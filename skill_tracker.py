"""Skill evolution tracker for hermes-memorex.

Tracks the lifecycle of Hermes Agent skills by reading SKILL.md files,
parsing git history (if available), and reading Curator logs to build
a comprehensive skill evolution timeline.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SkillChange:
    """A single change event in a skill's history."""

    date: str
    type: str  # created, modified, pruned, consolidated, retained
    summary: str
    diff: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CuratorAction:
    """A Curator action on a skill."""

    date: str
    action: str  # retained, pruned, consolidated, archived
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SkillInfo:
    """Complete information about a skill."""

    name: str
    description: str = ""
    created: Optional[str] = None
    modified: Optional[str] = None
    size_bytes: int = 0
    is_agent_authored: bool = False
    changes: list[SkillChange] = field(default_factory=list)
    curator_actions: list[CuratorAction] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["changes"] = [c.to_dict() for c in self.changes]
        d["curator_actions"] = [c.to_dict() for c in self.curator_actions]
        return d


@dataclass
class SkillEvolution:
    """Complete skill evolution data."""

    skills: list[SkillInfo] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    curator_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "skills": [s.to_dict() for s in self.skills],
            "timeline": self.timeline,
            "curator_summary": self.curator_summary,
        }


# ---------------------------------------------------------------------------
# SKILL.md frontmatter parser
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> dict:
    """Parse YAML-ish frontmatter from a SKILL.md file.

    Handles the simple key: value format used by Hermes skills
    without requiring a full YAML parser.
    """
    frontmatter: dict = {}
    lines = content.split("\n")

    in_frontmatter = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter:
            match = re.match(r"^(\w[\w\s]*?):\s*(.+)$", stripped)
            if match:
                key = match.group(1).strip().lower().replace(" ", "_")
                value = match.group(2).strip().strip("\"'")
                frontmatter[key] = value

    return frontmatter


def _extract_description(content: str) -> str:
    """Extract the first meaningful paragraph as a description."""
    in_frontmatter = False
    lines = content.split("\n")

    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        # Skip headings
        if stripped.startswith("#"):
            continue
        # Return first non-empty paragraph line
        if stripped and not stripped.startswith("```"):
            return stripped[:200]

    return ""


# ---------------------------------------------------------------------------
# Git history
# ---------------------------------------------------------------------------

def _run_git(args: list[str], cwd: str) -> Optional[str]:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _is_git_repo(path: str) -> bool:
    """Check if a path is inside a git repository."""
    return _run_git(["rev-parse", "--is-inside-work-tree"], path) is not None


def _get_git_log(filepath: str, cwd: str, include_diffs: bool = False) -> list[SkillChange]:
    """Get git log for a specific file."""
    changes: list[SkillChange] = []

    # Get log entries
    fmt = "--format=%H|||%aI|||%s"
    args = ["log", fmt, "--follow", "--", filepath]
    output = _run_git(args, cwd)
    if not output:
        return changes

    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|||")
        if len(parts) < 3:
            continue

        commit_hash, date, summary = parts[0], parts[1], parts[2]

        diff_text = None
        if include_diffs:
            diff_output = _run_git(
                ["diff", f"{commit_hash}~1..{commit_hash}", "--", filepath],
                cwd,
            )
            if diff_output:
                # Trim diff header, keep only +/- lines
                diff_lines = []
                for dl in diff_output.split("\n"):
                    if dl.startswith(("+", "-")) and not dl.startswith(
                        ("+++", "---")
                    ):
                        diff_lines.append(dl)
                diff_text = "\n".join(diff_lines[:50])  # Cap at 50 lines

        changes.append(
            SkillChange(
                date=date,
                type="modified",
                summary=summary,
                diff=diff_text,
            )
        )

    # The last entry in git log is the creation
    if changes:
        changes[-1].type = "created"

    return changes


# ---------------------------------------------------------------------------
# Curator log parser
# ---------------------------------------------------------------------------

def _parse_curator_logs(hermes_dir: Path) -> tuple[list[CuratorAction], dict]:
    """Parse Curator logs from the logs/curator/ directory.

    Returns:
        Tuple of (all_actions, summary_dict).
    """
    curator_dir = hermes_dir / "logs" / "curator"
    all_actions: list[CuratorAction] = []
    summary = {
        "total_runs": 0,
        "skills_pruned": 0,
        "skills_consolidated": 0,
        "skills_retained": 0,
        "skills_archived": 0,
    }

    if not curator_dir.exists():
        return all_actions, summary

    # Parse run.json files
    for run_file in sorted(curator_dir.glob("**/run.json")):
        try:
            data = json.loads(run_file.read_text(encoding="utf-8"))
            summary["total_runs"] += 1

            for action_data in data.get("actions", []):
                action = CuratorAction(
                    date=action_data.get("timestamp", ""),
                    action=action_data.get("action", "unknown"),
                    reason=action_data.get("reason", ""),
                )
                all_actions.append(action)

                action_type = action.action.lower()
                if action_type in summary:
                    summary[f"skills_{action_type}"] += 1
        except (json.JSONDecodeError, OSError):
            continue

    # Parse REPORT.md files for additional context
    for report_file in sorted(curator_dir.glob("**/REPORT.md")):
        try:
            content = report_file.read_text(encoding="utf-8")

            # Extract actions from markdown report
            action_pattern = re.compile(
                r"[-*]\s+\*\*(\w+)\*\*\s*:\s*`?([^`\n]+)`?\s*[-—]\s*(.+)",
            )
            for match in action_pattern.finditer(content):
                action_type = match.group(1).lower()
                skill_name = match.group(2).strip()
                reason = match.group(3).strip()

                # Get date from filename or parent dir
                date_match = re.search(
                    r"(\d{4}-\d{2}-\d{2})", str(report_file)
                )
                date = date_match.group(1) if date_match else ""

                all_actions.append(
                    CuratorAction(
                        date=date, action=action_type, reason=reason
                    )
                )
        except OSError:
            continue

    return all_actions, summary


# ---------------------------------------------------------------------------
# Main tracker
# ---------------------------------------------------------------------------

def track_skills(
    hermes_dir: Optional[str | Path] = None,
    skill_name: Optional[str] = None,
    include_diffs: bool = False,
) -> SkillEvolution:
    """Track skill evolution across the Hermes skills directory.

    Args:
        hermes_dir: Override path to the Hermes home directory.
        skill_name: Filter to a specific skill by name.
        include_diffs: Include git diffs for each change.

    Returns:
        SkillEvolution with all skills, timeline, and curator summary.
    """
    if hermes_dir is None:
        hermes_dir = Path.home() / ".hermes"
    else:
        hermes_dir = Path(hermes_dir)

    skills_dir = hermes_dir / "skills"
    result = SkillEvolution()

    if not skills_dir.exists():
        return result

    has_git = _is_git_repo(str(skills_dir))

    # Parse curator logs
    curator_actions, curator_summary = _parse_curator_logs(hermes_dir)
    result.curator_summary = curator_summary

    # Map curator actions by skill name
    curator_by_skill: dict[str, list[CuratorAction]] = {}
    for action in curator_actions:
        # Try to extract skill name from reason or action context
        # This is a best-effort mapping
        curator_by_skill.setdefault("_global", []).append(action)

    # Scan skills directory
    skill_files: list[Path] = []

    # Skills can be individual .md files or directories with SKILL.md
    for item in skills_dir.iterdir():
        if item.is_file() and item.suffix == ".md":
            skill_files.append(item)
        elif item.is_dir():
            skill_md = item / "SKILL.md"
            if skill_md.exists():
                skill_files.append(skill_md)

    for skill_path in sorted(skill_files):
        # Determine skill name
        if skill_path.name == "SKILL.md":
            name = skill_path.parent.name
        else:
            name = skill_path.stem

        # Apply name filter
        if skill_name and name.lower() != skill_name.lower():
            continue

        try:
            content = skill_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Parse frontmatter
        frontmatter = _parse_frontmatter(content)
        description = (
            frontmatter.get("description", "")
            or _extract_description(content)
        )

        # File metadata
        stat = skill_path.stat()
        created_ts = datetime.fromtimestamp(stat.st_ctime).isoformat()
        modified_ts = datetime.fromtimestamp(stat.st_mtime).isoformat()

        # Determine if agent-authored
        is_agent = frontmatter.get("author", "").lower() in (
            "hermes",
            "agent",
            "auto",
            "self",
        ) or "agent_authored" in frontmatter

        # Build change history
        changes: list[SkillChange] = []
        if has_git:
            rel_path = str(skill_path.relative_to(skills_dir))
            changes = _get_git_log(rel_path, str(skills_dir), include_diffs)

        if not changes:
            # No git history — create synthetic entries from file timestamps
            changes.append(
                SkillChange(
                    date=created_ts,
                    type="created",
                    summary=f"Skill '{name}' created",
                )
            )
            if modified_ts != created_ts:
                changes.append(
                    SkillChange(
                        date=modified_ts,
                        type="modified",
                        summary=f"Skill '{name}' modified",
                    )
                )

        skill_info = SkillInfo(
            name=name,
            description=description,
            created=created_ts,
            modified=modified_ts,
            size_bytes=stat.st_size,
            is_agent_authored=is_agent,
            changes=changes,
            curator_actions=curator_by_skill.get(name, []),
        )
        result.skills.append(skill_info)

    # Build unified timeline
    timeline: list[dict] = []
    for skill in result.skills:
        for change in skill.changes:
            timeline.append({
                "date": change.date,
                "event": change.type,
                "skill": skill.name,
                "summary": change.summary,
            })
    for action in curator_actions:
        timeline.append({
            "date": action.date,
            "event": f"curator_{action.action}",
            "skill": "_curator",
            "summary": action.reason,
        })

    # Sort timeline chronologically
    timeline.sort(key=lambda e: e.get("date", ""))
    result.timeline = timeline

    return result

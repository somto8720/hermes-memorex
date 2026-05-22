"""Tests for the skill evolution tracker module."""

import json
from pathlib import Path

from hermes_memorex.skill_tracker import (
    SkillInfo,
    SkillChange,
    CuratorAction,
    SkillEvolution,
    track_skills,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_SKILL_MD = """\
---
name: github-workflow
description: Manages the full GitHub PR lifecycle
author: agent
version: "1.0"
---

# GitHub Workflow

When working with GitHub repositories, follow this process:

## Creating a Branch

1. Check current branch with `git branch`
2. Create a new feature branch: `git checkout -b feature/description`

## Making Changes

- Stage changes: `git add .`
- Commit with conventional message: `git commit -m "feat: description"`

## Pull Request

1. Push the branch: `git push origin feature/description`
2. Create a PR with a clear title and description
3. Request review from appropriate team members
"""

SAMPLE_CURATOR_RUN = {
    "timestamp": "2026-04-01T00:00:00Z",
    "actions": [
        {
            "timestamp": "2026-04-01T00:00:00Z",
            "action": "retained",
            "reason": "High usage frequency (15 invocations in last 30 days)",
        },
        {
            "timestamp": "2026-04-01T00:00:00Z",
            "action": "pruned",
            "reason": "Duplicate of docker-deploy skill",
        },
    ],
}


def _setup_skills_dir(tmp_path: Path) -> Path:
    """Set up a mock Hermes directory with skills."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # Create a skill as a directory with SKILL.md
    gh_skill = skills_dir / "github-workflow"
    gh_skill.mkdir()
    (gh_skill / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")

    # Create a skill as a standalone .md file
    (skills_dir / "docker-deploy.md").write_text(
        "---\nname: docker-deploy\ndescription: Docker deployment workflow\n---\n\n"
        "# Docker Deploy\n\nDeploy containers using docker-compose.\n",
        encoding="utf-8",
    )

    return tmp_path


def _setup_curator_logs(tmp_path: Path) -> None:
    """Set up mock Curator logs."""
    curator_dir = tmp_path / "logs" / "curator" / "2026-04-01"
    curator_dir.mkdir(parents=True)

    (curator_dir / "run.json").write_text(
        json.dumps(SAMPLE_CURATOR_RUN), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# track_skills tests
# ---------------------------------------------------------------------------

class TestTrackSkills:
    """Tests for the skill evolution tracker."""

    def test_discovers_skills(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        assert isinstance(result, SkillEvolution)
        assert len(result.skills) == 2

    def test_skill_names(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        names = {s.name for s in result.skills}
        assert "github-workflow" in names
        assert "docker-deploy" in names

    def test_parses_frontmatter(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        gh_skill = next(s for s in result.skills if s.name == "github-workflow")
        assert "GitHub PR lifecycle" in gh_skill.description or gh_skill.description != ""

    def test_detects_agent_authored(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        gh_skill = next(s for s in result.skills if s.name == "github-workflow")
        assert gh_skill.is_agent_authored is True

    def test_has_file_metadata(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        for skill in result.skills:
            assert skill.size_bytes > 0
            assert skill.created is not None
            assert skill.modified is not None

    def test_creates_synthetic_timeline_without_git(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        for skill in result.skills:
            assert len(skill.changes) >= 1
            assert skill.changes[0].type == "created"

    def test_filter_by_name(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir, skill_name="github-workflow")

        assert len(result.skills) == 1
        assert result.skills[0].name == "github-workflow"

    def test_builds_timeline(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)

        assert len(result.timeline) > 0
        # Timeline should be sorted by date
        dates = [e["date"] for e in result.timeline if e["date"]]
        assert dates == sorted(dates)

    def test_parses_curator_logs(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        _setup_curator_logs(tmp_path)
        result = track_skills(hermes_dir)

        assert result.curator_summary["total_runs"] >= 1

    def test_handles_missing_skills_dir(self, tmp_path: Path):
        result = track_skills(tmp_path)
        assert len(result.skills) == 0

    def test_handles_empty_skills_dir(self, tmp_path: Path):
        (tmp_path / "skills").mkdir()
        result = track_skills(tmp_path)
        assert len(result.skills) == 0

    def test_to_dict_structure(self, tmp_path: Path):
        hermes_dir = _setup_skills_dir(tmp_path)
        result = track_skills(hermes_dir)
        data = result.to_dict()

        assert "skills" in data
        assert "timeline" in data
        assert "curator_summary" in data
        assert isinstance(data["skills"], list)
        assert isinstance(data["timeline"], list)

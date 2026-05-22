"""Pytest configuration for hermes-memorex tests.

Adds the project root to sys.path so the package can be imported
as 'hermes_memorex' regardless of the directory name.
"""

import sys
from pathlib import Path

# Add project root to path, aliased as hermes_memorex
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Create an alias so 'import hermes_memorex' works
# even though the directory is named 'hermes-memorex'
import importlib
import types

# Import the package from the current directory structure
spec = importlib.util.spec_from_file_location(
    "hermes_memorex",
    project_root / "__init__.py",
    submodule_search_locations=[str(project_root)],
)
if spec and spec.loader:
    module = importlib.util.module_from_spec(spec)
    sys.modules["hermes_memorex"] = module

    # Register submodules
    for submod in [
        "memory_parser",
        "graph_builder",
        "skill_tracker",
        "schemas",
        "tools",
        "server",
    ]:
        submod_path = project_root / f"{submod}.py"
        if submod_path.exists():
            sub_spec = importlib.util.spec_from_file_location(
                f"hermes_memorex.{submod}",
                submod_path,
            )
            if sub_spec and sub_spec.loader:
                sub_module = importlib.util.module_from_spec(sub_spec)
                sys.modules[f"hermes_memorex.{submod}"] = sub_module
                sub_spec.loader.exec_module(sub_module)
                setattr(module, submod, sub_module)

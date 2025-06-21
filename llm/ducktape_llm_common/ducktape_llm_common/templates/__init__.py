"""Templates for quick-start project structures.

This module provides functions to create standard project structures
for investigations, tasks, and other common workflows.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

# Import METADATA_VERSION from parent package to avoid circular import
import ducktape_llm_common


def create_investigation_structure(
    root_path: Union[str, Path],
    investigation_name: str,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Create a standard investigation folder structure.

    Args:
        root_path: Root directory where to create the investigation
        investigation_name: Name of the investigation (will be the folder name)
        description: Optional description for the investigation
        metadata: Optional additional metadata to include

    Returns:
        Path to the created investigation directory
    """
    root_path = Path(root_path)
    inv_dir = root_path / investigation_name

    # Create directory structure
    inv_dir.mkdir(parents=True, exist_ok=True)
    (inv_dir / "findings").mkdir(exist_ok=True)
    (inv_dir / "evidence").mkdir(exist_ok=True)
    (inv_dir / "scripts").mkdir(exist_ok=True)

    # Create README.md
    readme_content = f"""# Investigation: {investigation_name}

## Description
{description or "TODO: Add investigation description"}

## Status
- Started: {__import__("datetime").datetime.now().isoformat()}
- Status: In Progress

## Findings
See the `findings/` directory for detailed findings.

## Evidence
Supporting evidence is stored in the `evidence/` directory.

## Scripts
Any analysis scripts are in the `scripts/` directory.
"""
    (inv_dir / "README.md").write_text(readme_content)

    # Create METADATA.yaml
    default_metadata = {
        "metadata_version": ducktape_llm_common.METADATA_VERSION,
        "type": "investigation",
        "name": investigation_name,
        "description": description or "",
        "created": __import__("datetime").datetime.now().isoformat(),
        "status": "in_progress",
        "tags": [],
    }

    if metadata:
        default_metadata.update(metadata)

    with open(inv_dir / "METADATA.yaml", "w") as f:
        yaml.dump(default_metadata, f, default_flow_style=False, sort_keys=False)

    # Create .metadata-version file
    (inv_dir / ".metadata-version").write_text(
        f"{ducktape_llm_common.METADATA_VERSION}\n"
    )

    # Create .gitignore
    gitignore_content = """# Temporary files
*.tmp
*.log
.DS_Store

# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/

# IDE
.vscode/
.idea/
*.swp
*.swo
"""
    (inv_dir / ".gitignore").write_text(gitignore_content)

    return inv_dir


def create_task_structure(
    root_path: Union[str, Path],
    task_name: str,
    task_type: str = "task",
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    """Create a standard task folder structure.

    Args:
        root_path: Root directory where to create the task
        task_name: Name of the task (will be the folder name)
        task_type: Type of task (task, subtask, etc.)
        description: Optional description for the task
        metadata: Optional additional metadata to include

    Returns:
        Path to the created task directory
    """
    root_path = Path(root_path)
    task_dir = root_path / task_name

    # Create directory structure
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "work").mkdir(exist_ok=True)
    (task_dir / "output").mkdir(exist_ok=True)

    # Create TASK.md
    task_content = f"""# Task: {task_name}

## Objective
{description or "TODO: Add task objective"}

## Requirements
- TODO: Add specific requirements

## Deliverables
- TODO: List expected deliverables

## Success Criteria
- TODO: Define success criteria
"""
    (task_dir / "TASK.md").write_text(task_content)

    # Create METADATA.yaml
    default_metadata = {
        "metadata_version": ducktape_llm_common.METADATA_VERSION,
        "type": task_type,
        "name": task_name,
        "description": description or "",
        "created": __import__("datetime").datetime.now().isoformat(),
        "status": "pending",
        "tags": [],
        "dependencies": [],
    }

    if metadata:
        default_metadata.update(metadata)

    with open(task_dir / "METADATA.yaml", "w") as f:
        yaml.dump(default_metadata, f, default_flow_style=False, sort_keys=False)

    # Create .metadata-version file
    (task_dir / ".metadata-version").write_text(
        f"{ducktape_llm_common.METADATA_VERSION}\n"
    )

    # Create PLAN.md
    plan_content = """# Execution Plan

## Phase 1: Analysis
- [ ] Understand requirements
- [ ] Identify constraints
- [ ] Research existing solutions

## Phase 2: Implementation
- [ ] TODO: Add implementation steps

## Phase 3: Validation
- [ ] Test implementation
- [ ] Verify against requirements
- [ ] Document results
"""
    (task_dir / "PLAN.md").write_text(plan_content)

    # Create OUTPUT.md template
    output_content = """# Task Output

## Status: PENDING

## Summary
TODO: Add execution summary when complete

## Deliverables
TODO: List completed deliverables

## Notes
TODO: Add any important notes or findings
"""
    (task_dir / "OUTPUT.md").write_text(output_content)

    return task_dir


def create_task_graph_template(
    root_path: Union[str, Path], graph_name: str = "TASK_GRAPH.md"
) -> Path:
    """Create a template TASK_GRAPH.md file.

    Args:
        root_path: Directory where to create the file
        graph_name: Name of the file (defaults to TASK_GRAPH.md)

    Returns:
        Path to the created file
    """
    root_path = Path(root_path)
    graph_file = root_path / graph_name

    template_content = """# Task Graph

## Overview
This document defines the dependency graph for tasks in this project.

## Task Definitions

### Phase 1: Foundation
- **task01-setup**: Initial project setup
  - Description: Set up basic project structure
  - Dependencies: None
  - Deliverables: Project skeleton

### Phase 2: Implementation
- **task02-core**: Core implementation
  - Description: Implement core functionality
  - Dependencies: [task01-setup]
  - Deliverables: Working core module

- **task03-tests**: Test suite
  - Description: Create comprehensive tests
  - Dependencies: [task02-core]
  - Deliverables: Test suite with >80% coverage

### Phase 3: Documentation
- **task04-docs**: Documentation
  - Description: Write user and developer documentation
  - Dependencies: [task02-core, task03-tests]
  - Deliverables: Complete documentation

## Dependency Graph

```mermaid
graph TD
    task01-setup --> task02-core
    task02-core --> task03-tests
    task02-core --> task04-docs
    task03-tests --> task04-docs
```

## Execution Order
1. task01-setup
2. task02-core
3. task03-tests (can run in parallel with task04-docs after task02-core)
4. task04-docs
"""

    graph_file.write_text(template_content)
    return graph_file


def list_template_types() -> list[str]:
    """List available template types.

    Returns:
        List of template type names
    """
    return ["investigation", "task", "task_graph"]


__all__ = [
    "create_investigation_structure",
    "create_task_structure",
    "create_task_graph_template",
    "list_template_types",
]

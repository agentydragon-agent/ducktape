"""Generate .github/workflows/ from workflows.yaml.

Generates ci.yml and per-package release workflow files,
eliminating duplication in job definitions.

Usage:
    bazel run //devinfra/ci:generate_ci_bin
"""

from __future__ import annotations

from pathlib import Path

import yaml

from devinfra.ci.github_actions import Job, Step, Workflow
from devinfra.ci.models import WorkflowConfig, WorkflowManifest
from devinfra.prettier import prettier_format_in_place
from util.bazel.workspace import get_build_workspace_directory

SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
WORKFLOWS_YAML = SCRIPT_DIR / "workflows.yaml"
# Runfiles path — used by tests to check generated files against expectations
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


HEADER = """\
# AUTO-GENERATED from devinfra/ci/workflows.yaml - DO NOT EDIT DIRECTLY
# Regenerate with: bazel run //devinfra/ci:generate_ci_bin
"""


COMPUTE_TARGETS_JOB = Job(
    name="Compute affected targets",
    runs_on="ubuntu-latest",
    timeout_minutes=30,
    outputs={"workflows": "${{ steps.decide.outputs.workflows }}"},
    steps=[
        Step(uses="actions/checkout@v6", with_args={"fetch-depth": 0}),
        Step(uses="astral-sh/setup-uv@v7"),
        Step(name="Compute CI decision", id="decide", run="uv run devinfra/ci/ci_decide.py"),
    ],
)


RBE_IMAGE_JOB = "rbe-image"


def _uses_rbe(name: str, config: WorkflowConfig) -> bool:
    """Whether this workflow uses BuildBuddy RBE and should receive rbe_image."""
    return name != RBE_IMAGE_JOB and config.secrets == "inherit" and config.rbe


def build_workflow_job(name: str, config: WorkflowConfig, *, has_rbe_image_job: bool) -> Job:
    """Build a job definition from workflow config."""
    with_args: dict[str, str] = {}
    if config.inputs:
        with_args.update(config.inputs)

    needs: str | list[str] = "compute-targets"
    if_cond = f"contains(fromJson(needs.compute-targets.outputs.workflows || '[]'), '{name}')"

    # Bazel workflows that use RBE should wait for the rbe-image job (when
    # it exists) and forward the built image reference. The job may be skipped
    # when no RBE image files changed, so we allow skipped results.
    if has_rbe_image_job and _uses_rbe(name, config):
        needs = ["compute-targets", RBE_IMAGE_JOB]
        if_cond = (
            f"always() && !cancelled() && !failure() "
            f"&& contains(fromJson(needs.compute-targets.outputs.workflows || '[]'), '{name}')"
        )
        with_args["rbe_image"] = f"${{{{ needs.{RBE_IMAGE_JOB}.outputs.rbe_image }}}}"

    return Job(
        needs=needs,
        if_cond=if_cond,
        uses=f"./.github/workflows/{name}.yml",
        with_args=with_args or None,
        secrets=config.secrets,
    )


def generate_ci_config(manifest: WorkflowManifest) -> Workflow:
    """Generate the complete ci.yml config."""
    has_rbe_image_job = RBE_IMAGE_JOB in manifest.workflows

    jobs: dict[str, Job] = {"compute-targets": COMPUTE_TARGETS_JOB}
    for name, config in manifest.workflows.items():
        jobs[name] = build_workflow_job(name, config, has_rbe_image_job=has_rbe_image_job)

    # Jobs that push to GHCR need packages:write.
    ghcr_jobs = {"rbe-image", "e2e-container-image"}
    permissions: dict[str, str] = {"contents": "read"}
    if ghcr_jobs & manifest.workflows.keys():
        permissions["packages"] = "write"

    # rbe-image.yml declares permissions: contents: write (to pin the built image
    # tag in BUILD.bazel via git push). GitHub Actions validates at startup that the
    # calling workflow grants at least the permissions declared by called workflows,
    # so ci.yml must also declare contents: write when rbe-image is present.
    if "rbe-image" in manifest.workflows:
        permissions["contents"] = "write"

    return Workflow(
        name="CI",
        on={"push": {"branches": ["main", "master", "devel"]}, "pull_request": None, "workflow_dispatch": None},
        concurrency={"group": "${{ github.workflow }}-${{ github.ref }}", "cancel-in-progress": True},
        permissions=permissions,
        jobs=jobs,
    )


def generate_ci_yml(workflow: Workflow) -> str:
    """Generate the complete ci.yml content."""
    config = workflow.model_dump(by_alias=True, exclude_none=True)

    # Custom representer for multiline strings
    def str_representer(dumper: yaml.Dumper, data: str) -> yaml.Node:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, str_representer)

    yaml_content = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
    return HEADER + yaml_content


def write_workflow(path: Path, workflow: Workflow) -> None:
    """Write a workflow file and run prettier to match pre-commit formatting."""
    path.write_text(generate_ci_yml(workflow))
    prettier_format_in_place(path)
    print(f"Generated {path}")


def main() -> None:
    """Main entry point."""
    manifest = WorkflowManifest.from_yaml(WORKFLOWS_YAML)

    out_dir = get_build_workspace_directory() / ".github" / "workflows"
    write_workflow(out_dir / "ci.yml", generate_ci_config(manifest))


if __name__ == "__main__":
    main()

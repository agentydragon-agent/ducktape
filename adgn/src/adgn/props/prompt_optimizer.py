"""Prompt optimizer implementation.

Runs an LLM agent to optimize critic prompts using train/valid/test splits
with budget tracking and granular evaluation tools.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from importlib import resources
import logging
from pathlib import Path
import shutil
import tempfile

from fastmcp.client import Client

from adgn.agent.agent import MiniCodex
# from adgn.agent.event_renderer import DisplayEventsHandler
from adgn.agent.handler import BaseHandler
from adgn.agent.loop_control import Abort, Auto, Continue
from adgn.agent.rich_display import RichDisplayHandler
from adgn.agent.transcript_handler import TranscriptHandler
from adgn.mcp._shared.constants import PROMPT_EVAL_SERVER_NAME
from adgn.mcp.compositor.server import Compositor
from adgn.openai_utils.client_factory import build_client
from adgn.props.docker_env import properties_docker_spec
from adgn.props.prompt_eval.server import PromptEvalState, attach_prompt_eval
from adgn.props.prop_utils import pkg_dir, specimens_definitions_root
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.splits import get_train_specimens

logger = logging.getLogger(__name__)


class BudgetHandler(BaseHandler):
    """Loop controller: continue while budget remains, abort when exceeded."""

    def __init__(self, state: PromptEvalState) -> None:
        self._state = state

    def on_before_sample(self):
        """Check budget and decide whether to continue or abort."""
        if self._state.budget_limit and self._state.total_cost >= self._state.budget_limit:
            logger.info(
                f"Budget exhausted: ${self._state.total_cost:.2f} >= ${self._state.budget_limit:.2f}"
            )
            return Abort()
        return Continue(Auto())


@asynccontextmanager
async def hydrate_train_specimens_to_temp():
    """Hydrate all train specimens to temp directories, yield (specimen_paths, defs_root).

    Returns:
        specimen_paths: {specimen_slug: Path_to_hydrated_copy}
        train_defs_root: Path to temp directory with train specimen definitions only
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="train_specimens_"))
    train_defs_dir = Path(tempfile.mkdtemp(prefix="train_defs_"))
    specimen_paths: dict[str, Path] = {}

    try:
        train_specimens = get_train_specimens()
        logger.info(f"Hydrating {len(train_specimens)} train specimens to {tmpdir}")

        specimens_defs_root = specimens_definitions_root()

        for slug in train_specimens:
            # Hydrate source code
            rec = SpecimenRegistry.load_strict(slug)
            async with rec.hydrated_copy(gitconfig=None) as content_root:
                # Copy hydrated content to persistent temp location
                # Use slug directly (repo/specimen-name form)
                dest = tmpdir / slug
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(content_root, dest, symlinks=True)
                specimen_paths[slug] = dest
                logger.debug(f"Hydrated {slug} to {dest}")

            # Copy specimen definitions (ground truth) to train-only defs directory
            def_src = specimens_defs_root / slug
            if def_src.exists():
                def_dest = train_defs_dir / slug
                def_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(def_src, def_dest, symlinks=True)
                logger.debug(f"Copied definitions {slug} to {def_dest}")

        yield specimen_paths, train_defs_dir
    finally:
        # Cleanup temp directories
        logger.info(f"Cleaning up hydrated specimens: {tmpdir}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        logger.info(f"Cleaning up train definitions: {train_defs_dir}")
        shutil.rmtree(train_defs_dir, ignore_errors=True)


async def run_prompt_optimizer(
    budget: float,
    out_dir: Path | None = None,
    model: str = "gpt-5",
    agent_model: str = "gpt-5-mini",
    verbose: bool = False,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt.

    Args:
        budget: $ budget for optimization
        out_dir: Output directory (defaults to runs/prompt_optimize_<timestamp>)
        model: Model ID to use for optimization agent
        agent_model: Model ID to use for inner critic agent during evaluations
        verbose: If True, display inner agent (critic/grader) events during evaluations
    """
    # Load system prompt from prompts directory
    system = (resources.files(__package__) / "prompts" / "prompt_optimizer_system.md").read_text(encoding="utf-8")

    # Session directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = (out_dir if out_dir is not None else (pkg_dir() / "runs" / f"prompt_optimize_{ts}")).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)

    # Shared evaluation directories
    evals_base = (pkg_dir() / "runs" / "prompt_evals").resolve()
    evals_base.mkdir(parents=True, exist_ok=True)

    # Hydrate train specimens to temp directories
    async with hydrate_train_specimens_to_temp() as (train_specimens, train_defs_root):
        # Build extra volumes for Docker (specimens + eval results + definitions)
        # Format: {host_path: {"bind": container_path, "mode": "ro"|"rw"}}
        extra_volumes = {}

        # Train specimens source code (ro) - use original slug form (repo/specimen-name)
        for slug, path in train_specimens.items():
            extra_volumes[str(path.resolve())] = {
                "bind": f"/specimens/train/{slug}",
                "mode": "ro"
            }

        # Mount train-only specimen definitions (ground truth issues)
        # This prevents leaking test split data to the optimization agent
        # Mount at /specimen_defs/train to match specimen source structure
        extra_volumes[str(train_defs_root.resolve())] = {
            "bind": "/specimen_defs/train",
            "mode": "ro"
        }

        # Past evaluation results (ro) - already resolved above
        extra_volumes[str(evals_base)] = {
            "bind": "/artifacts/prompt_evals",
            "mode": "ro"
        }

        # Create Docker wiring (no /repo mount - would leak test specimen definitions!)
        # workspace_root will be mounted as /workspace (rw mode for agent to write prompts)
        wiring = properties_docker_spec(
            workspace_root=session_dir,
            mount_properties=False,  # No property definitions mounted
            extra_volumes=extra_volumes,
            ephemeral=True,
            workspace_mode="rw",  # Agent needs to write prompt iterations
        )

        comp = Compositor("compositor")
        runtime_server = await wiring.attach(comp)  # Attaches runtime MCP server

        prompt_eval_server, pe_state = await attach_prompt_eval(
            comp,
            client=build_client(model),
            name=PROMPT_EVAL_SERVER_NAME,
            agent_model=agent_model,
            evals_base_dir=evals_base,
            workspace_host_path=session_dir,  # Map /workspace to host session_dir
        )
        pe_state.budget_limit = budget
        pe_state.verbose = verbose

        # Collect servers for tool schema extraction
        servers = {
            wiring.server_name: runtime_server,
            PROMPT_EVAL_SERVER_NAME: prompt_eval_server,
        }

        user = f"""Your budget is: ${budget:.2f}.

Iterate to find an optimal prompt for a code reviewer/critic LLM agent.
Prioritize recall first, then precision.

Start with cheap iterations (eval_file, eval_specimen) to explore quickly.
Run expensive eval_split() when you have a promising candidate.

Write prompts to /workspace (e.g., /workspace/prompts/v1.txt).
Organize your work however you like.

The critic will run in a harness ensuring proper output format.
Do not prescribe output schemas explicitly in your prompt.
"""

        async with Client(comp) as mcp_client:
            agent = await MiniCodex.create(
                model=model,
                mcp_client=mcp_client,
                system=system,
                client=build_client(model),
                handlers=[
                    BudgetHandler(pe_state),  # Loop control: abort when budget exhausted
                    TranscriptHandler(dest_dir=session_dir / "transcript"),
                    RichDisplayHandler(max_lines=50, prefix="[OPTIMIZER] ", servers=servers),
                ],
                parallel_tool_calls=True,
            )

            res = await agent.run(user)
            (session_dir / "final.md").write_text(res.text, encoding="utf-8")

        logger.info(f"Optimization session complete. Results in: {session_dir}")
        logger.info(f"Total cost: ${pe_state.total_cost:.2f} / ${budget:.2f}")

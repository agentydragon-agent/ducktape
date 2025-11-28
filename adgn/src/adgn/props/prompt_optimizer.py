"""Prompt optimizer implementation.

Runs an LLM agent to optimize critic prompts using train/valid/test splits
with budget tracking and granular evaluation tools.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
from importlib import resources
import logging
from pathlib import Path

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
from adgn.props.prop_utils import specimens_definitions_root
from adgn.props.runs_context import RunsContext
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
            logger.info(f"Budget exhausted: ${self._state.total_cost:.2f} >= ${self._state.budget_limit:.2f}")
            return Abort()
        return Continue(Auto())


@asynccontextmanager
async def hydrate_train_specimens() -> AsyncIterator[tuple[dict[str, Path], Path]]:
    """Hydrate all train specimens and keep them alive for direct Docker mounting.

    Uses AsyncExitStack to keep all specimens hydrated until context exits.
    No copying - mount each specimen and its definitions directly as separate Docker volumes.

    Yields:
        (specimen_paths, defs_root):
            - specimen_paths: {specimen_slug: Path_to_hydrated_specimen} - mount each as /specimens/{slug}
            - defs_root: Base path to specimen definitions - mount {slug} subdirs as /defs/{slug}
    """
    specimen_paths: dict[str, Path] = {}
    defs_root = specimens_definitions_root()

    async with AsyncExitStack() as stack:
        train_specimens = get_train_specimens()
        logger.info(f"Hydrating {len(train_specimens)} train specimens (for direct Docker mount)")

        for slug in train_specimens:
            # Load and hydrate specimen, keep alive for Docker mounting
            _rec, content_root = await stack.enter_async_context(
                SpecimenRegistry.load_and_hydrate(slug, gitconfig=None)
            )
            # No copying - mount hydrated path directly as separate Docker volume
            specimen_paths[slug] = content_root
            logger.debug(f"Hydrated {slug} → {content_root} (mount as /specimens/{slug})")

        # Return base definitions directory - consumer mounts defs_root/{slug} for each train specimen
        logger.info(f"Definitions available at {defs_root} (mount subdirs as /defs/{{slug}})")

        yield specimen_paths, defs_root
        # AsyncExitStack will cleanup all hydrated specimens automatically


async def run_prompt_optimizer(
    budget: float,
    ctx: RunsContext,
    out_dir: Path | None = None,
    model: str = "gpt-5",
    agent_model: str = "gpt-5-mini",
    verbose: bool = False,
) -> None:
    """Run a Prompt Engineering agent to optimize a critic system prompt.

    Args:
        budget: $ budget for optimization
        ctx: RunsContext for path derivation (injected from CLI)
        out_dir: Output directory (defaults to runs/prompt_optimize_<timestamp>)
        model: Model ID to use for optimization agent
        agent_model: Model ID to use for inner critic agent during evaluations
        verbose: If True, display inner agent (critic/grader) events during evaluations
    """
    # Load system prompt from prompts directory
    system = (resources.files(__package__) / "prompts" / "prompt_optimizer_system.md").read_text(encoding="utf-8")

    # Session directory
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = (out_dir if out_dir is not None else ctx.prompt_optimize_output_dir(ts)).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)

    # Shared evaluation directories
    evals_base = ctx.prompt_evals_dir().resolve()
    evals_base.mkdir(parents=True, exist_ok=True)

    # Hydrate train specimens and keep alive for Docker mounting
    async with hydrate_train_specimens() as (train_specimens, defs_root):
        # Build extra volumes for Docker (specimens + eval results + definitions)
        # Format: {host_path: {"bind": container_path, "mode": "ro"|"rw"}}
        extra_volumes = {}

        # Train specimens source code (ro) - mount each separately
        for slug, path in train_specimens.items():
            extra_volumes[str(path.resolve())] = {"bind": f"/specimens/train/{slug}", "mode": "ro"}

        # Mount train specimen definitions separately (ground truth issues)
        # This prevents leaking test/valid split data to the optimization agent
        for slug in train_specimens:
            def_path = defs_root / slug
            if def_path.exists():
                extra_volumes[str(def_path.resolve())] = {"bind": f"/specimen_defs/train/{slug}", "mode": "ro"}

        # Past evaluation results (ro) - ONLY mount train split to prevent validation leakage
        # Create train/ directory eagerly (required for Docker mount)
        train_evals = evals_base / "train"
        train_evals.mkdir(parents=True, exist_ok=True)
        extra_volumes[str(train_evals)] = {"bind": "/artifacts/prompt_evals/train", "mode": "ro"}

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
        servers = {wiring.server_name: runtime_server, PROMPT_EVAL_SERVER_NAME: prompt_eval_server}

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

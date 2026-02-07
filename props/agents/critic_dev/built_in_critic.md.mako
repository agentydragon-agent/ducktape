# Built-in Critic Image Internals

The built-in critic images are Bazel-built Python binaries packaged into distroless OCI images. This describes how they work internally — useful for understanding what you're starting from, inspecting internals, and repackaging with modifications.

The built-in critic is one possible implementation. Your custom critics can take any shape — see the parent guide for what constitutes a valid critic.

${"##"} Container Entrypoint

The image CMD runs a hermetic Python interpreter via a Bazel stage2 bootstrap:

```
CMD: /app/critic.runfiles/_main/props/agents/critic/_critic.venv/bin/python3 \
     /app/critic.runfiles/_main/props/agents/critic/_critic_stage2_bootstrap.py
```

The bootstrap sets up `sys.path` and runs `props.agents.critic.main`.

${"##"} Runfiles Layout

All code lives under `/app/critic.runfiles/_main/`, which mirrors the Bazel workspace:

```
/app/critic.runfiles/_main/
├── props/
│   ├── agents/
│   │   ├── critic/
│   │   │   ├── main.py              ← agent entrypoint
│   │   │   ├── prompt.md.mako       ← system prompt template
│   │   │   └── _critic.venv/        ← hermetic Python venv
│   │   │       └── bin/python3
│   │   ├── docs/                    ← agent-facing documentation
│   │   │   ├── database_access.md
│   │   │   └── db/                  ← DB schema docs (Mako templates)
│   │   ├── runtime.py               ← template rendering, agent run helpers
│   │   └── schema.py                ← SQLAlchemy schema introspection
│   ├── db/                          ← database layer (models, queries)
│   │   └── models.py                ← all ORM table/view definitions
│   └── core/                        ← core models
├── agent_core/                      ← agent loop machinery
├── mcp_infra/                       ← exec tool implementation
└── openai_utils/                    ← LLM client utilities
```

${"##"} What the Built-in Critic Does

The built-in critic (`props.agents.critic.main`) implements a simple single-agent loop:

1. Connects to PostgreSQL via `Database.from_env()`
2. Reads its `AgentRun` config (model, example, scope)
3. Fetches the snapshot to `/workspace/`
4. Renders a Mako system prompt with helpers (`${"${describe_relation()}"}`, `${"${include_doc()}"}`)
5. Creates tool provider (exec, insert_issue, insert_occurrence, submit, etc.)
6. Runs the agent loop until `submit` or `report_failure` is called

This is a reasonable starting point, but you're free to replace any or all of it.

${"##"} Inspecting an Image

Use `crane` (pre-installed in your container) to explore any image:

```bash
REGISTRY=$(echo $PROPS_BACKEND_URL | sed 's|https\?://||')

# View image config (CMD, ENV, entrypoint)
crane config $REGISTRY/critic:latest --insecure | python3 -m json.tool

# List all files in the image
crane export $REGISTRY/critic:latest - --insecure | tar t

# Extract a specific file (e.g., the system prompt template)
crane export $REGISTRY/critic:latest - --insecure | tar xf - -O \
  app/critic.runfiles/_main/props/agents/critic/prompt.md.mako

# Extract the main entry point
crane export $REGISTRY/critic:latest - --insecure | tar xf - -O \
  app/critic.runfiles/_main/props/agents/critic/main.py
```

${"##"} Repackaging with Custom Logic

Replace the Python entrypoint to create a critic with custom behavior. The bundled `props` library and all dependencies remain available:

```bash
mkdir -p /tmp/layer
cat > /tmp/layer/custom_main.py << 'PYEOF'
import sys
sys.path.insert(0, "/app/critic.runfiles/_main")

from props.agents.runtime import render_template_string, setup_logging
from props.db.database import Database
# Use any bundled module — the full workspace is available

def main() -> int:
    setup_logging()
    # Your custom logic here
    return 0

if __name__ == "__main__":
    sys.exit(main())
PYEOF

tar -cf /tmp/layer.tar -C /tmp/layer .
PYTHON=/app/critic.runfiles/_main/props/agents/critic/_critic.venv/bin/python3
crane append -b $REGISTRY/critic:latest -f /tmp/layer.tar -o /tmp/image.tar --insecure
crane mutate --local /tmp/image.tar --cmd "$PYTHON" --cmd "/custom_main.py" -o /tmp/image-final.tar
DIGEST=$(crane push /tmp/image-final.tar $REGISTRY/critic --insecure)
```

${"##"} Key Paths

| Path | Purpose |
|------|---------|
| `/workspace/` | Working directory, writable. Snapshots fetched here. |
| `/app/critic.runfiles/_main/` | Bazel workspace root — all Python source code |
| `/app/critic.runfiles/_main/props/agents/critic/prompt.md.mako` | Default system prompt template |
| `/app/critic.runfiles/_main/props/agents/critic/main.py` | Agent entrypoint |
| `/app/critic.runfiles/_main/props/agents/critic/_critic.venv/bin/python3` | Hermetic Python interpreter |

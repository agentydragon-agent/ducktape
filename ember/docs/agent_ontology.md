# Ember ontology

The deployed pilot is an event loop that repeatedly samples a large language
model and executes the tool calls it returns.

- **Ember** – the persona embodied by the LLM. Ember is the conversational
  agent whose reasoning traces we collect and whose tool calls drive the system.
- **emberd** – the lightweight Python runner that hosts the loop. emberd boots
  inside a container, wires up secrets/configuration, polls Matrix, and brokers
  tool execution. The process lives under `/opt/emberd`.
- **LLM core** – the OpenAI Responses API model (default `gpt-5`). Every cycle,
  emberd sends the current context to the LLM, receives reasoning + tool calls,
  and acts on them. The LLM itself has no direct I/O; everything must flow
  through tools.
- **Pilot state** – persisted under `PILOT_STATE_DIR` (typically
  `/var/lib/ember`). Stores conversation history metadata and encrypted reasoning
  traces; room membership is sourced live from the homeserver on startup.
- **Workspace** – `${EMBER_WORKSPACE_DIR:-/var/lib/ember/workspace}` is a
  persistent scratch area mounted from the same PVC. Ember drops temporary
  scripts, notes, or multi-step artifacts there between Matrix turns.
- **Secrets surface** – `/var/run/ember/secrets/`, where Kubernetes projects the
  Matrix, Gitea, and OpenAI credentials. emberd monitors this directory so tokens can
  rotate without pod restarts.
- **Matrix runtime** – the runtime bridges Matrix rooms into the tool loop. The
  LLM only sees messages that emberd forwards and must reply via shell tools.

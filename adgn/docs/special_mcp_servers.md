Special MCP Servers (container-owned)

Summary
- Introduce a first-class way to declare “special” in-proc servers in presets, owned by the agent container rather than the generic transport path. Examples: resources, approval_policy, seatbelt_exec.

Motivation
- Avoid double-initialization hacks and ad-hoc filtering for seatbelt_exec.
- Keep wiring/persistence for container-integrated servers centralized and explicit.
- Allow small, declarative options without exposing low-level transport details to presets.

Proposal: SpecialSpec transport
- In presets, add a special transport entry listing well-known servers and options.
- The container interprets these and attaches matching in-proc servers directly.
- Normal transports continue to work unchanged for non-special servers.

Preset shape (sketch)
- specs:
  - special:
      - name: approval_policy
        initial_policy: |
          # policy.py text (optional)
      - name: seatbelt_exec
        enable: true              # default: true
        initial_templates: {}     # map name -> SBPLPolicy JSON
        template_resource: true   # default: true (expose sbpl-template-json:// URIs)
      - name: resources
        enable: true              # default: true
  - docker:
      transport: stdio
      command: docker-mcp

Backwards compatibility
- If presets include seatbelt_exec via normal transport, the container ignores it when a special seatbelt entry is present.
- If no special block is present, the container preserves current behavior (filters and attaches a wired seatbelt server).

Container responsibilities
- Parse special entries at start and reconfigure.
- Attach in-proc servers with agent-specific state:
  - approval_policy: NotifyingFastMCP + persistence + proposal resources.
  - seatbelt_exec: NotifyingFastMCP + persistence + template resources.
  - resources: synthetic resources aggregator.
- Decide defaults (approval_policy + resources on by default; seatbelt_exec on by default).

Implementation plan
- specs.py: add SpecialSpec (type: special; entries list with name + options).
- presets loader: allow special under specs; validate known names.
- container: collect special specs; attach in-proc servers; exclude specials from generic transport wiring.
- header rendering: show final attached servers (special + normal).
- docs: AGENTS.md additions and example preset.

Open questions
- Do we want per-seatbelt options for resource visibility or template namespace scoping?
- Should approval_policy’s initial_policy be persisted immediately or only if none exists?

Non-goals (for now)
- General plugin system for arbitrary “specials”. Keep the list explicit and small.
- New UI hooks; rely on existing notifications/resources.

Future work
- Per-agent toggles for special servers via UI.
- Add a “special: ui” entry if we want to make the UI server optional/configurable.

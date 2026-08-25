# General repository-cleanup docket

This is a fresh, ranked cleanup audit of Ducktape. It covers stale production
code, complete experimental subsystems, broken feature surfaces, obsolete CI and
test machinery, compatibility shims, and misleading documentation.

The ranking is by **expected maintainer value**, not raw bytes:

1. recurring edit, review, test, dependency, and operational cost removed;
2. probability that the maintainer will accept the change, based on prior
   decisions;
3. whether the patch deletes a complete stage or ownership surface;
4. conservative whole-tree net reduction after replacement code and tests;
5. semantic, security, compatibility, and rollout risk.

Prior cleanup decisions strongly favor complete, behavior-preserving stage
removal and roughly 100+ whole-tree-line payoff. They reject micro-refactors,
complexity moved into new helpers, exact-config test churn disguised as
coverage, and changes that weaken durable compatibility or independent
security oracles.

Baseline inspected:
[`c50eb5f56`](https://github.com/agentydragon/ducktape/commit/c50eb5f56702160a0f14552577497b2ea2cbb8bf)
(2026-08-25). The audit included repository-wide references, BUILD/package
wiring, recent history, current open PRs, explicit cleanup tombstones, and
current Flux status where it materially changed the recommendation.

## How to review this docket

Terse decisions are enough:

```text
C01 yes after #4043 provenance closure
C02 preserve the two generic MCP research notes, delete the rest
C06 fix instead of delete
C10 no, keep the compatibility aliases
H02 bundle with the next cluster-validation cleanup
```

Approval of one item does not approve adjacent items. Implementation PRs should
be focused, independently reversible, and report the actual whole-tree diff.

## Ranked queue

The order reflects expected value, so a smaller live operational cleanup can
rank above a larger inert archive. Acceptance probabilities are estimates, not
claims of prior approval.

| Rank | ID  | P(accept) | Recommendation                                                    |        Conservative net payoff | Main risk                             |
| ---: | --- | --------: | ----------------------------------------------------------------- | -----------------------------: | ------------------------------------- |
|    1 | C02 |       93% | Retire `x/agent_server` while preserving generic research         |          **17,000–17,600 LOC** | deleting reusable lifecycle research  |
|    2 | C03 |       96% | Retire orphaned `x/inop` instruction optimizer                    |     **7,400–7,600 LOC** + deps | undocumented manual use               |
|    3 | C04 |       95% | Retire superseded `x/claude_linter_v2`                            |      **6,700–6,900 LOC** + dep | confusing it with the active hook     |
|    4 | C05 |       91% | Delete the orphaned release-decision stage                        |                **370–410 LOC** | undocumented manual invocation        |
|    5 | C06 |       89% | Delete or deliberately repair the broken Props GEPA surface       |      **1,000–1,200 LOC** + dep | abandoning intended optimization work |
|    6 | C07 |       92% | Retire `x/editor_agent`                                           |            **1,150–1,300 LOC** | overlooked personal workflow          |
|    7 | C01 |       70% | After #4043, retire the Squid spike and stale decision plan       | **2,500–2,800 LOC** + workload | active PR depends on its provenance   |
|    8 | C08 |       82% | Retire the answered, mid-WIP EOB-matching experiment              |            **1,450–1,550 LOC** | one-off personal utility still wanted |
|    9 | C09 |       84% | Remove three unwired generated-policy mirror tests                |                **330–360 LOC** | unknown manual test workflow          |
|   10 | C10 |       72% | Remove deprecated Debundle CLI aliases after a compatibility call |                **150–250 LOC** | external scripts using old commands   |
|   11 | C11 |       87% | Delete the superseded April cluster redesign archive              |            **about 1,005 LOC** | losing option/cost rationale          |
|   12 | C12 |       92% | Delete the obsolete February bootstrap analysis                   |                    **331 LOC** | losing historical bootstrap reasoning |
|   13 | C13 |       90% | Delete the stale SRE best-practices review                        |                    **448 LOC** | one remaining action not migrated     |
|   14 | C14 |       88% | Compress the superseded Haku instruction-ownership note           |                  **85–95 LOC** | dropping a still-open drift question  |
|   15 | C15 |       83% | Delete retired Kagent IaC snapshots, retain explanatory records   |              **about 916 LOC** | reducing exact revival archaeology    |

## Detailed recommendations

### C01 — retire the completed Squid egress spike and stale decision plan

**Delete or edit:**

- [`cluster/k8s/x/squid-egress-spike/`](../cluster/k8s/x/squid-egress-spike/)
- [`cluster/images/squid-ssl/`](../cluster/images/squid-ssl/)
- [`.github/workflows/squid-ssl-image.yml`](../.github/workflows/squid-ssl-image.yml)
- the `squid-ssl` Flux image repository and policy under
  [`cluster/k8s/flux-image-automation-forgejo/`](../cluster/k8s/flux-image-automation-forgejo/)
- the two Flux registrations in
  [`cluster/k8s/kustomization.yaml`](../cluster/k8s/kustomization.yaml)
- the `squid-egress-spike` registry-credential reflection entries
- most of
  [`cluster/docs/plans/agent_egress_proxy_options.md`](../cluster/docs/plans/agent_egress_proxy_options.md)

The spike calls itself throwaway infrastructure and says to delete it after its
questions are answered. The README records those answers. Git still registers
both Flux Kustomizations, and a direct Flux query on 2026-08-25 reported both
`Ready` at the audited `devel` revision. This is therefore not merely archived
source: the cluster still reconciles a completed experiment, image automation,
credentials, an ICAP stub, an echo origin, and a proxy workload. Re-check live
Flux state immediately before implementation rather than treating this dated
observation as permanent.

The 1,711-line plan still presents “one Squid per fence” as the current route,
while the shipped agent fences use Iron Proxy. Two open PRs also matter:

- old draft [#2798](https://github.com/agentydragon/ducktape/pull/2798)
  preserves the abandoned Squid migration;
- [#4043](https://github.com/agentydragon/ducktape/pull/4043) actively ports the
  measured Squid 7.6 ICAP wire behavior from this spike and links both the spike
  and plan as protocol provenance.

C01 is **blocked while #4043 remains unresolved**. Its acceptance probability
returns to roughly 97% after #4043 merges or closes and its required provenance
has a canonical owner. Deleting first would break an active review's historical
references.

**Safe replacement:** keep a concise decision record with the empirical facts
that remain useful: TLS bump viability, destination-scoped substitution,
`Basic` rewriting, the measured ICAP framing/preview behavior used by #4043,
cache treatment for authenticated responses, and why the shipped architecture
chose differently. Point operational readers to the current Iron Proxy manifests
and security documentation. Do not delete the security finding preserved in
[`cluster/docs/archive/2026_08_iron_proxy_consolidation.md`](../cluster/docs/archive/2026_08_iron_proxy_consolidation.md).
Update #4043's links or retained documentation owner, and explicitly decide the
status of #2798 rather than silently leaving it looking current.

**Validation:** resolve #4043's provenance first. Then remove the Flux
registrations in Git, validate cluster integration and image-policy references,
merge, and verify:

1. the two root Flux Kustomization objects are gone;
2. the app resources are pruned (`squid-egress-spike-app` has `prune: true`);
3. image-policy, registry-reflection, Secret, and build references are gone;
4. the namespace is empty and then explicitly deleted—the namespace
   Kustomization has `prune: false`, so Flux will not delete it automatically.

### C02 — retire `x/agent_server`

[`x/agent_server/`](../x/agent_server/) is 165 files and about 17,800 lines of
FastAPI, Svelte, persistence, container runtime, approval policy, MCP routing,
Matrix, and E2E machinery. No production runtime imports it and no external
Python BUILD target depends on it. The frontend is still intentionally wired
into shared build tooling: `MODULE.bazel`, the pnpm workspace/lockfile, ESLint,
pre-commit comments, Copilot instructions, and research documents all name it.
Those are deletion-scope updates, not evidence of a live runtime consumer.

More importantly, the current personal-agent survey explicitly records the
maintainer decision that `x/agent_server`, `agent_core`, and `x/editor_agent`
are **not** reuse candidates for future personal-agent work. The deployed
public coder and Haku Console now provide the relevant live architecture.
Keeping the executable stack causes dependency, lint, package-lock, and test
maintenance without preserving an accepted product direction.

**Safe replacement:** delete the executable stack, web package, Bazel npm-lock
input, pnpm workspace/lockfile section, ESLint source set, stale pre-commit and
Copilot guidance, and obsolete command examples. Before deletion, move only
genuinely reusable research—especially the async-cancellation analysis already
linked from `mcp_infra`—to its canonical owning documentation. Replace “do not
revive this stack” links with a dated decision or Git-history reference. Leave
frozen Props specimen snapshots unchanged unless their own specimen-pruning
rules independently authorize removal.

Do **not** include [`agent_core/`](../agent_core/) in this deletion. It still has
live consumers in `git_commit_ai`, `mcp_infra`, Props test fixtures, and other
code.

**Validation:** repository reference scan, pnpm lock regeneration, all affected
Python/TypeScript package checks, and a full BUILD/query check for surviving
references.

### C03 — retire orphaned `x/inop`

[`x/inop/`](../x/inop/) contains about 7,600 lines across 42 files. It defines an
instruction optimizer, runners, grading, plots, datasets, and Docker tests, but
it has no registered/package binary target and no caller outside its own
subtree. `engine/optimizer.py` does have a direct `main()` path, so an
undocumented manual `python …/optimizer.py` workflow remains possible and must
be checked. External references are limited to old inventory/documentation and
Ruff configuration. Its last changes are repository-wide mechanical maintenance
rather than feature work.

The subtree also appears to be the only code consumer of the heavyweight
`plotnine` and `claude-code-sdk` dependencies. Deleting the experiment therefore
removes more recurring dependency and CI cost than its source-line count alone
suggests.

**Safe replacement:** delete the subtree, Ruff entry, and stale references in
`docs/flat_tool_convertible.md` and `docs/gazelle_python_status.md`; remove
dependencies only after a fresh whole-tree import and BUILD scan. Git history is
the right owner for the abandoned implementation.

**Validation:** dependency lock regeneration, affected Python checks, and an
explicit proof that no binary, CI job, prompt, or developer script invokes the
optimizer.

### C04 — retire superseded `x/claude_linter_v2`

[`x/claude_linter_v2/`](../x/claude_linter_v2/) is about 6,900 lines with its own
CLI, policy language, session state, hooks, notifications, examples, and tests.
It has no repository caller or packaging entry. The active Claude hook is the
Rust implementation under
[`devinfra/claude/claude_hook/`](../devinfra/claude/claude_hook/), installed by
current Nix and Web setup paths.

The old linter still claims commands such as `cl2 check` and carries a large
`_factored_out.md` code dump, so search results can mislead maintainers toward a
non-shipped implementation. It is the only source import of `pytimeparse`,
although that dependency is still listed in root/Nix package metadata and needs
an explicit packaging audit before removal.

**Safe replacement:** delete the subtree and its Ruff/build references. Remove
`pytimeparse` from package metadata only if the packaging audit confirms no
surviving runtime needs it. Preserve the active Rust hook, Python statusline, and
current configuration profiles; this item is not permission to simplify those
contracts.

**Validation:** active Claude hook tests and container E2E, dependency lock
regeneration, and exact proof that no current settings/profile invokes `cl2` or
the old Python modules.

### C05 — delete the orphaned release-decision stage

**Targets:**

- [`devinfra/ci/check_release.py`](../devinfra/ci/check_release.py)
- [`devinfra/ci/diff_utils.py`](../devinfra/ci/diff_utils.py)
- [`devinfra/ci/github_actions.py`](../devinfra/ci/github_actions.py)
- their `check_release`, `diff_utils`, `github_actions`, and
  `check_release_bin` BUILD targets

Commit `93fc945c7` replaced the CI decision engine with native GitHub triggers.
The current release path is content-addressed in
[`.github/actions/release-artifact/action.yml`](../.github/actions/release-artifact/action.yml).
No workflow invokes `check_release.py`, `check_release_bin`, or
`compute_release_decision`; the remaining three modules reference only one
another. `diff_utils.py` even describes a `check_release_lib.py` that no longer
exists.

This is a complete obsolete control stage rather than a speculative refactor.
Delete its now-stale comment in `bazel_ci.sh` too, but leave the active
`bazel-diff` CI implementation alone.

**Validation:** repository reference scan, `devinfra/ci` tests, and inspection of
all release workflow calls. The only meaningful risk is an undocumented manual
`uv run devinfra/ci/check_release.py` workflow.

### C06 — delete or deliberately repair the broken Props GEPA surface

[`props/core/gepa/`](../props/core/gepa/) and
[`props/cli/cmd_gepa.py`](../props/cli/cmd_gepa.py) expose a `props gepa` command
and carry the repository's sole `gepa` dependency. The adapter deliberately
raises `NotImplementedError` from its constructor, evaluation paths, and
`optimize_with_gepa()` because `run_critic_legacy()` was removed. The warm-start
tests also state that the implementation is temporarily broken.

An advertised CLI that cannot enter its core path is worse than an absent
feature: it retains 1,100+ lines of adapters, database queries, logging,
checkpointing, tests, documentation, and a third-party dependency while giving
users a dead command.

**Recommended decision:** delete the CLI, adapter, warm-start path, GEPA
dependency, and README references unless there is a concrete owner and near-term
migration to definition-based `run_critic()`. Preserve the general prompt-
optimization research under the critic documentation.

**Validation:** all Props CLI and critic/grader tests, dependency lock
regeneration, and help-output/schema checks proving the dead command is gone.

### C07 — retire `x/editor_agent`

[`x/editor_agent/`](../x/editor_agent/) is about 1,300 lines of host/runtime code
and Docker-backed tests. It has no live external consumer, and the same current
personal-agent survey that rules out `x/agent_server` also rules out this stack
as a reuse candidate. The recent timeout commit was repository-wide test
maintenance, not renewed product work.

Delete it as a separate PR from C02 so failures and dependency cleanup remain
attributable. Do not delete `agent_core` or shared MCP display helpers merely
because this consumer disappears; evaluate any newly orphaned shared code in a
follow-up reference audit.

### C08 — retire the answered EOB-matching experiment

[`x/eob_matching/`](../x/eob_matching/) is about 1,550 lines. Its README says the
matching algorithm is mid-WIP and that the question which motivated it was
answered by PDF data extraction without needing the full matcher. There are no
external repository references.

This is a strong deletion candidate, but lower ranked because it is a personal,
one-off utility and the maintainer may still value rerunning its extraction
code. Confirm that workflow is finished; then delete the whole experiment rather
than completing an algorithm the recorded task no longer needs.

### C09 — remove three unwired generated-policy mirror tests

**Delete after confirming no manual workflow:**

- [`nix/home/tests/claude-code-permissions.nix`](../nix/home/tests/claude-code-permissions.nix)
- [`nix/home/tests/codex-execpolicy-rules.nix`](../nix/home/tests/codex-execpolicy-rules.nix)
- [`nix/home/tests/gemini-cli-integration.nix`](../nix/home/tests/gemini-cli-integration.nix)

These 362 lines are not wired into the flake, CI, BUILD, or documentation. They
mostly reconstruct exact generated permission/rule values from the same shared
source, so they are unwired change detectors rather than independent consumer
oracles.

Keep
[`nix/home/tests/codex-execpolicy-evaluation.nix`](../nix/home/tests/codex-execpolicy-evaluation.nix):
it invokes the real Codex CLI and is an independent external-consumer/security
test. If Claude or Gemini needs equivalent coverage, add one real parser/client
evaluation instead of preserving copied expected strings.

**Validation:** normal flake checks plus the surviving Codex evaluation check.

### C10 — remove deprecated Debundle CLI aliases

[`devinfra/js/debundle/cli/mod.rs`](../devinfra/js/debundle/cli/mod.rs) still
supports six `debundle peel …` aliases and the singular
`debundle module merge`. Current documentation and repository callers use the
top-level commands and `debundle modules merge`; no in-repository script uses
the deprecated forms.

The cleanup would remove alias structs/dispatch, deprecation output, parser
tests, and compatibility prose while keeping the current command implementations
unchanged.

**Why this ranks lower:** absence of repository callers is not proof that the
maintainer has no shell history or external scripts using a CLI. Make an
explicit compatibility decision first. If durable compatibility is preferred,
leave the aliases; a tiny LOC win does not justify surprising a real user.

## Documentation and archive cleanup

These are valid but rank below live-code and tooling deletions because Git already
contains their history and most have little recurring execution cost.

### C11 — delete `cluster/archive/2026_04_architecture_redesign/`

The four files total about 1,005 lines and have no external inbound references.
One still says “Draft / In Progress”; the others say the decisions are resolved.
Current architecture, storage, and SSO ownership lives in
[`cluster/docs/plan.md`](../cluster/docs/plan.md) and
[`cluster/docs/sso.md`](../cluster/docs/sso.md).

Before deletion, compare the old cost/options rationale with the current
architecture-decision section. Preserve a short ADR only for unique reasoning
that still changes future choices.

### C12 — delete `cluster/docs/archive/2026_02_bootstrap_analysis.md`

This 331-line, unreferenced analysis describes an obsolete Proxmox/Talos
nine-stage flow and old gaps. Current OVH/Kimsufi bootstrap ownership lives in
[`cluster/docs/bootstrap.md`](../cluster/docs/bootstrap.md) and
[`cluster/docs/bootstrap_dependencies.md`](../cluster/docs/bootstrap_dependencies.md).
Verify that any still-open gap was migrated, then delete the historical analysis.

### C13 — delete `cluster/archive/2026_05_sre_best_practices_review.md`

The unreferenced 448-line review retains obsolete Vault assumptions, completed
ingress work, and an old P0–P3 action list. Current owners include
[`cluster/docs/plan.md`](../cluster/docs/plan.md),
[`cluster/docs/sso.md`](../cluster/docs/sso.md), and operational
lessons/postmortems. Confirm every still-open action has a current owner before
deletion.

### C14 — compress `haku/archive/2026_08_instructions_ownership.md`

The 116-line note says it was superseded, but most of the old proposal remains
below the outcome and references removed paths. Keep a 20–30-line decision
record: the manual moved to `haku-state`, `agent_shared.yaml` remains protected
configuration, and self-drift remains unresolved. Canonical ownership is in
[`haku/base/README.md`](../haku/base/README.md) and
[`haku/docs/security.md`](../haku/docs/security.md).

### C15 — delete retired Kagent IaC snapshots, retain explanatory records

Delete `cluster/archive/2026_07_kagent/k8s/**` and
`cluster/archive/2026_07_kagent/terraform/provider_kagent.tf` (about 916 lines),
but retain the README and analytical/operational documents. The archive already
says these workloads, CRDs, namespace resources, and `devbot` were removed and
must not be restored directly. Rewrite links in the retained README and
operational documents to prose or the historical commit, then run a full
post-deletion link-closure check.

## Small, high-confidence follow-ups

These are too small or too storage-oriented to drive the cleanup roadmap. Bundle
them with related work or take them only when a maintainer explicitly wants a
housekeeping pass.

| ID  | P(accept) | Follow-up                                                                       |              Payoff |
| --- | --------: | ------------------------------------------------------------------------------- | ------------------: |
| H01 |       96% | Delete stale `mcp_infra/docs/mcp_tool_name_violations.md`                       |         **271 LOC** |
| H02 |       94% | Delete unused `cluster/validation:kustomize_build_all` binary/target            |    **about 78 LOC** |
| H03 |       97% | Delete dated `cluster/archive/2026_05_raw_pvc_inventory.md`                     |          **45 LOC** |
| H04 |       95% | Delete the remainder of `x/claude_commands_old/`                                |   **about 919 LOC** |
| H05 |       86% | Consolidate the two overlapping useless-comments/documentation scan prompts     | **350–500 net LOC** |
| H06 |       80% | Delete/compress unreferenced `archive/2026_04_sops_nix_container_activation.md` |   **up to 316 LOC** |

H04 remains low priority despite its size: the files are explicitly archived and
cost little recurring programmer time. H05 requires preserving the genuinely
distinct detection examples rather than blindly choosing the shorter prompt.

## Explicitly parked, excluded, or preserved

Do not turn the following into cleanup PRs from this docket without a changed
precondition:

- **Haku launch-routine capability:** eventual 450–650-line duplicate privilege
  path deletion, but only after haku-ui submits `haku_routine.launch_routine`
  through the standard approval queue. It currently overlaps the separate Web /
  Codex feature track and PR #4584.
- **Haku runner credential/setup compatibility and duplicate setup narration:**
  real future cleanups, but they require rollout proof or reader migration and
  overlap current runtime work.
- **Haku session lifecycle D03:** independently reviewed cleanup remains parked
  at [draft PR #10](https://github.com/agentydragon-agent/ducktape/pull/10)
  because its ancestry includes #4584. Do not manage #4584 from cleanup work.
- **`agent_core`:** explicitly ruled out for new personal-agent design, but still
  a live dependency of `git_commit_ai`, `mcp_infra`, Props test helpers, and other
  code. It is not presently a deletion candidate.
- **Compositor public pinning:** likely simplifies after C02/C03/C07 remove nearly
  every application `pinned=True` caller. Re-audit then; do not refactor around
  consumers already proposed for deletion.
- **Claude/Codex transcript projection sharing:** overlaps active Codex/runtime
  work; revisit only after the feature stabilizes.
- **LiteLLM exact-config mirror tests:** already owned by
  [open PR #4472](https://github.com/agentydragon/ducktape/pull/4472).
- **Rejected Haku manifest and Augur reducer prototypes:** prior versions removed
  no worthwhile stage or weakened independent security/performance oracles.
- **Raw inference `.eval` archives:** explicitly deferred.
- **Props specimen inputs:** dated captured trees are frozen unless a reference
  audit and specimen integration test prove an unrelated copied subtree can be
  pruned.
- **`haku/console/plans/conversation_layers.md`:** still referenced and tracks
  remaining work; it is not stale documentation.
- **Migrations, schema compatibility tests, negative authorization tests, exact
  approval/audit semantics, renderer snapshots, postmortems, security records,
  and operational lessons:** preserve unless the replacement has an independent
  semantic owner.
- **Kagent explanatory retirement docs, the OpenClaw namespace-retirement record,
  Iron Proxy hardening record, and Haku multi-agent trust findings:** preserve
  their unique operational/security evidence even when exact retired manifests
  are deleted.

## Implementation standard

For every accepted item:

1. rebase onto current `devel` and re-run the inbound-reference audit;
2. preserve user-visible behavior and every independent semantic/security oracle;
3. report raw deletions, replacement additions, and **whole-tree net** payoff;
4. remove BUILD/package/lock/config/documentation references in the same PR;
5. run the owning unit/integration/e2e checks and changed-file pre-commit hooks;
6. obtain independent semantic review before opening or marking a PR ready;
7. keep unrelated candidates in separate PRs unless one deletion genuinely
   orphans the next.

This docket is a decision aid and historical scratchpad. It is intentionally a
draft and is not itself a merge deliverable.

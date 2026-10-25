# Tests that read Flux manifest trees

Inventory for moving Flux delivery manifests off `devel`. The intended test model is per test: test cdk8s-owned behavior from its source constructs or a focused in-memory graph, and test policy or consumer logic with fixtures. CI does not need to feed one rendered bundle to every test. Only checks that truly validate the complete Flux graph need that graph, and should live with the graph owner. This PR changes documentation only. Classes are assigned by the main assertion in each Bazel test target; a target can contain more than one kind of assertion.

This is a snapshot of `origin/devel` at `138897a8`; test paths and targets are recorded as they exist at that baseline.

| Class | Meaning                                                                         |
| ----- | ------------------------------------------------------------------------------- |
| a     | Restates a declaration or detects arbitrary changes; delete candidate.          |
| b     | Checks a durable relation between objects or files.                             |
| c     | Validates rendered output against a schema or policy, or builds the Flux graph. |
| d     | Tests generator or model behavior that can run on a cdk8s model in memory.      |
| e     | Other; the row explains the consumer-specific reason.                           |

## Inventory

<!-- prettier-ignore -->
| Test path and Bazel target | YAML read and assertion | Class | Home after the move | Real regression evidence |
| --- | --- | --- | --- | --- |
| `cluster/cdk8s/test_generate_manifests.py`; `//cluster/cdk8s:test_generate_manifests` | Runs the generator, then reads all generated YAML and compares every generated file with its committed counterpart under `cluster/generated/`, generated `*.k8s.yaml` under the hand-written/parked roots, and the closed generated root. The generator also loads source inputs such as Authentik blueprints. Asserts committed twins and byte parity, no stale files in the closed root, plus generated-object invariants (Piraeus, Flux dependencies, policy bindings, and others). | d | Keep durable generation invariants as focused tests over in-memory model output. Remove committed-file byte parity and the closed-output-tree check when delivery YAML leaves devel; those compare output with a second copy. No shared render input. | No specific incident was found in source comments. The cdk8s guidance names this as the sole generated-output pin. |
| `cluster/cdk8s/haku_ci/test_runner.py`; `//cluster/cdk8s/haku_ci:test_runner` | Reads `cluster/k8s/haku/forgejo-tea/haku-forgejo-tea.sops.yaml` by runfile. Asserts the Secret name and key match `runner.py` constants and its reflector annotations name the KEDA namespace. | b | Synthesize the TriggerAuthentication from its constructor and compare its Secret reference with the Secret source contract. Keep the source-Secret check with its owner if that authored SOPS input remains separate; do not test through delivery output. | No incident or issue reference found. |
| `cluster/debug/litellm_probe/test_probe_models.py`; `//cluster/debug/litellm_probe:test_probe_models` | Indirectly reads `cluster/k8s/litellm/app/app.k8s.yaml`: the test depends on `:probe_models`, whose `data` includes `:proxy_manifest`; `_load_model_probes(None)` reads the `config` ConfigMap. Asserts parsed models are nonempty and unique and include Ollama and embedding cases. | e — exercises a diagnostic consumer on its real input. | Keep parser behavior tests on synthetic LiteLLM config; delete the committed-manifest roster assertion or feed it explicit config. The diagnostic tool may take a specific source config, but tests need no cluster render. | No incident or issue reference found. |
| `cluster/skills/grafana/test_verify_dashboard.py`; `//cluster/skills/grafana:test_verify_dashboard` | Reads `cluster/generated/monitoring/grafana-instance/grafana-instance.k8s.yaml`. One test uses the generated GrafanaDashboard to resolve `DS_LOKI` to the operator datasource name and checks a query uses that datasource; the other cases use synthetic dashboards. | e — tests an external dashboard verifier against the resource it consumes. | Synthesize just the GrafanaDashboard input from its source model, or use a focused dashboard fixture, then exercise the verifier. Keep synthetic verifier cases; no monitoring bundle. | No incident or issue reference found. |
| `agentplane/system_tests/test_ollama_catalog.py`; `//agentplane/system_tests:test_ollama_catalog` | Reads `cluster/k8s/agentplane-staging/agentplane-staging.k8s.yaml` through the `agentplane_staging_manifest` data target. The committed-config case runs `ollama_cases` over `app-config` and asserts the smoke case list is nonempty and unique; the remaining cases use synthetic manifests. | a | Delete the committed-config assertion; synthetic cases already exercise selection and failure behavior. Do not pin the production model roster in a manifest test. | No incident or issue reference found. |
| `agentplane/system_tests/test_ollama_routes.py`; `//agentplane/system_tests:test_ollama_routes` | Reads the same Agentplane staging manifest through `agentplane_staging_manifest` to select routes. The manual live smoke checks each route is offered by the deployed API and can complete a sandbox tool call. | e — a live deployed-system smoke test. | Source candidate routes from the deployed models API at runtime, then exercise each live case. It needs neither a manifest file nor a render artifact. | No specific regression was found; this is explicitly a live smoke. |
| `cluster/validation/test_cluster_integration.py`; `//cluster/validation:test_cluster_integration` | Through `conftest.py` and `parse_cluster`, reads the full `cluster/k8s/` and `cluster/generated/` trees plus package-boundary manifest filegroups. It also opens the central Flux Kustomizations, Agentplane staging manifest, Loki proxy manifest, and binding-delegation manifests. Checks whole-graph build coverage, dependencies, health checks, credential ownership, image/namespace relations, grant/delegation wiring, Flux rewrite constraints, SOPS blocks, and policy invariants. | b (mixed with c) | Split cdk8s-owned relations and policy checks into focused in-memory model tests. Keep only checks that need the complete Flux graph with that graph's owner and CI; code-level checks should not consume a shared render. | The image-automation assertion documents an earlier raw-YAML-walking gap, but no issue or introducing commit is available here. Cluster guidance separately points to `test_crd_layering` for CRD layering; that test uses synthetic data and is not a reader in this inventory. |
| `cluster/validation/test_mailbox_smtp_ingress.py`; `//cluster/validation:test_mailbox_smtp_ingress` | Reads `cluster/k8s/haku/mailbox/mailbox.k8s.yaml` and adjacent `nginx.conf`; the target has broad manifest data deps. Asserts the SMTP Service port is the proxy destination and PROXY protocol is enabled. | b | Test the Service-to-proxy destination against the mailbox model and source config. If nginx.conf is the source input, read that input directly; synth only the mailbox chart, not its generated YAML. | No incident or issue reference found. |
| `cluster/validation/test_public_coder_clickhouse_reader_contract.py`; `//cluster/validation:test_public_coder_clickhouse_reader_contract` | Reads the hand-written `cluster/k8s/clickhouse/cluster/public-coder-credentials.sops.yaml` via `k8s_dir`. Asserts Secret name, namespace, password key, and that reflector annotations do not mirror it, against `clickhouse.client` constants. | b | Compare the reader's name and key against a synthesized reader model and a small source-Secret contract. If the SOPS Secret remains source-owned, keep only that source check beside it; do not load a delivered copy. | No incident or issue reference found. |
| `cluster/validation/test_authentik_blueprint_contracts.py`; `//cluster/validation:test_authentik_blueprint_contracts` | Through `k8s_dir`, reads `cluster/k8s/authentik/app/blueprints/*.yaml` (source blueprints embedded by cdk8s, not standalone rendered manifests). Asserts each present proxy provider is assigned to an outpost and outpost provider references resolve without targeting retired entries. | b | Move the contract checker beside the Authentik blueprint inputs; they are source data embedded by cdk8s, not rendered Flux output. Read only those blueprints and check their references. | [#2390](https://github.com/agentydragon/ducktape/pull/2390) says this wiring gap had already caused redirect-URI failures for two providers. |
| `cluster/validation/test_flux_build.py`; `//cluster/validation:test_flux_build` | Uses the root `cluster/k8s/kustomization.yaml` runfile and all referenced hand-written and generated trees, including three Bazel subpackage manifest groups. Asserts `flux build` renders the whole tree successfully. | c | Move this whole-graph build check with the Flux source graph and run it in that graph owner's pipeline. It necessarily reads the source graph; it is not a cdk8s model test or a consumer of a rendered artifact. | No specific incident or issue reference found. |
| `cluster/validation/test_generator_namespace.py`; `//cluster/validation:test_generator_namespace` | Uses the root Kustomization as a runfiles anchor, then scans `kustomization.yaml` files across manifest roots and the central Flux Kustomizations. Checks active direct Flux targets using `configMapGenerator`/`secretGenerator` get a namespace from the local Kustomization or `targetNamespace`; it skips generated-root directories and replacement-only sources. | b | Keep a focused source-level check beside hand-written Kustomizations that use generators; read those declarations only. Cdk8s-owned Kustomization generation belongs in constructor or model tests. | [#3567](https://github.com/agentydragon/ducktape/pull/3567) fixes the documented three-hour outage: a missing namespace left the public-coder instance serving 502s from a stale Deployment. |
| `cluster/validation/kyverno/test_default_vpa_requests_only.py`; `//cluster/validation/kyverno:test_default_vpa_requests_only` | Reads the generated `default-vpa-requests-only` ClusterPolicy through shared `kyverno.paths.policy()` and scans YAML across both manifest roots. Exercises policy behavior on fixture Namespaces and checks declared auto-mode namespace policies specify `controlledValues`. | c | Synthesize this policy from its constructor and run Kyverno on fixtures. Move the fleet-wide namespace annotation rule to in-memory cdk8s validation; keep any authored YAML checks with their source owners. | [#3880](https://github.com/agentydragon/ducktape/pull/3880) records the 2026-08-09 LiteLLM incident: both replicas got a 150m CPU limit and crash-looped for six hours. |
| `cluster/validation/kyverno/test_default_service_links.py`; `//cluster/validation/kyverno:test_default_service_links` | Shared `kyverno.paths.policy()` reads the generated `default-disable-service-links` policy; applies it to a synthetic Pod fixture. Asserts `enableServiceLinks` becomes false. | c | Synthesize the policy from its cdk8s constructor, then keep the real Kyverno CLI behavior test on its Pod fixture. It needs no generated policy file or whole graph. | No incident or issue reference found. |
| `cluster/validation/kyverno/test_restrict_agent_gateway_routes.py`; `//cluster/validation/kyverno:test_restrict_agent_gateway_routes` | Shared policy helper reads the generated `restrict-agent-gateway-routes` policy; applies it to fixture HTTPRoutes/TLSRoutes. Asserts agent-namespace routes fail and a service-namespace route passes. | c | Synthesize the policy from its cdk8s constructor, then keep the real Kyverno CLI behavior tests on route fixtures. They need no generated policy file or whole graph. | No incident or issue reference found. |
| `cluster/validation/kyverno/test_require_secret_store_conditions.py`; `//cluster/validation/kyverno:test_require_secret_store_conditions` | Shared policy helper reads the generated `require-secret-store-conditions` policy; applies it to fixture ClusterSecretStores. Asserts missing, empty, and unconstrained conditions fail while explicit conditions pass. | c | Synthesize the policy from its cdk8s constructor, then keep the real Kyverno CLI behavior tests on ClusterSecretStore fixtures. They need no generated policy file or whole graph. | No incident or issue reference found. |
| `cluster/validation/kyverno/test_proxy_injection.py`; `//cluster/validation/kyverno:test_proxy_injection` | Shared policy helper reads the generated `inject-haku-egress-proxy` policy; applies it twice to a probe Pod and to a self-wired Pod fixture. Asserts reinvocation is idempotent and existing wiring is left alone. | c | Synthesize the injection policy from its cdk8s constructor, then keep the real Kyverno CLI reinvocation tests on Pod fixtures. They need no generated policy file or whole graph. | [#3838](https://github.com/agentydragon/ducktape/pull/3838) documents the 2026-08-05 Haku UI outage: reinvocation duplicated volume mounts, leaving one replica unable to create its Pod. |

The class counts use one primary class per row; the whole-graph integration target
is marked mixed because it also validates rendered policy/schema properties.

| Primary class                           | Test targets |
| --------------------------------------- | -----------: |
| a — change detector / restatement       |            1 |
| b — artifact relations                  |            6 |
| c — rendered schema / policy validation |            6 |
| d — generator/model behavior            |            1 |
| e — other                               |            3 |
| **Total**                               |       **17** |

The Agentplane catalog target is the one primary change-detector row: its production-config case checks the current roster, while the helper's durable selection behavior already has synthetic cases. The cdk8s generator target is primarily model behavior but also contains committed-output parity and a closed-tree check. Those are output-copy checks; once delivery YAML leaves devel, retain the durable model invariants and remove that parity dependency. No test needs a universal CI-render input.

## Searches and completeness

The first search is deliberately broad: path strings, fixtures, and comments are
candidates, not proof that a test opens the checked-in tree.

```sh
rg -l 'cluster/(k8s|generated)|manifest_files\(|k8s_dir|generated_dir|repo_root' \
  --glob 'test_*.py' --glob '*_test.py' --glob '*_test.go' --glob '*_test.ts' --glob '*.bats' . | sort
```

I then traced Bazel `data` edges and filegroups, including package-boundary globs
and helper-owned data:

```sh
rg -n 'cluster/(k8s|generated)|generated_manifests|parked_generated_manifests|cluster_all_files|flux_bootstrap_files|flux_system_files|kyverno_policy_files|agentplane_staging_manifest|authentik_blueprint_contract_files|proxy_manifest' \
  --glob 'BUILD*' --glob '*.bzl' .
```

This surfaced whole-tree readers in `test_cluster_integration`, `test_flux_build`,
`test_generator_namespace`, `test_default_vpa_requests_only`, and
`test_generate_manifests`; focused filegroups for the Agentplane, Authentik,
ClickHouse, and haku-ci tests; the shared Kyverno policy loader; and the
transitive `cluster/debug/litellm_probe:test_probe_models` reader (`:probe_models`
data → `:proxy_manifest` → `app.k8s.yaml`). I followed each helper to its open/read
call and matched the source to its test target.

The source/helper cross-check was:

```sh
rg -n '(_main/|ducktape/)?cluster/(k8s|generated)/|manifest_files\(|GENERATED_ROOT|generated_dir|k8s_dir|_POLICIES|_load_model_probes' \
  --glob 'test_*.py' --glob '*_test.py' --glob '*_test.go' --glob '*_test.ts' --glob '*.bats' .
rg -n 'get_required_path|manifest_files|_POLICIES|_load_model_probes|read_text' \
  cluster/validation cluster/cdk8s/test_generate_manifests.py cluster/cdk8s/haku_ci \
  cluster/skills/grafana cluster/debug/litellm_probe agentplane/system_tests
```

I also searched non-Python test languages:

```sh
rg -n 'cluster/(k8s|generated)' \
  --glob '*.go' --glob '*.ts' --glob '*.tsx' --glob '*.sh' --glob '*.bats' .
```

No Go, TypeScript, or shell test that reads either tree was found. The broad
candidate scan also finds synthetic tests whose paths happen to contain
`cluster/k8s` (for example `test_dependencies`, `test_crd_layering`,
`test_health_checks`, `test_sops_decryption`, and `test_render_diff`); those build
temporary objects/trees and do not read the checked-in manifests. It finds
comments in `test_egress` and `test_egress_fences`, and a registry-test docstring;
none opens a manifest. The container E2E secret path is staged from its
`testdata/e2e_secrets` fixture, not read from `cluster/k8s`.

## Follow-up trim order

No trim depends on a shared rendered artifact. Keep each PR focused on the owning
test or source package:

1. `cluster/validation/kyverno/`: synthesize one policy at a time from its cdk8s
   constructor, then run the real Kyverno CLI on the existing behavior fixtures.
   Move the namespace-wide VPA annotation rule into an in-memory cdk8s model rule.
2. `cluster/skills/grafana/`: source the one GrafanaDashboard from its cdk8s model
   or a focused fixture and keep verifier behavior local.
3. `cluster/debug/litellm_probe/`: keep parser behavior on explicit synthetic
   config; remove the production-manifest roster assertion from the test.
4. `agentplane/system_tests/`: discover the Ollama smoke cases from the deployed
   models API; keep catalog-selection logic covered with synthetic inputs.
5. `cluster/cdk8s/haku_ci/`: synthesize the TriggerAuthentication and compare it
   with the source Secret contract.
6. `cluster/cdk8s/authentik/`: keep blueprint reference checks beside the source
   blueprint data that cdk8s embeds.
7. `cluster/validation/` mailbox and ClickHouse checks: move generated-object
   assertions to the specific cdk8s model; keep any remaining authored-source
   contract checks beside their source.
8. `cluster/cdk8s/` generator tests: retain durable rules over in-memory objects
   and remove committed deployment-output parity when those outputs leave devel.
9. `cluster/validation/` namespace-generator check: keep it on the hand-written
   Kustomization source declarations; test cdk8s-owned generation at the model.
10. `cluster/validation/` Flux build and integration checks: move the complete-graph
    checks with the Flux source graph and run them where that graph is owned.

The only unresolved ownership question is which authored inputs under
`cluster/k8s/` (including SOPS Secrets, Kustomizations, and Authentik blueprints)
remain as source data in devel versus move with Flux delivery. That affects where
those source-contract checks run. It does not block the focused cdk8s model trims.
The linked incident PRs are the available evidence; the checkout's Git history is
shallow, so no further commit attribution was available.

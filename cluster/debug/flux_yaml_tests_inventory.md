# Tests that read Flux manifest trees

Inventory for the planned move of Flux-rendered YAML out of `devel`. No code or
test changes are made here. Classes are assigned by the main assertion in each
Bazel test target; a target can contain more than one kind of assertion.

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
| `cluster/cdk8s/test_generate_manifests.py`; `//cluster/cdk8s:test_generate_manifests` | Runs the generator, then reads all generated YAML and compares every generated file with its committed counterpart under `cluster/generated/`, generated `*.k8s.yaml` under the hand-written/parked roots, and the closed generated root. The generator also loads source inputs such as Authentik blueprints. Asserts committed twins and byte parity, no stale files in the closed root, plus generated-object invariants (Piraeus, Flux dependencies, policy bindings, and others). | d | Move model invariants to cdk8s synth tests. Keep one output parity check in CI against the delivered render; the in-memory assertions do not need committed YAML. | No specific incident was found in source comments. The cdk8s guidance names this as the sole generated-output pin. |
| `cluster/cdk8s/haku_ci/test_runner.py`; `//cluster/cdk8s/haku_ci:test_runner` | Reads `cluster/k8s/haku/forgejo-tea/haku-forgejo-tea.sops.yaml` by runfile. Asserts the Secret name and key match `runner.py` constants and its reflector annotations name the KEDA namespace. | b | Move onto the cdk8s model: synth the TriggerAuthentication and check its Secret reference against this input Secret. | No incident or issue reference found. |
| `cluster/debug/litellm_probe/test_probe_models.py`; `//cluster/debug/litellm_probe:test_probe_models` | Indirectly reads `cluster/k8s/litellm/app/app.k8s.yaml`: the test depends on `:probe_models`, whose `data` includes `:proxy_manifest`; `_load_model_probes(None)` reads the `config` ConfigMap. Asserts parsed models are nonempty and unique and include Ollama and embedding cases. | e — exercises a diagnostic consumer on its real input. | Run the consumer check against the CI-rendered artifact; keep its separate raw-config parser test synthetic. | No incident or issue reference found. |
| `cluster/skills/grafana/test_verify_dashboard.py`; `//cluster/skills/grafana:test_verify_dashboard` | Reads `cluster/generated/monitoring/grafana-instance/grafana-instance.k8s.yaml`. One test uses the generated GrafanaDashboard to resolve `DS_LOKI` to the operator datasource name and checks a query uses that datasource; the other cases use synthetic dashboards. | e — tests an external dashboard verifier against the resource it consumes. | Run the generated-resource case against the CI-rendered artifact; retain the synthetic verifier tests as unit tests. | No incident or issue reference found. |
| `agentplane/system_tests/test_ollama_catalog.py`; `//agentplane/system_tests:test_ollama_catalog` | Reads `cluster/k8s/agentplane-staging/agentplane-staging.k8s.yaml` through the `agentplane_staging_manifest` data target. The committed-config case runs `ollama_cases` over `app-config` and asserts the smoke case list is nonempty and unique; the remaining cases use synthetic manifests. | d | Move the committed-config case onto the cdk8s model or rendered artifact. The helper’s behavior is already exercised with synthetic input. | No incident or issue reference found. |
| `agentplane/system_tests/test_ollama_routes.py`; `//agentplane/system_tests:test_ollama_routes` | Reads the same Agentplane staging manifest through `agentplane_staging_manifest` to select routes. The manual live smoke checks each route is offered by the deployed API and can complete a sandbox tool call. | e — a live deployed-system smoke test. | Keep as a manual live smoke; supply its case list from the rendered artifact or deployed model API, not a checked-in manifest. | No specific regression was found; this is explicitly a live smoke. |
| `cluster/validation/test_cluster_integration.py`; `//cluster/validation:test_cluster_integration` | Through `conftest.py` and `parse_cluster`, reads the full `cluster/k8s/` and `cluster/generated/` trees plus package-boundary manifest filegroups. It also opens the central Flux Kustomizations, Agentplane staging manifest, Loki proxy manifest, and binding-delegation manifests. Checks whole-graph build coverage, dependencies, health checks, credential ownership, image/namespace relations, grant/delegation wiring, Flux rewrite constraints, SOPS blocks, and policy invariants. | b (mixed with c) | Run against the assembled rendered artifact in CI, preserving the Flux graph and source metadata required by the checks. | The image-automation assertion documents an earlier raw-YAML-walking gap, but no issue or introducing commit is available here. Cluster guidance separately points to `test_crd_layering` for CRD layering; that test uses synthetic data and is not a reader in this inventory. |
| `cluster/validation/test_mailbox_smtp_ingress.py`; `//cluster/validation:test_mailbox_smtp_ingress` | Reads `cluster/k8s/haku/mailbox/mailbox.k8s.yaml` and adjacent `nginx.conf`; the target has broad manifest data deps. Asserts the SMTP Service port is the proxy destination and PROXY protocol is enabled. | b | Run against the rendered artifact in CI; it relates the emitted Service to the proxy configuration. | No incident or issue reference found. |
| `cluster/validation/test_public_coder_clickhouse_reader_contract.py`; `//cluster/validation:test_public_coder_clickhouse_reader_contract` | Reads the hand-written `cluster/k8s/clickhouse/cluster/public-coder-credentials.sops.yaml` via `k8s_dir`. Asserts Secret name, namespace, password key, and that reflector annotations do not mirror it, against `clickhouse.client` constants. | b | Move the relation check onto the cdk8s model or run it against the rendered Secret and reader in CI. | No incident or issue reference found. |
| `cluster/validation/test_authentik_blueprint_contracts.py`; `//cluster/validation:test_authentik_blueprint_contracts` | Through `k8s_dir`, reads `cluster/k8s/authentik/app/blueprints/*.yaml` (source blueprints embedded by cdk8s, not standalone rendered manifests). Asserts each present proxy provider is assigned to an outpost and outpost provider references resolve without targeting retired entries. | b | Move beside the Authentik cdk8s input/model and validate the blueprint data before synth. | [#2390](https://github.com/agentydragon/ducktape/pull/2390) says this wiring gap had already caused redirect-URI failures for two providers. |
| `cluster/validation/test_flux_build.py`; `//cluster/validation:test_flux_build` | Uses the root `cluster/k8s/kustomization.yaml` runfile and all referenced hand-written and generated trees, including three Bazel subpackage manifest groups. Asserts `flux build` renders the whole tree successfully. | c | Run against the rendered artifact in CI. | No specific incident or issue reference found. |
| `cluster/validation/test_generator_namespace.py`; `//cluster/validation:test_generator_namespace` | Uses the root Kustomization as a runfiles anchor, then scans `kustomization.yaml` files across manifest roots and the central Flux Kustomizations. Checks active direct Flux targets using `configMapGenerator`/`secretGenerator` get a namespace from the local Kustomization or `targetNamespace`; it skips generated-root directories and replacement-only sources. | b | Run on the rendered artifact in CI, or move the generator-owned half into cdk8s synth validation. | [#3567](https://github.com/agentydragon/ducktape/pull/3567) fixes the documented three-hour outage: a missing namespace left the public-coder instance serving 502s from a stale Deployment. |
| `cluster/validation/kyverno/test_default_vpa_requests_only.py`; `//cluster/validation/kyverno:test_default_vpa_requests_only` | Reads the generated `default-vpa-requests-only` ClusterPolicy through shared `kyverno.paths.policy()` and scans YAML across both manifest roots. Exercises policy behavior on fixture Namespaces and checks declared auto-mode namespace policies specify `controlledValues`. | c | Run against the CI-rendered policy and resource artifact; keep fixture cases alongside the policy test. | [#3880](https://github.com/agentydragon/ducktape/pull/3880) records the 2026-08-09 LiteLLM incident: both replicas got a 150m CPU limit and crash-looped for six hours. |
| `cluster/validation/kyverno/test_default_service_links.py`; `//cluster/validation/kyverno:test_default_service_links` | Shared `kyverno.paths.policy()` reads the generated `default-disable-service-links` policy; applies it to a synthetic Pod fixture. Asserts `enableServiceLinks` becomes false. | c | Run against the CI-rendered policy artifact. | No incident or issue reference found. |
| `cluster/validation/kyverno/test_restrict_agent_gateway_routes.py`; `//cluster/validation/kyverno:test_restrict_agent_gateway_routes` | Shared policy helper reads the generated `restrict-agent-gateway-routes` policy; applies it to fixture HTTPRoutes/TLSRoutes. Asserts agent-namespace routes fail and a service-namespace route passes. | c | Run against the CI-rendered policy artifact. | No incident or issue reference found. |
| `cluster/validation/kyverno/test_require_secret_store_conditions.py`; `//cluster/validation/kyverno:test_require_secret_store_conditions` | Shared policy helper reads the generated `require-secret-store-conditions` policy; applies it to fixture ClusterSecretStores. Asserts missing, empty, and unconstrained conditions fail while explicit conditions pass. | c | Run against the CI-rendered policy artifact. | No incident or issue reference found. |
| `cluster/validation/kyverno/test_proxy_injection.py`; `//cluster/validation/kyverno:test_proxy_injection` | Shared policy helper reads the generated `inject-haku-egress-proxy` policy; applies it twice to a probe Pod and to a self-wired Pod fixture. Asserts reinvocation is idempotent and existing wiring is left alone. | c | Run against the CI-rendered policy artifact. | [#3838](https://github.com/agentydragon/ducktape/pull/3838) documents the 2026-08-05 Haku UI outage: reinvocation duplicated volume mounts, leaving one replica unable to create its Pod. |

The class counts use one primary class per row; the whole-graph integration target
is marked mixed because it also validates rendered policy/schema properties.

| Primary class                           | Test targets |
| --------------------------------------- | -----------: |
| a — change detector / restatement       |            0 |
| b — artifact relations                  |            6 |
| c — rendered schema / policy validation |            6 |
| d — generator/model behavior            |            2 |
| e — other                               |            3 |
| **Total**                               |       **17** |

There is no standalone pure declaration-pin target among the 17. The cdk8s
generator test does contain committed-output snapshot assertions; those are the
intentional sole pin and should compare the render delivered by CI rather than a
second copy committed under these trees.

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

First establish a stable Bazel input for the CI-delivered render, including the
Flux graph metadata needed by whole-graph checks. Then keep each trim small and
within one owning directory per PR:

1. `cluster/cdk8s/authentik/`: move blueprint reference validation beside its
   source/model input.
2. `cluster/cdk8s/haku_ci/`: exercise the TriggerAuthentication-to-Secret
   relation on the in-memory model.
3. `cluster/cdk8s/`: separate in-memory generator invariants from the single
   render-parity check that consumes CI output.
4. `cluster/validation/kyverno/`: point policy behavior tests at the CI-rendered
   policy bundle; keep policy fixtures and real Kyverno CLI coverage.
5. `cluster/validation/`: move the Flux build and whole-graph checks to the
   rendered artifact. Do the smaller namespace, mailbox, and ClickHouse
   relations separately; handle `test_cluster_integration` last because it
   spans the graph and currently owns several checks.
6. `cluster/debug/litellm_probe/` and `cluster/skills/grafana/`: run the two
   external artifact consumers against CI output while retaining synthetic unit
   coverage.
7. `agentplane/system_tests/`: keep the live Ollama smoke, but source its cases
   from the delivered render or deployed model API.

The order assumes that `cluster/k8s/authentik/app/blueprints/*.yaml` and the
hand-written Secret inputs remain available as generator/source inputs. If those
also move, their source-file ownership needs to be decided before the model-test
PRs. The local Git history is a one-commit shallow checkout; the linked PRs are
the available incident references. No incident citation was found for rows
marked unknown.

"""The runner SandboxTemplates: shared execution paths, the Codex executor, sidecar tokens and routes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest
import pytest_bazel
import yaml
from cdk8s import Chart, Testing as Cdk8sTesting  # not collected by pytest
from cdk8s_plus_34 import k8s
from more_itertools import one

from agentplane.crd_group import GROUP
from cluster.cdk8s.agentplane import sandbox_pod, staging
from cluster.cdk8s.agentplane.runner_sandbox import RunnerTemplate
from cluster.cdk8s.pod_policy import workload_kind


def _templates(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Our SandboxTemplates that start Pods; a VM template has no `pod`."""
    return [doc for doc in docs if workload_kind(doc) == (GROUP, "SandboxTemplate") and "pod" in doc["spec"]]


def _by_name(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return one(doc for doc in docs if doc["kind"] == kind and doc["metadata"]["name"] == name)


def _runner_pod(
    *,
    isolated_executor: bool,
    runner_resources: k8s.ResourceRequirements,
    executor_resources: k8s.ResourceRequirements | None,
) -> dict[str, Any]:
    app = Cdk8sTesting.app()
    chart = Chart(app, "runner-template-test")
    RunnerTemplate(
        chart,
        "runner-template",
        replace(staging.ENV, isolated_codex_executor=isolated_executor),
        name="test-runner",
        image="example.invalid/runner",
        runner_resources=runner_resources,
        executor_resources=executor_resources,
    )
    template = one(doc for doc in Cdk8sTesting.synth(chart) if doc["kind"] == "SandboxTemplate")
    return cast(dict[str, Any], template["spec"]["pod"]["spec"])


def test_all_sandbox_workloads_use_shared_environment_defaults(staging_manifests: list[dict[str, Any]]) -> None:
    templates = _templates(staging_manifests)
    assert templates
    for template in templates:
        workload = template["spec"]["pod"]["spec"]["containers"][0]
        timezone = next(item for item in workload["env"] if item["name"] == "TZ")
        assert timezone["value"] == "America/Los_Angeles"

    runner = next(template for template in templates if template["metadata"]["name"] == "runner")
    args = runner["spec"]["pod"]["spec"]["containers"][0]["args"]
    assert any(args[index : index + 2] == ["--harness-env", "TZ"] for index in range(len(args) - 1))
    # TZDIR's value belongs to the sandbox image, but a harness child starts from only what the
    # runner declares, so the runner has to name it: left off, the child reads every TZ as UTC.
    assert any(args[index : index + 2] == ["--harness-inherit-env", "TZDIR"] for index in range(len(args) - 1))


def test_runner_pod_gives_codex_a_private_executor_with_shared_paths(staging_manifests: list[dict[str, Any]]) -> None:
    template = _by_name(staging_manifests, "SandboxTemplate", "runner")
    pod = template["spec"]["pod"]["spec"]
    containers = {container["name"]: container for container in pod["containers"]}
    runner = containers["runner"]
    executor = containers["codex-executor"]

    assert pod["shareProcessNamespace"] is False
    assert pod["restartPolicy"] == "Always"
    assert pod["securityContext"]["runAsUser"] == pod["securityContext"]["runAsGroup"] == 1000
    assert executor["securityContext"] == runner["securityContext"]
    assert [container["name"] for container in pod["containers"]] == ["runner", "codex-executor", "egress-sidecar"]
    runner_args = runner["args"]
    executor_url_index = runner_args.index("--codex-executor-url")
    assert runner_args[executor_url_index : executor_url_index + 2] == ["--codex-executor-url", "ws://127.0.0.1:4501"]
    assert runner_args[executor_url_index + 2 : executor_url_index + 4] == [
        "--codex-executor-socket",
        "/run/agentplane/executor/control.sock",
    ]
    assert executor["command"] == ["/run/agentplane/runner/bin/agentplane-runner"]
    assert executor["args"] == [
        "--executor-container",
        "--socket",
        "/run/agentplane/executor/control.sock",
        "--listen",
        "ws://127.0.0.1:4501",
        "--binary",
        "/bin/codex",
    ]
    health = [
        "/run/agentplane/runner/bin/agentplane-runner",
        "--executor-container-health",
        "/run/agentplane/executor/control.sock",
    ]
    assert executor["livenessProbe"]["exec"]["command"] == health
    assert executor["readinessProbe"]["exec"]["command"] == health
    assert executor["image"] == runner["image"]
    assert executor["workingDir"] == runner["workingDir"] == "/state"

    runner_mounts = {mount["mountPath"]: mount["name"] for mount in runner["volumeMounts"]}
    executor_mounts = {mount["mountPath"]: mount["name"] for mount in executor["volumeMounts"]}
    for path in (
        "/state",
        "/state/workspaces",
        "/run/agentplane/runner",
        "/home/runner",
        "/tmp",
        "/run/agentplane/executor",
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/certs/java/cacerts",
        "/etc/kubernetes/kubeconfig",
    ):
        assert runner_mounts[path] == executor_mounts[path]
    volumes = {volume["name"]: volume for volume in pod["volumes"]}
    for path in ("/home/runner", "/tmp", "/run/agentplane/executor"):
        assert "emptyDir" in volumes[runner_mounts[path]]

    executor_mount_names = set(executor_mounts.values())
    assert executor_mounts["/etc/kubernetes/kubeconfig"] == "tool-config"
    assert executor_mount_names.isdisjoint({"egress-token", "platform-instructions", "buildbuddy-api-key"})
    executor_env = {variable["name"]: variable["value"] for variable in executor["env"]}
    runner_env = {variable["name"]: variable["value"] for variable in runner["env"]}
    for name in (*sandbox_pod.PROXY_VAR_NAMES, *sandbox_pod.NO_PROXY_VAR_NAMES, *sandbox_pod.CA_BUNDLE_VAR_NAMES):
        assert executor_env[name] == runner_env[name]
    assert executor_env["KUBECONFIG"] == runner_env["KUBECONFIG"]
    assert {"ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "LITELLM_URL"}.isdisjoint(executor_env)


def test_runner_template_can_override_executor_resources_independently() -> None:
    runner_resources = k8s.ResourceRequirements(
        requests={"cpu": k8s.Quantity.from_string("17m"), "memory": k8s.Quantity.from_string("127Mi")},
        limits={"cpu": k8s.Quantity.from_string("31m"), "memory": k8s.Quantity.from_string("251Mi")},
    )
    executor_resources = k8s.ResourceRequirements(
        requests={"cpu": k8s.Quantity.from_string("43m"), "memory": k8s.Quantity.from_string("509Mi")},
        limits={"cpu": k8s.Quantity.from_string("71m"), "memory": k8s.Quantity.from_string("997Mi")},
    )
    pod = _runner_pod(isolated_executor=True, runner_resources=runner_resources, executor_resources=executor_resources)
    containers = {container["name"]: container for container in pod["containers"]}
    assert containers["runner"]["resources"]["requests"] == {"cpu": "17m", "memory": "127Mi"}
    assert containers["runner"]["resources"]["limits"] == {"cpu": "31m", "memory": "251Mi"}
    assert containers["codex-executor"]["resources"]["requests"] == {"cpu": "43m", "memory": "509Mi"}
    assert containers["codex-executor"]["resources"]["limits"] == {"cpu": "71m", "memory": "997Mi"}


def test_environment_can_keep_codex_execution_inside_the_runner() -> None:
    runner_resources = k8s.ResourceRequirements(
        requests={"cpu": k8s.Quantity.from_string("17m"), "memory": k8s.Quantity.from_string("127Mi")},
        limits={"cpu": k8s.Quantity.from_string("31m"), "memory": k8s.Quantity.from_string("251Mi")},
    )
    pod = _runner_pod(isolated_executor=False, runner_resources=runner_resources, executor_resources=None)
    containers = {container["name"]: container for container in pod["containers"]}
    assert "codex-executor" not in containers
    assert "--codex-executor-url" not in containers["runner"]["args"]
    assert "--codex-executor-socket" not in containers["runner"]["args"]
    assert {"home", "tmp", "codex-executor"}.isdisjoint({volume["name"] for volume in pod["volumes"]})


def test_environment_cannot_configure_resources_for_a_disabled_executor() -> None:
    resources = k8s.ResourceRequirements(limits={"memory": k8s.Quantity.from_string("1Gi")})
    with pytest.raises(ValueError, match="executor_resources cannot be set"):
        _runner_pod(isolated_executor=False, runner_resources=resources, executor_resources=resources)


def test_ducktape_template_projects_buildbuddy_key_to_runner_and_executor(
    staging_manifests: list[dict[str, Any]],
) -> None:
    templates = {doc["metadata"]["name"]: doc for doc in _templates(staging_manifests)}
    app_config = one(
        doc for doc in staging_manifests if doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == "app-config"
    )
    presets = yaml.safe_load(app_config["data"]["config.yaml"])["sandbox_presets"]
    key_copies = [
        doc
        for doc in staging_manifests
        if doc["kind"] == "ExternalSecret"
        and doc["metadata"]["name"] == "buildbuddy-api-key"
        and doc["metadata"]["namespace"] == staging.ENV.namespace
    ]
    assert presets["public-coder-ducktape"]["template"] == "runner-ducktape"
    assert len(key_copies) == 1
    copy = key_copies[0]
    assert copy["spec"]["data"] == [
        {"remoteRef": {"key": "buildbuddy-api-key", "property": "api-key"}, "secretKey": "api-key"}
    ]
    assert copy["spec"]["secretStoreRef"]["name"] == "kubernetes-external-creds-secret-store"
    generic = templates["runner"]["spec"]
    specialized = deepcopy(templates["runner-ducktape"]["spec"])
    generic_containers = {container["name"]: container for container in generic["pod"]["spec"]["containers"]}
    specialized_containers = {container["name"]: container for container in specialized["pod"]["spec"]["containers"]}
    container = specialized_containers["runner"]
    assert container["image"] == "git.allegedly.works/ducktape-ci/runner-ducktape:unset"
    container["image"] = generic_containers["runner"]["image"]
    specialized_containers["codex-executor"]["image"] = generic_containers["codex-executor"]["image"]
    pod = specialized["pod"]["spec"]
    secret = next(volume for volume in pod["volumes"] if volume["name"] == "buildbuddy-api-key")
    assert secret["secret"] == {"secretName": "buildbuddy-api-key", "defaultMode": 288}
    pod["volumes"].remove(secret)
    mount = next(mount for mount in container["volumeMounts"] if mount["name"] == "buildbuddy-api-key")
    assert mount == {"name": "buildbuddy-api-key", "mountPath": "/run/buildbuddy", "readOnly": True}
    container["volumeMounts"].remove(mount)
    executor = specialized_containers["codex-executor"]
    executor_mount = next(mount for mount in executor["volumeMounts"] if mount["name"] == "buildbuddy-api-key")
    assert executor_mount == {"name": "buildbuddy-api-key", "mountPath": "/run/buildbuddy", "readOnly": True}
    executor["volumeMounts"].remove(executor_mount)
    sidecar = specialized_containers["egress-sidecar"]
    assert all(mount["name"] != "buildbuddy-api-key" for mount in sidecar["volumeMounts"])
    key_file = next(env for env in container["env"] if env["name"] == "BBR_BUILDBUDDY_API_KEY_FILE")
    assert key_file["value"] == "/run/buildbuddy/api-key"
    container["env"].remove(key_file)
    executor_key_file = next(env for env in executor["env"] if env["name"] == "BBR_BUILDBUDDY_API_KEY_FILE")
    assert executor_key_file["value"] == "/run/buildbuddy/api-key"
    executor["env"].remove(executor_key_file)
    args = container["args"]
    i = args.index("BBR_BUILDBUDDY_API_KEY_FILE")
    assert args[i - 1] == "--harness-env"
    del args[i - 1 : i + 1]
    settings = next(volume for volume in pod["volumes"] if volume["name"] == "egress-sidecar-settings")
    generic_settings = next(
        volume for volume in generic["pod"]["spec"]["volumes"] if volume["name"] == "egress-sidecar-settings"
    )
    # Each template owns its sidecar settings ConfigMap; the specialization adds none.
    assert settings["configMap"]["name"] == "runner-ducktape-egress-sidecar"
    assert (
        _by_name(staging_manifests, "ConfigMap", settings["configMap"]["name"])["data"]
        == _by_name(staging_manifests, "ConfigMap", generic_settings["configMap"]["name"])["data"]
    )
    settings["configMap"]["name"] = generic_settings["configMap"]["name"]
    # No extra authority in generic runners or the egress sidecar.
    assert specialized == generic


def test_staging_app_config_offers_ollama_smoke_routes(staging_manifests: list[dict[str, Any]]) -> None:
    app_config = yaml.safe_load(_by_name(staging_manifests, "ConfigMap", "app-config")["data"]["config.yaml"])
    ollama_routes = {model["model"] for model in app_config["models"]["models"] if model["model"].startswith("ollama/")}
    offered_routes = {route for routes in app_config["models"]["harnesses"].values() for route in routes}
    assert ollama_routes & offered_routes, "Agentplane staging must offer at least one Ollama route for smoke tests"


def test_launcher_relay_listens_on_every_interface_and_otherwise_matches_the_runner_sidecar(
    staging_manifests: list[dict[str, Any]],
) -> None:

    def settings(name: str) -> dict[str, Any]:
        return cast(
            dict[str, Any], yaml.safe_load(_by_name(staging_manifests, "ConfigMap", name)["data"]["settings.yaml"])
        )

    runner_settings = settings("runner-egress-sidecar")
    launcher_settings = settings("launcher-relay-egress-sidecar")
    assert "listen_address" not in runner_settings
    assert launcher_settings["listen_address"] == "0.0.0.0:3128"
    for name, route in runner_settings["platform_routes"].items():
        _, port = route["listen_address"].rsplit(":", 1)
        assert route["listen_address"] == f"127.0.0.1:{port}"
        assert launcher_settings["platform_routes"][name]["listen_address"] == f"0.0.0.0:{port}"
        launcher_settings["platform_routes"][name]["listen_address"] = route["listen_address"]
    del launcher_settings["listen_address"]
    assert launcher_settings == runner_settings
    policy = _by_name(staging_manifests, "ClusterPolicy", f"{staging.ENV.namespace}-launcher-relay")
    inject = one(rule for rule in policy["spec"]["rules"] if rule["name"] == "inject-relay")
    volumes = inject["mutate"]["patchStrategicMerge"]["spec"]["volumes"]
    assert {"name": "egress-sidecar-settings", "configMap": {"name": "launcher-relay-egress-sidecar"}} in volumes


def test_runner_tool_config_role_is_scoped_to_the_canonical_map(staging_manifests: list[dict[str, Any]]) -> None:
    _by_name(staging_manifests, "ConfigMap", "sandbox-tool-config")
    role = _by_name(staging_manifests, "Role", "agentplane-sandbox-tool-config-reader")
    assert role["rules"] == [
        {"apiGroups": [""], "resourceNames": ["sandbox-tool-config"], "resources": ["configmaps"], "verbs": ["get"]}
    ]

    runner = next(template for template in _templates(staging_manifests) if template["metadata"]["name"] == "runner")
    volumes = runner["spec"]["pod"]["spec"]["volumes"]
    config_maps = {volume["name"]: volume["configMap"]["name"] for volume in volumes if "configMap" in volume}
    assert config_maps["platform-instructions"] == "runner-platform-instructions"
    assert config_maps["tool-config"] == "sandbox-tool-config"


if __name__ == "__main__":
    pytest_bazel.main()

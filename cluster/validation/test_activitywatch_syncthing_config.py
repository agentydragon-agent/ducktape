"""Parity checks for ActivityWatch's static Syncthing config."""

from __future__ import annotations

import base64
import hashlib
import ssl
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

import pytest_bazel
import yaml

from util.bazel.runfiles import get_required_path

CONFIG_XML = get_required_path("_main/cluster/k8s/x/activitywatch/syncthing-config.xml")
CLUSTER_IDENTITY = get_required_path("_main/cluster/k8s/x/activitywatch/syncthing-identity.yaml")
CLUSTER_KEY = get_required_path("_main/cluster/k8s/x/activitywatch/syncthing-key.sops.yaml")
SYNCTHING_DEPLOYMENT = get_required_path("_main/cluster/k8s/x/activitywatch/syncthing-deployment.yaml")
IMPORTER_CRONJOB = get_required_path("_main/cluster/k8s/x/activitywatch/importer-cronjob.yaml")
PVC_MANIFEST = get_required_path("_main/cluster/k8s/x/activitywatch/pvc.yaml")
OVH_STORAGE_CLASS = get_required_path("_main/cluster/k8s/local-path-provisioner/sc-local-path-ovh.yaml")
HOST_CERT_SENTINEL = get_required_path("_main/secrets/home/rugged/activitywatch-syncthing.cert.pem")

SYNCTHING_BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def _luhn32_check_char(chunk: str) -> str:
    factor = 1
    total = 0
    for char in reversed(chunk):
        addend = factor * SYNCTHING_BASE32_ALPHABET.index(char)
        factor = 1 if factor == 2 else 2
        total += (addend // len(SYNCTHING_BASE32_ALPHABET)) + (addend % len(SYNCTHING_BASE32_ALPHABET))
    return SYNCTHING_BASE32_ALPHABET[(-total) % len(SYNCTHING_BASE32_ALPHABET)]


def _device_id_from_cert(pem: str) -> str:
    cert_der = ssl.PEM_cert_to_DER_cert(pem)
    digest = base64.b32encode(hashlib.sha256(cert_der).digest()).decode("ascii").rstrip("=")
    checked = "".join(
        digest[index : index + 13] + _luhn32_check_char(digest[index : index + 13])
        for index in range(0, len(digest), 13)
    )
    return "-".join(checked[index : index + 7] for index in range(0, len(checked), 7))


def _read_yaml(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load(path.read_text()))


def _host_devices_from_cert_files() -> dict[str, str]:
    home_secrets_dir = HOST_CERT_SENTINEL.parents[1]
    devices = {}
    for cert_path in sorted(home_secrets_dir.glob("*/activitywatch-syncthing.cert.pem")):
        host = cert_path.parent.name
        key_path = cert_path.with_name("activitywatch-syncthing.sops.key")
        assert key_path.exists(), f"{host} is missing {key_path.name}"
        assert "ENC[AES256_GCM" in key_path.read_text(), f"{key_path} is not SOPS-encrypted"
        devices[host] = _device_id_from_cert(cert_path.read_text())
    return devices


def _cluster_device_from_identity() -> dict[str, str]:
    identity = _read_yaml(CLUSTER_IDENTITY)
    key_secret = _read_yaml(CLUSTER_KEY)
    assert "device_id" not in identity["data"]
    assert "ENC[AES256_GCM" in key_secret["data"]["key.pem"]
    return {"activitywatch-cluster": _device_id_from_cert(identity["data"]["cert.pem"])}


def _expected_devices() -> dict[str, str]:
    return _host_devices_from_cert_files() | _cluster_device_from_identity()


def test_syncthing_config_matches_identity_sources() -> None:
    expected_devices = _expected_devices()

    root = ET.parse(CONFIG_XML).getroot()
    assert {device.attrib["id"] for folder in root.findall("folder") for device in folder.findall("device")} == set(
        expected_devices.values()
    )

    xml_devices = {device.attrib["name"]: device for device in root.findall("device")}
    assert set(xml_devices) == set(expected_devices)

    for name, expected_device_id in expected_devices.items():
        assert xml_devices[name].attrib["id"] == expected_device_id


def test_ovh_workloads_use_the_canonical_zone_label() -> None:
    syncthing = _read_yaml(SYNCTHING_DEPLOYMENT)
    importer = _read_yaml(IMPORTER_CRONJOB)
    storage_class = _read_yaml(OVH_STORAGE_CLASS)
    zone_requirement = next(
        requirement
        for topology in storage_class["allowedTopologies"]
        for requirement in topology["matchLabelExpressions"]
        if requirement["key"] == "topology.kubernetes.io/zone"
    )
    [zone] = zone_requirement["values"]
    expected_selector = {zone_requirement["key"]: zone}

    assert syncthing["spec"]["template"]["spec"]["nodeSelector"] == expected_selector
    assert importer["spec"]["jobTemplate"]["spec"]["template"]["spec"]["nodeSelector"] == expected_selector


def test_syncthing_index_state_is_persistent() -> None:
    syncthing = _read_yaml(SYNCTHING_DEPLOYMENT)
    pod_spec = syncthing["spec"]["template"]["spec"]
    init_mounts = {
        mount["name"] for container in pod_spec["initContainers"] for mount in container.get("volumeMounts", [])
    }
    production_mounts = {
        mount["name"] for container in pod_spec["containers"] for mount in container.get("volumeMounts", [])
    }
    state_volume = next(
        volume
        for volume in pod_spec["volumes"]
        if volume["name"] in init_mounts & production_mounts and "persistentVolumeClaim" in volume
    )

    pvcs = {manifest["metadata"]["name"]: manifest for manifest in yaml.safe_load_all(PVC_MANIFEST.read_text())}
    state_pvc = pvcs[state_volume["persistentVolumeClaim"]["claimName"]]
    assert state_pvc["spec"]["storageClassName"] == _read_yaml(OVH_STORAGE_CLASS)["metadata"]["name"]


def test_importer_is_suspended_pull_only_and_fails_closed() -> None:
    importer = _read_yaml(IMPORTER_CRONJOB)
    assert importer["spec"]["suspend"] is True
    assert importer["spec"]["concurrencyPolicy"] == "Forbid"

    pod_spec = importer["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    validator = next(
        container
        for container in pod_spec["initContainers"]
        if "Refusing to import unexpected database" in container["command"][-1]
    )
    validator_script = validator["command"][-1]
    assert "-name '*.db'" in validator_script
    assert "!= test.db" in validator_script
    validator_mount = next(mount for mount in validator["volumeMounts"] if mount["mountPath"] in validator_script)
    assert validator_mount["readOnly"] is True

    container = next(container for container in pod_spec["containers"] if "sync" in container.get("command", []))
    command = container["command"]
    assert command[-3:] == ["sync", "--mode", "pull"]
    assert "push" not in command
    importer_mount = next(mount for mount in container["volumeMounts"] if mount["mountPath"] in command)
    assert importer_mount["name"] == validator_mount["name"]

    inbox_volume = next(volume for volume in pod_spec["volumes"] if volume["name"] == importer_mount["name"])
    pvcs = {manifest["metadata"]["name"]: manifest for manifest in yaml.safe_load_all(PVC_MANIFEST.read_text())}
    inbox_pvc = pvcs[inbox_volume["persistentVolumeClaim"]["claimName"]]
    assert "ReadWriteMany" in inbox_pvc["spec"]["accessModes"]


if __name__ == "__main__":
    pytest_bazel.main()

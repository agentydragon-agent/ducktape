"""Render the retired Claude injection policy for revival regression coverage.

Unlike active policies, this must not be loaded from the deployed policy bundle.
"""

from pathlib import Path

import yaml
from cdk8s import Testing as Cdk8sTesting

from cluster.cdk8s.kyverno.proxy_injection import inject_mitmproxy_chart


def parked_mitmproxy_policy(directory: Path) -> Path:
    path = directory / "parked-inject-mitmproxy.yaml"
    path.write_text(yaml.safe_dump_all(Cdk8sTesting.synth(inject_mitmproxy_chart(Cdk8sTesting.app()))))
    return path

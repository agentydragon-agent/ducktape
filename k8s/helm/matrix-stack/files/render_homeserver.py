#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def main() -> None:
    template_path = Path(os.environ.get("HOMESERVER_TEMPLATE", "/tmpl/homeserver.yaml.tmpl"))
    output_path = Path(os.environ.get("HOMESERVER_OUTPUT", "/config/homeserver.yaml"))

    reg_secret = os.environ.get("REGISTRATION_SHARED_SECRET")
    if not reg_secret:
        raise SystemExit("REGISTRATION_SHARED_SECRET must be set")

    content = template_path.read_text()
    content = content.replace("${REGISTRATION_SHARED_SECRET}", reg_secret)

    oidc_secret = os.environ.get("OIDC_CLIENT_SECRET")
    if oidc_secret:
        content = content.replace("${OIDC_CLIENT_SECRET}", oidc_secret)

    output_path.write_text(content)


if __name__ == "__main__":
    main()

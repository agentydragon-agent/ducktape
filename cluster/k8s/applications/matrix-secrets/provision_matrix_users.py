"""Provision Matrix users on Synapse: admin + OpenClaw bot.

Two-phase idempotent provisioning:
  Phase 1: Register _provisioner as admin via shared-secret endpoint.
           Skips if user already exists (M_USER_IN_USE).
  Phase 2: Log in as _provisioner, then PUT the bot user via Synapse admin API.
           Creates or updates (handles password drift).

Requires: REGISTRATION_SECRET, ADMIN_PASSWORD, BOT_PASSWORD env vars.
"""

import hashlib
import hmac
import json
import os
import urllib.request

SYNAPSE_URL = "http://matrix-synapse.matrix.svc.cluster.local:8008"
ADMIN_USERNAME = "_provisioner"
BOT_USERNAME = "openclaw"
SERVER_NAME = "allegedly.works"


def _post_json(url: str, data: dict, headers: dict | None = None) -> dict:
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, json.dumps(data).encode(), headers=hdrs)
    return json.loads(urllib.request.urlopen(req).read())


def _put_json(url: str, data: dict, headers: dict) -> dict:
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers)
    req = urllib.request.Request(url, json.dumps(data).encode(), headers=hdrs, method="PUT")
    return json.loads(urllib.request.urlopen(req).read())


def register_admin(registration_secret: str, admin_password: str) -> None:
    """Phase 1: Register _provisioner as admin via shared-secret."""
    # Get nonce
    req = urllib.request.Request(f"{SYNAPSE_URL}/_synapse/admin/v1/register")
    resp = json.loads(urllib.request.urlopen(req).read())
    nonce = resp["nonce"]

    # HMAC-SHA1: nonce\0username\0password\0admin
    mac_input = f"{nonce}\0{ADMIN_USERNAME}\0{admin_password}\0admin"
    mac = hmac.new(registration_secret.encode(), mac_input.encode(), hashlib.sha1).hexdigest()

    try:
        result = _post_json(
            f"{SYNAPSE_URL}/_synapse/admin/v1/register",
            {"nonce": nonce, "username": ADMIN_USERNAME, "password": admin_password, "admin": True, "mac": mac},
        )
        print(f"Phase 1: Registered admin @{result['user_id']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 400 and "M_USER_IN_USE" in body:
            print(f"Phase 1: Admin @{ADMIN_USERNAME}:{SERVER_NAME} already exists, skipping")
            return
        raise RuntimeError(f"Phase 1 failed: HTTP {e.code} - {body}") from e


def upsert_bot(admin_password: str, bot_password: str) -> None:
    """Phase 2: Log in as admin, then create/update bot user via admin API."""
    # Log in as _provisioner
    login_resp = _post_json(
        f"{SYNAPSE_URL}/_matrix/client/v3/login",
        {
            "type": "m.login.password",
            "identifier": {"type": "m.id.user", "user": ADMIN_USERNAME},
            "password": admin_password,
        },
    )
    access_token = login_resp["access_token"]
    print(f"Phase 2: Logged in as @{ADMIN_USERNAME}:{SERVER_NAME}")

    # PUT bot user (creates if missing, updates password if exists)
    bot_mxid = f"@{BOT_USERNAME}:{SERVER_NAME}"
    encoded_mxid = urllib.request.quote(bot_mxid)
    result = _put_json(
        f"{SYNAPSE_URL}/_synapse/admin/v2/users/{encoded_mxid}",
        {"password": bot_password, "displayname": "OpenClaw", "admin": False},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    print(f"Phase 2: Upserted {bot_mxid} (displayname: {result.get('displayname', 'n/a')})")


def main() -> None:
    registration_secret = os.environ["REGISTRATION_SECRET"]
    admin_password = os.environ["ADMIN_PASSWORD"]
    bot_password = os.environ["BOT_PASSWORD"]

    register_admin(registration_secret, admin_password)
    upsert_bot(admin_password, bot_password)
    print("Done: all Matrix users provisioned")


if __name__ == "__main__":
    main()

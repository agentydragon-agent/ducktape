"""Register the @openclaw:allegedly.works bot user on Synapse.

Idempotent: attempts registration and gracefully handles "user already exists".
Requires REGISTRATION_SECRET and BOT_PASSWORD environment variables.
"""

import hashlib
import hmac
import json
import os
import urllib.request

SYNAPSE_URL = "http://matrix-synapse.matrix.svc.cluster.local:8008"
USERNAME = "openclaw"
SERVER_NAME = "allegedly.works"


def main() -> None:
    password = os.environ["BOT_PASSWORD"]
    secret = os.environ["REGISTRATION_SECRET"]

    # Get nonce from registration endpoint
    req = urllib.request.Request(f"{SYNAPSE_URL}/_synapse/admin/v1/register")
    resp = json.loads(urllib.request.urlopen(req).read())
    nonce = resp["nonce"]

    # Compute HMAC-SHA1
    mac_input = f"{nonce}\0{USERNAME}\0{password}\0notadmin"
    mac = hmac.new(secret.encode(), mac_input.encode(), hashlib.sha1).hexdigest()

    # Attempt registration
    data = json.dumps({"nonce": nonce, "username": USERNAME, "password": password, "admin": False, "mac": mac}).encode()
    req = urllib.request.Request(
        f"{SYNAPSE_URL}/_synapse/admin/v1/register", data=data, headers={"Content-Type": "application/json"}
    )
    try:
        result = json.loads(urllib.request.urlopen(req).read())
        print(f"Registered @{result['user_id']} (device: {result.get('device_id', 'n/a')})")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        # Synapse returns 400 with M_USER_IN_USE if user already exists
        if e.code == 400 and "M_USER_IN_USE" in body:
            print(f"User @{USERNAME}:{SERVER_NAME} already exists, skipping")
            return
        raise RuntimeError(f"Registration failed: HTTP {e.code} - {body}") from e


if __name__ == "__main__":
    main()

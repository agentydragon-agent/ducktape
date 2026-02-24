"""Register the @openclaw:allegedly.works bot user on Synapse.

Idempotent: skips registration if the user already exists.
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

    # Check if user already exists
    try:
        req = urllib.request.Request(f"{SYNAPSE_URL}/_synapse/admin/v1/username_available?username={USERNAME}")
        urllib.request.urlopen(req)
        print(f"Username {USERNAME} is available, proceeding with registration")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            print(f"User @{USERNAME}:{SERVER_NAME} already exists, skipping")
            return
        raise

    # Get nonce
    req = urllib.request.Request(f"{SYNAPSE_URL}/_synapse/admin/v1/register")
    resp = json.loads(urllib.request.urlopen(req).read())
    nonce = resp["nonce"]

    # Compute HMAC
    mac_input = f"{nonce}\0{USERNAME}\0{password}\0notadmin"
    mac = hmac.new(secret.encode(), mac_input.encode(), hashlib.sha1).hexdigest()

    # Register
    data = json.dumps({"nonce": nonce, "username": USERNAME, "password": password, "admin": False, "mac": mac}).encode()
    req = urllib.request.Request(
        f"{SYNAPSE_URL}/_synapse/admin/v1/register", data=data, headers={"Content-Type": "application/json"}
    )
    result = json.loads(urllib.request.urlopen(req).read())
    print(f"Registered @{result['user_id']} (device: {result.get('device_id', 'n/a')})")


if __name__ == "__main__":
    main()

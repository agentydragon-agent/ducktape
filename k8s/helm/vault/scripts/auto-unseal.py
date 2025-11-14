#!/usr/bin/env python3
from datetime import datetime
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
os.environ["PYTHONUNBUFFERED"] = "1"


def log(message):
    print(f"{datetime.now().isoformat()}: {message}", flush=True)


def get_vault_status():
    """Get Vault status using HTTP API"""
    try:
        vault_addr = os.getenv("VAULT_ADDR", "https://vault.vault.svc:8200")
        ca_cert = os.getenv("VAULT_CACERT")

        # Create SSL context
        if ca_cert and Path(ca_cert).exists():
            ssl_context = ssl.create_default_context(cafile=ca_cert)
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        request = urllib.request.Request(f"{vault_addr}/v1/sys/seal-status")
        with urllib.request.urlopen(
            request, timeout=10, context=ssl_context
        ) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        log(f"Error getting Vault status: {e}")
        return None


def get_unseal_key():
    """Get unseal key from mounted secret"""
    try:
        # Read the base64 encoded key from the mounted secret
        key_file = Path("/vault/unseal/unseal-key")
        if not key_file.exists():
            return None
        # The key is already base64 encoded in the secret, use it directly
        return key_file.read_text().strip()
    except Exception as e:
        log(f"Error reading unseal key: {e}")
        return None


def unseal_vault(unseal_key):
    """Attempt to unseal Vault using HTTP API"""
    try:
        vault_addr = os.getenv("VAULT_ADDR", "https://vault.vault.svc:8200")
        ca_cert = os.getenv("VAULT_CACERT")

        # Create SSL context
        if ca_cert and Path(ca_cert).exists():
            ssl_context = ssl.create_default_context(cafile=ca_cert)
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        payload = {"key": unseal_key}
        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{vault_addr}/v1/sys/unseal",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(
            request, timeout=10, context=ssl_context
        ) as response:
            result = json.loads(response.read().decode())
            return not result.get("sealed", True)  # Return True if unsealed
    except Exception as e:
        log(f"Error unsealing Vault: {e}")
        return False


def main():
    log("🚀 Vault Auto-Unseal Service Starting...")

    # Verify unseal key is available at startup
    if not Path("/vault/unseal/unseal-key").exists():
        log("❌ FATAL: Unseal key secret not mounted at /vault/unseal/unseal-key")
        sys.exit(1)

    while True:
        log("🔍 Checking Vault seal status...")

        status = get_vault_status()
        if status is None:
            log("⏳ Vault is not responding yet, waiting...")
            time.sleep(10)
            continue

        if not status.get("sealed", False):
            log("✅ Vault is already unsealed")
            time.sleep(10)
            continue

        log("🔒 Vault is sealed, attempting auto-unseal...")

        unseal_key = get_unseal_key()
        if not unseal_key:
            log("❌ Failed to retrieve unseal key from mounted secret")
            time.sleep(10)
            continue

        log("🔑 Retrieved unseal key, unsealing Vault...")
        if unseal_vault(unseal_key):
            log("✅ Vault unsealed successfully!")
        else:
            log("❌ Failed to unseal Vault")

        time.sleep(10)


if __name__ == "__main__":
    main()

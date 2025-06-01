#!/usr/bin/env python3
"""
tools/make_wg_host.py - generate WireGuard keys per host into
host_vars/<host>/wireguard.yml, encrypting the private key
with Ansible Vault.

Prereqs on the control machine (run once):
  sudo apt install wireguard-tools ansible-core libsecret-tools

Usage:
  python tools/mk_wg_host.py server1 laptop phone …
"""

import pathlib
import subprocess
import sys

ANSIBLE_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOST_VARS = ANSIBLE_ROOT / "host_vars"


def run(cmd, *, stdin=None) -> str:
    return subprocess.check_output(cmd, input=stdin).strip().decode()


def gen_wg_keypair() -> tuple[str, str]:
    "Returns (private, public) keys, both base64."
    priv = run(["wg", "genkey"])
    pub = run(["wg", "pubkey"], stdin=priv.encode())
    return priv, pub


def vault_encrypt(var_name: str, plaintext: str) -> str:
    "Encrypt a string with ansible-vault and return the encrypted YAML block."
    return run(
        [
            "ansible-vault",
            "encrypt_string",
            plaintext,
            "--name",
            var_name,
        ],
    )


def write_host_file(host: str):
    priv, pub = gen_wg_keypair()

    host_dir = HOST_VARS / host
    host_dir.mkdir(parents=True, exist_ok=True)
    outfile = host_dir / "wireguard.yml"

    if outfile.exists():
        print(f"⚠️  {outfile} already exists - skipping", file=sys.stderr)
        return

    encrypted = vault_encrypt("wg_private", priv)

    with outfile.open("w", encoding="utf-8", newline="\n") as f:
        f.write(encrypted + "\n")
        f.write(f'wg_public: "{pub}"\n')

    print(f"✅  Wrote {outfile}")


def main():
    if len(sys.argv) < 2:
        print("Usage: mk_wg_host.py <host1> [host2 ...]", file=sys.stderr)
        sys.exit(1)

    for h in sys.argv[1:]:
        write_host_file(h)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Generate WireGuard QR code for mobile device configuration."""

import argparse
from pathlib import Path
import sys

import qrcode

from ansible import constants as C  # type: ignore[attr-defined]  # noqa: N812
from ansible.cli import CLI
from ansible.inventory.manager import InventoryManager
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from ansible.vars.manager import VariableManager


def generate_config(host: str) -> str:
    """Generate WireGuard host configuration using Ansible's logic."""
    # Initialize Ansible components
    loader = DataLoader()
    loader.set_vault_secrets(
        CLI.setup_vault_secrets(loader=loader, vault_ids=C.DEFAULT_VAULT_IDENTITY_LIST),
    )
    inventory = InventoryManager(loader=loader, sources=C.DEFAULT_HOST_LIST)
    variable_manager = VariableManager(loader=loader, inventory=inventory)

    if not (host_obj := inventory.get_host(host)):
        sys.exit(f"Host '{host}' not in inventory")

    # Get all variables for this host
    host_vars = variable_manager.get_vars(host=host_obj)

    # Check if host has WireGuard configuration
    if "wg_private" not in host_vars:
        sys.exit(f"No WireGuard config for '{host}'")

    # Create templar with host variables
    templar = Templar(loader=loader, variables=host_vars)

    # Set required template variables
    templar.available_variables["inventory_hostname"] = host

    # Build groups dictionary
    templar.available_variables["groups"] = {
        group_name: [h.name for h in group.hosts]
        for group_name, group in inventory.groups.items()
    }

    # Build hostvars dictionary
    templar.available_variables["hostvars"] = {
        hostname: variable_manager.get_vars(host=h_obj)
        for hostname in inventory.hosts
        if (h_obj := inventory.get_host(hostname))
    }

    # Load and render template
    template_path = (
        Path(__file__).parent.parent
        / "roles"
        / "wireguard"
        / "templates"
        / "wg0.conf.j2"
    )
    return templar.template(template_path.read_text())


def main():
    parser = argparse.ArgumentParser(description="Generate WireGuard QR code")
    parser.add_argument("host", help="Host name (e.g., pixel6)")
    args = parser.parse_args()
    config = generate_config(args.host)

    # Generate QR code
    qr = qrcode.QRCode()
    qr.add_data(config)
    qr.make(fit=True)
    qr.print_ascii()

    print("\nConfiguration preview:")
    print("=" * 50)
    print(config)
    print("=" * 50)


if __name__ == "__main__":
    main()

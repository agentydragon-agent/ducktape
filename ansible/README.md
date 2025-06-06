## Per-host setup for deployment

Grab `VAULT_KEY`. Save in keyring:

```bash
echo -n "$VAULT_KEY" | \
  secret-tool store --label='ansible-vault ducktape' \
    service ansible-vault account ducktape
```

## Caveats

* The `rcup` command asks for confirmation before overwriting existing dotfiles.
  Which we can't give from an Ansible playbook. Which sucks.

## To update requirements

```bash
ansible-galaxy install -r requirements.yaml
```

## To deploy localhost

```bash
ansible-playbook agentydragon.yaml --ask-become-pass
```

## To deploy cloudragon

```bash
ansible-playbook cloudragon.yaml --ask-become-pass
```

## To deploy linode

```bash
ansible-playbook vps.yaml
```

NOTE: running with `--skip-tags` might not work in any reasonable way. I didn't
assign task particularly with that in mind... :/

On GPD: `--skip-tags bazel-remote-cache` -- because I don't have the Bazel
remote cache `htpasswd` on GPD.

## To deploy gpd

```bash
ansible-playbook gpd.yaml --ask-become-pass
```

### TODO

Make worthy work, actually.

- zoom (for meetings)
- ubuntu-desktop

TODO: minimize texlive, etc.

TODO: refactor Let's Encrypt - this way it's invoking the role 3 times,
repeating the same setup steps like reading users for the letsencrypt group and
such.

TODO: store htpasswd into Ansible Vault

## Manual VPS installation steps

These parts aren't yet done by Ansible:

* `htpasswd` for `bazel-remote-cache` is not stored in the repo - but that
  should be fine, those creds are cheap to rotate.
  It's expected to be in `$(repo root)/ansible/bazel_remote_cache.htpasswd`.
* Setup steps for Inventree - see https://docs.inventree.org/en/latest/start/docker_install/#initial-database-setup
  (making databases etc)

## Manual laptop installation steps

These parts can't be done by Ansible:

* `ssh-keygen`
* Add key to GitHub
* `apt install git ansible`
* `git clone git@github.com:agentydragon/playbooks`
* `ansible-playbook agentydragon.yaml --ask-become-pass`
* Add `~/.config/bazelrc.secrets` - see the `bazelrc` dotfile. The global
  `bazelrc` imports this file, it's supposed to contain the path (and
  password) to the Bazel cache on the VPS.

## WireGuard

The WireGuard VPN network provides secure connectivity between all managed devices using a hub-and-spoke topology with the VPS as the central hub.

### Network Layout

| Host | IP Address | Description | Notes |
|------|------------|-------------|-------|
| `vps` | 10.13.13.1/24 | VPS Hub | Accessible at agentydragon.com:51820 |
| `agentydragon` | 10.13.13.11/24 | ThinkPad X1 Extreme | |
| `gpd` | 10.13.13.12/24 | GPD Win Max 2 | |
| `homeassistant` | 10.13.13.100/24 | Home Assistant | Not managed by Ansible |
| `pixel6` | 10.13.13.50/24 | Pixel 6 phone | |

### Adding a New Device

To add a new device to the WireGuard network:

1. Generate keypair and create host vars:
   ```bash
   cd ansible
   python tools/make_wg_host.py <hostname>
   ```

2. Assign an IP address by editing `host_vars/<hostname>/wireguard.yml`:
   ```yaml
   wg_address: "10.13.13.XX/24"  # Choose an unused IP
   ```

3. Add the host to the `wg_peers` group in `inventory.yaml`:
   ```yaml
   wg_peers:
     hosts:
       # ... existing hosts ...
       <hostname>: # Description
   ```

4. Deploy the configuration:
   ```bash
   # Deploy to VPS to update peer allowlist
   ansible-playbook vps.yaml --tags wireguard
   
   # Deploy to the new device (if managed by Ansible)
   ansible-playbook <hostname>.yaml --tags wireguard
   ```

### Mobile Device Setup

For mobile devices (Android/iOS), generate a QR code for easy setup:

```bash
cd ansible
python tools/make_wg_qr.py <hostname>

# Or save QR code to file
python tools/make_wg_qr.py <hostname> -o wireguard-<hostname>.png
```

Scan the QR code with the WireGuard mobile app to import the configuration.

### Features Enabled

* All devices report ActivityWatch data to the central server on VPS
* Secure access to internal services
* Cross-device connectivity

## VPS SyncThing management

```zsh
ssh -L 9092:localhost:8384 root@agentydragon.com
```

Then open <http://localhost:9092> in a browser.

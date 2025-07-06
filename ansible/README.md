## Per-host setup for deployment

Grab `VAULT_KEY`. Save in keyring:

```bash
echo -n "$VAULT_KEY" | \
  secret-tool store --label='ansible-vault ducktape' \
    service ansible-vault account ducktape
```

## Generating secrets

To generate and encrypt a secret in one go:

```bash
# Generate a 32-character password and encrypt it
python3 -c "import secrets; print(secrets.token_urlsafe(32))" | \
  ansible-vault encrypt_string --stdin-name 'vault_variable_name'
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
* Add key to GitHub (see GitHub SSH Key Setup section below)
* `apt install git ansible`
* `git clone git@github.com:agentydragon/ducktape`
* `ansible-playbook agentydragon.yaml --ask-become-pass`
* Add `~/.config/bazelrc.secrets` - see the `bazelrc` dotfile. The global
  `bazelrc` imports this file, it's supposed to contain the path (and
  password) to the Bazel cache on the VPS.

## Manual VM/Remote Machine Setup

When provisioning a new VM or remote machine:

Note: The ducktape repository must be cloned before running the playbook, as the dotfiles deployment depends on it.

1. Generate SSH key and add to GitHub/GitLab (see sections below)
2. Clone ducktape repository and checkout devel branch:
   ```bash
   ssh agentydragon@NEW_MACHINE_IP 'mkdir -p ~/code && git clone git@gitlab.com:agentydragon/ducktape ~/code/ducktape && cd ~/code/ducktape && git checkout devel'
   ```
3. Run the playbook from your provisioning machine:
   ```bash
   ansible-playbook new-vm.yaml --ask-become-pass
   ```
4. If the playbook fails on dotfiles installation, SSH to the machine and run:
   ```bash
   ssh agentydragon@NEW_MACHINE_IP 'RCRC=~/code/ducktape/dotfiles/rcrc rcup -B new-vm'
   ```
   You'll need to confirm overwriting default files like .bashrc with 'y'.

## GitHub SSH Key Setup

After generating an SSH key on a new machine, you can add it to GitHub using the GitHub CLI from your provisioning machine:

```bash
# On the new machine, generate SSH key:
ssh-keygen -t ed25519 -C "agentydragon@HOSTNAME"

# From your provisioning machine (with gh installed and authenticated):
ssh agentydragon@NEW_MACHINE_IP 'cat ~/.ssh/id_ed25519.pub' | \
  gh ssh-key add - --title "HOSTNAME"

# Add GitHub to known hosts on the new machine:
ssh agentydragon@NEW_MACHINE_IP 'ssh-keyscan github.com >> ~/.ssh/known_hosts'

# Verify it worked from the new machine:
ssh agentydragon@NEW_MACHINE_IP 'ssh -T git@github.com'
```

## GitLab SSH Key Setup

Similar process for GitLab:

```bash
# From your provisioning machine (with glab installed and authenticated):
ssh agentydragon@NEW_MACHINE_IP 'cat ~/.ssh/id_ed25519.pub' | \
  glab ssh-key add -t "HOSTNAME"

# Add GitLab to known hosts on the new machine:
ssh agentydragon@NEW_MACHINE_IP 'ssh-keyscan gitlab.com >> ~/.ssh/known_hosts'

# Verify it worked from the new machine:
ssh agentydragon@NEW_MACHINE_IP 'ssh -T git@gitlab.com'
```

TODO: Document how to set up `gh` authentication on the new machine (for CLI operations beyond SSH)
TODO: Document how to set up `glab` authentication on the new machine (for CLI operations beyond SSH)
TODO (low priority): Consider adding repository setup + package install as an option to the shared Python install implementation, since "add repo & install package" is a common pattern and deb822_repository doesn't reliably trigger apt cache update
TODO (low priority): Optimize rcrc deployment to avoid duplication - can be done by first copying over .rcrc, or by pointing RCM at a different .rcrc path => can take effect before deployed
TODO: Handle cronomix config - unclear how it should be managed (rcm symlinks individual files in ~/.config/cronomix, not the directory itself)
TODO (low priority): XDG associations (mimeapps.list) shouldn't be an rcm-managed dotfile - it's already being asserted/managed in ansible

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

Open on WireGuard network: <http://10.13.13.1:8384>

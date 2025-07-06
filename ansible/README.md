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

## To deploy

```bash
ansible-playbook agentydragon.yaml --ask-become-pass

ansible-playbook cloudragon.yaml --ask-become-pass

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
* Add `~/.config/bazelrc.secrets` - see the `bazelrc` dotfile. Global `bazelrc` imports this file, it's supposed to contain the path (and
  password) to the Bazel cache on the VPS.

## Manual VM/Remote Machine Setup

When provisioning a new VM or remote machine:

1. The ducktape repository must be cloned before running the playbook, as the dotfiles deployment depends on it.
2. Generate SSH key and add to GitHub/GitLab:
   ```bash
   # On the new machine, generate SSH key:
   ssh-keygen -t ed25519 -C "agentydragon@HOSTNAME"
   
   # Add both GitHub and GitLab to known hosts on the new machine:
   ssh agentydragon@NEW_MACHINE_IP 'ssh-keyscan github.com gitlab.com >> ~/.ssh/known_hosts'
   
   # From your provisioning machine (with gh installed and authenticated):
   ssh agentydragon@NEW_MACHINE_IP 'cat ~/.ssh/id_ed25519.pub' | \
     gh ssh-key add - --title "HOSTNAME"
   
   # From your provisioning machine (with glab installed and authenticated):
   ssh agentydragon@NEW_MACHINE_IP 'cat ~/.ssh/id_ed25519.pub' | \
     glab ssh-key add -t "HOSTNAME"
   
   # Verify both worked from the new machine:
   ssh agentydragon@NEW_MACHINE_IP 'for host in github.com gitlab.com; do echo "Testing $host:"; ssh -T git@$host; done'
   ```
3. Clone ducktape repository and checkout devel branch:
   ```bash
   ssh agentydragon@NEW_MACHINE_IP 'mkdir -p ~/code && git clone git@gitlab.com:agentydragon/ducktape ~/code/ducktape && cd ~/code/ducktape && git checkout devel'
   ```
4. Run the playbook from your provisioning machine:
   ```bash
   ansible-playbook new-vm.yaml --ask-become-pass
   ```
   When prompted for the BECOME password, enter the sudo password for the agentydragon user on the VM.
5. If the playbook fails on dotfiles installation, SSH to the machine and run:
   ```bash
   ssh agentydragon@NEW_MACHINE_IP 'RCRC=~/code/ducktape/dotfiles/rcrc rcup -B new-vm'
   ```
   You'll need to confirm overwriting default files like .bashrc with 'y'.
6. After successful deployment, update WireGuard configs on peer machines


- TODO: Set hostname on the VM (currently using IP address)
- TODO: Document how to set up `gh` authentication on the new machine (for CLI operations beyond SSH)
- TODO: Document how to set up `glab` authentication on the new machine (for CLI operations beyond SSH)
- TODO: Handle cronomix config - unclear how it should be managed (rcm symlinks individual files in ~/.config/cronomix, not the directory itself)
- TODO: XDG associations (mimeapps.list) shouldn't be an rcm-managed dotfile - it's already being asserted/managed in ansible
- TODO: Handle Anki installation on Ubuntu 22.04 - newer Anki requires glibc 2.36+ but Ubuntu 22.04 has glibc 2.35. Need to either skip on older systems or find alternative installation method
- TODO (low priority): Consider adding repository setup + package install as an option to the shared Python install implementation, since "add repo & install package" is a common pattern and deb822_repository doesn't reliably trigger apt cache update

## WireGuard

The WireGuard VPN network provides secure connectivity between all managed devices using a hub-and-spoke topology with the VPS as the central hub.

### Network Layout

| Host | IP (10.13.13.x/24) | Description | Notes |
|------|------------|-------------|-------|
| `vps` | .1 | VPS Hub | Accessible at agentydragon.com:51820 |
| `agentydragon` | .11 | ThinkPad X1 Extreme | |
| `gpd` | .12 | GPD Win Max 2 | |
| `atlas` | .30 | Proxmox host | TODO set this up |
| `new-vm` | .31 | New Pop!_OS VM | |
| `pixel6` | .50 | Pixel 6 phone | |
| `homeassistant` | .100 | Home Assistant | Not managed by Ansible |

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

### SyncThing

All devices report ActivityWatch data to the central server on VPS

Open on WireGuard network: <http://10.13.13.1:8384>

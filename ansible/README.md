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

- The `rcup` command asks for confirmation before overwriting existing dotfiles.
  Which we can't give from an Ansible playbook. Which sucks.

## To update requirements

```bash
cd ansible
ansible-galaxy role install -r requirements.yaml
ansible-galaxy collection install -r requirements.yaml
```

These install into the default `~/.ansible/{roles,collections}` paths so
third-party content never lands in `ansible/roles` or `ansible/collections`.

## To deploy

```bash
cd ansible
ansible-playbook agentydragon.yaml --ask-become-pass
ansible-playbook vps.yaml
```

NOTE: running with `--skip-tags` might not work in any reasonable way. I didn't
assign task particularly with that in mind... :/

On GPD: `--skip-tags bazel-remote-cache` -- because I don't have the Bazel
remote cache `htpasswd` on GPD.

## To deploy gpd

```bash
cd ansible
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

- `htpasswd` for `bazel-remote-cache` is not stored in the repo - but that
  should be fine, those creds are cheap to rotate.
  It's expected to be in `$(repo root)/ansible/bazel_remote_cache.htpasswd`.
- Setup steps for Inventree - see <https://docs.inventree.org/en/latest/start/docker_install/#initial-database-setup>
  (making databases etc)

## Manual laptop installation steps

These parts can't be done by Ansible:

- `ssh-keygen`
- Add key to GitHub/GitLab
- `apt install git ansible`
- `git clone git@gitlab.com:agentydragon/ducktape`
- `ansible-playbook agentydragon.yaml --ask-become-pass`
- Add `~/.config/bazelrc.secrets` - see the `bazelrc` dotfile. Global `bazelrc` imports this file, it's supposed to contain the path (and
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
   cd ansible
   ansible-playbook wyrm.yaml --ask-become-pass
   ```

   When prompted for the BECOME password, enter the sudo password for the agentydragon user on the VM.

5. If the playbook fails on dotfiles installation, SSH to the machine and run:

   ```bash
   ssh agentydragon@NEW_MACHINE_IP 'RCRC=~/code/ducktape/dotfiles/rcrc rcup -B new-vm'
   ```

   You'll need to confirm overwriting default files like .bashrc with 'y'.

- TODO: Set hostname on the VM (currently using IP address)
- TODO: Document how to set up `gh` authentication on the new machine (for CLI operations beyond SSH)
- TODO: Document how to set up `glab` authentication on the new machine (for CLI operations beyond SSH)
- TODO: Handle cronomix config - unclear how it should be managed (rcm symlinks individual files in ~/.config/cronomix, not the directory itself)
- TODO: XDG associations (mimeapps.list) shouldn't be an rcm-managed dotfile - the 2 critical associations are now enforced by Nix activation script (home.activation.fixMimeApps), Ansible task may be redundant
- TODO: (low priority): Consider adding repository setup + package install as an option to the shared Python install implementation, since "add repo & install package" is a common pattern and deb822_repository doesn't reliably trigger apt cache update

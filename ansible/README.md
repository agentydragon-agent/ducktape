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

Enables:

* ActivityWatch between laptops and server

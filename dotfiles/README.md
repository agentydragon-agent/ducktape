# dotfiles

Personal dotfiles managed with [rcm](https://github.com/thoughtbot/rcm). Deployment is handled by Ansible.

## Structure

- **Source**: This directory (`dotfiles/`)
- **Deployment**: Via rcm (managed by Ansible role `ansible/roles/cli/tasks/dotfiles.yml`)
- **Configuration**: `rcrc` controls symlink behavior

## Key Symlinked Components

```
~/.config/* -> ducktape/dotfiles/config/*
~/.local/bin/* -> ducktape/dotfiles/local/bin/*
```

**Note:** Progressively migrating to Nix home-manager. See `nix/home/home.nix` and `dotfiles/docs/shell-configuration.md` for current status.

## User Scripts (.local/bin)

Utility scripts symlinked to `~/.local/bin/`:

- Theme switchers (`set_dark_theme`, `set_light_theme`)
- Backup utilities (`duplicity`)
- Git utilities (`git-purge-file`)
- Other (`skype-history`)

## Commands

```bash
lsrc                    # List managed files
mkrc ~/.tigrc           # Add new RC file
rcup -B agentydragon    # Update symlinks
```

## Shell Configuration

Shell configuration follows a specific loading hierarchy. See `docs/shell-configuration.md` for details.

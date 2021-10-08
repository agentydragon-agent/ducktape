## To update requirements

```bash
ansible-galaxy install -r requirements.yaml
```

## To deploy localhost

```bash
ansible-playbook agentydragon.yaml --ask-become-pass
```

## To deploy agentydragon

```bash
ansible-playbook cloudragon.yaml
```

### TODO

Make worthy work, actually.

- zoom (for meetings)
- ubuntu-desktop
- slic3r
- dropbox

TODO: minimize cinnamon desktop, texlive, etc.

## Fresh laptop install

These parts can't be done by Ansible:

1.`ssh-keygen`
1. Add key to GitHub
1. `apt install git ansible`
1. `git clone git@github.com:agentydragon/playbooks`
1. `ansible-playbook agentydragon.yaml --ask-become-pass`

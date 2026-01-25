# Ansible Stubs

This directory contains stub roles for Galaxy dependencies. These stubs allow
`ansible-playbook --syntax-check` to pass without installing actual Galaxy roles.

## Why This Exists

The pre-commit hook runs `ansible-playbook --syntax-check` for fast local feedback.
However, this command validates role dependencies in `meta/main.yml` files.

Galaxy roles are NOT installed in pre-commit to avoid:

- Unreliable Galaxy API (intermittent 500 errors)
- Slow network calls during pre-commit

Full Galaxy roles are installed in CI for comprehensive ansible-lint validation.

## Structure

```
stubs/
  galaxy_roles/           # Stub roles matching requirements.yaml
    petermosmans.customize-gnome/
    geerlingguy.docker/
    ...
```

## Maintenance

When adding a new role to `requirements.yaml`:

1. Create a stub directory: `stubs/galaxy_roles/<role-name>/tasks/main.yml`
2. The stub only needs an empty `tasks/main.yml` with a comment

When removing a role from `requirements.yaml`:

1. Delete the corresponding stub directory

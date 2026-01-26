@README.md

# Agent Checklist (Ansible)

Before handing work back to the user, run pre-commit hooks:

```bash
pre-commit run --all-files
```

This automatically runs `prettier`, `ansible-playbook --syntax-check`, and other checks.

Do not ship un-checked YAML. If any command fails, fix the reported issues first, then rerun until they succeed.

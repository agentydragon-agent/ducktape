# Agent Checklist (Ansible)

Before handing work back to the user, run validation:

```bash
# Primary: Bazel lint for Python files
bazel lint //...

# Ansible-specific checks (yamllint, syntax-check)
pre-commit run yamllint ansible-syntax-check --all-files
```

Do not ship un-checked YAML. If any command fails, fix the reported issues first, then rerun until they succeed.

**Optional**: For a targeted ansible-lint pass on specific files, use:
```bash
python ansible/tools/run_ansible_lint.py
```

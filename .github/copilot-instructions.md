# GitHub Copilot Instructions

This file provides instructions for GitHub Copilot and related AI coding assistants.

For detailed repository guidance, see: [AGENTS.md](../AGENTS.md)

## Pre-commit Hooks (Required)

**Before handing in any work, you MUST ensure pre-commit hooks pass.**

### Setup

Install pre-commit hooks when starting work:

```bash
pre-commit install
```

### Verification

Before completing your work, run the full pre-commit check:

```bash
pre-commit run --all-files
```

All checks must pass before the work is considered complete.

### Ansible-Specific Changes

If you modify any files in `ansible/`, follow the dedicated checklist in [`ansible/AGENTS.md`](../ansible/AGENTS.md):

1. Run yamllint:
   ```bash
   uvx yamllint -c .yamllint.yaml ansible/
   ```

2. Run syntax check for each playbook you touched:
   ```bash
   uvx --from ansible-core ansible-playbook --syntax-check <playbook>.yaml
   ```

3. Finish with the full repo workflow:
   ```bash
   pre-commit run --all-files
   ```

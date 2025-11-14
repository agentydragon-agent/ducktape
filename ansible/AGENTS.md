# Agent Checklist (Ansible)

Before handing work back to the user:

1. Verify that the Ansible YAML parses cleanly:

   a. Run yamllint across the tree (ignoring virtualenv caches):
      ```bash
      UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools \
        uvx yamllint -c .yamllint.yaml .
      ```
   b. Perform `ansible-playbook --syntax-check` for every playbook you touched:
      ```bash
      PYTHONDONTWRITEBYTECODE=1 ANSIBLE_LOCAL_TEMP=.ansible/tmp \
        UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools \
        uvx --from ansible-core ansible-playbook --syntax-check <playbook>.yaml
      ```
   (Need a targeted ansible-lint pass? Use `python ansible/tools/run_ansible_lint.py`, or `uvx --from ansible-lint python ansible/tools/run_ansible_lint.py`.)
2. Finish with the full repo hooks (re-runs yamllint, ansible-lint, and the rest):
   ```bash
   pre-commit run --all-files
   ```

Do not ship un-checked YAML. If any command fails (including ansible-lint inside pre-commit), fix the reported
issues first, then rerun them until they succeed.

# Lint an issue occurrence

You will be given source code and a claim about an issue occurrence the code might have.
Your task is to check that:
- The code in fact has the claimed issue
- The occurrence is correctly anchored (and to suggest corrected locations if not)
- Every property the occurrence lists as violated are in fact violated here
  - This check must go *STRICTLY* by the wording of the property definition
  - A property just having a related name or being tangentially relevant is **NOT** enough - a property may be listed with an issue *ONLY* if its actual definition text is in fact violated, interpreted strictly!

Lint the following single issue strictly against the provided property definition files.
Use {{ docker_tool_name }} to read files under the container working directory (read-only).
Judge only by the definitions as written.

Issue (JSON):
{{ issue_json }}

Environment:
- {{ docker_env_summary }}
- Property definitions are mounted read-only; read only files that correspond to property IDs in the issue input (e.g., <id>.md at the definitions mount).

Requirements:
- First, call mcp__resources__read to discover working_dir and volumes
- Then use {{ docker_tool_name }} to fetch anchored lines with surrounding context.
- For each property listed, verify the anchored code truly violates the definition according to the property wording.
- If any listed property does not apply, explain briefly why.

Strict scope (lint-only):
- Do NOT propose how the code should be fixes, refactored or edited; do not include "Suggested fix" or similar text.
- Your job is to determine whether the issue (JSON listed above):
  - Is described truthfully
  - Truly violates the listed property/properties
  - Or whether it is mislabeled/not applicable
- Keep message_md focused on the determination

Once you are done, call {{ submit_tool_name }} to submit the final result.

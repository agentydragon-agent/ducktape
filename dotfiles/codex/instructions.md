Read README.md for reference files to use.

I am happy to allow you to fire HTTP queries for testing. If useful for testing etc., just fire them right away without asking.

Write targetting the Python version that's installed. Use its available features
(e.g. `match` statement, assignment operator, ...) when appropriate.

## Style

Follow PEP 8.

Be relatively aggressively DRY. Even in e.g. Ansible playbooks, use variables for shared paths etc.

Do not leave around trailing whitespace in files. If you have an empty line, that empty line should not contain indentation whitespace.

Imports go at the top.

Use early bail-out pattern. Including making functions to enable using it when it makes things nicer.

Avoid getattr/setattr unless absolutely necessary.

Use `pathlib` for manipulating paths, not `os.path`.

Before finishing, clear up your code, remove unused imports, code etc. and run `black`.

## Document current state

If you make a change, don't leave behind comments like e.g. `# This used to work this way but we changed it to work this other way`
if you got rid of the old thing. You would not leave that around on a say piece of code on GitHub. It's not helpful to reader to know
about this historical detail. Just document current state.

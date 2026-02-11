#!/bin/sh
set -eu

present=""
missing=""

# Helper: report present if any name exists
have_any() {
  for cmd in "$@"; do
    if which "$cmd" >/dev/null 2>&1; then
      return 0
    fi
  done
  return 1
}

# Tools to check via a simple which-based loop
# Format per line: cmdspec:label
# - cmdspec may contain alternatives separated by '|', e.g. "pyan3|pyan"
TOOLS='
ruff:ruff
rg:ripgrep
pyright:pyright
bandit:bandit
pip-audit:pip-audit
safety:safety
radon:radon
xenon:xenon
pylint:pylint
lizard:lizard
ctags:universal-ctags
jq:jq
jscpd:jscpd
lint-imports:import-linter
pytest:pytest
coverage:coverage
semgrep:semgrep
codespell:codespell
pyupgrade:pyupgrade
refurb:refurb
flynt:flynt
pydocstyle:pydocstyle
interrogate:interrogate
diff-cover:diff-cover
adgn-detectors-custom:adgn-detectors-custom
nl:nl
pyan3|pyan:pyan
'

printf "%s" "$TOOLS" | while IFS=: read -r cmdspec label; do
  [ -z "$cmdspec" ] && continue
  IFS_SAVE="$IFS"; IFS='|'; set -- $cmdspec; IFS="$IFS_SAVE"
  if have_any "$@"; then
    present="$present$label "
  else
    missing="$missing$label "
  fi
done

printf "✓ %s\n" "$present"
printf "✗ %s\n" "$missing"

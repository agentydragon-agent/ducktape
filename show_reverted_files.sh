#!/bin/bash

# Script to show files that were changed between devel and dirty but ended up with same content as devel
# These are files that were modified and then reverted back

set -euo pipefail

# Get files that were changed in commits but ended up with same content as devel
files=$(comm -23 \
  <(git log --name-only --pretty=format: devel..dirty | grep -v '^$' | sort | uniq) \
  <(git diff --name-only devel...dirty | sort))

echo "Files that were changed between devel and dirty but ended up with same content as devel:"
echo "================================================================================="

for file in $files; do
    echo
    echo "================== $file =================="
    echo
    # Show the patch log for this file between the two points
    git --no-pager log -p devel..dirty $@ -- "$file" || {
        echo "Warning: Could not show log for $file (file may have been renamed/deleted)"
    }
done

echo "Done."

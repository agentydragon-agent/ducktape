#!/usr/bin/env bash
set -euo pipefail

# Enable line numbers in Vim and Neovim for interactive sessions.
# Idempotent: safe to run multiple times.

mkdir -p "$HOME/.config/nvim"
printf '%s\n' 'set number' >> "$HOME/.vimrc"
printf '%s\n' 'set number' >> "$HOME/.config/nvim/init.vim"

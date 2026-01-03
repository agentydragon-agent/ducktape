@README.md

# Agent Guide for `dotfiles/`

## Important Rules

- **DO NOT modify dotfiles directly in `~/`** — edit source files here in `dotfiles/`
- **DO NOT modify dotfiles in Ansible steps** — Ansible deploys via rcm, not direct file writes
- Some dotfiles are host-specific (e.g., `host-agentydragon/rcrc`, `host-gpd/rcrc`)

## Shell Configuration

@docs/shell-configuration.md

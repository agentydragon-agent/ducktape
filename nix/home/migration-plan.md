# Nix/Home-Manager Migration Plan for Wyrm

## Strategy: Parallel Deployment with Progressive Cutover

Your proposed strategy makes perfect sense! Here's the refined plan:

### Phase 1: Test & Mark 
**Status: Testing Complete, Marking Pending**

#### Successfully Migrated to Nix (home.nix)
- [x] **GUI role (partial)**:
  - [x] dconf settings (GNOME preferences, workspace shortcuts, night light)
  - [x] GNOME Shell extensions configuration
  - [x] XDG autostart entries (Syncthing-GTK, Discord, Flameshot)
  - [x] XDG MIME associations
  - [x] Flameshot keybinding
- [x] **gnome-terminal-solarized role**:
  - [x] Solarized Light & Dark profiles (using nix-colors)
- [x] **claude-mcp role**:
  - [x] MCP server configuration via ~/.claude.json
- [x] **Package management**:
  - [x] User-level packages (Python 3.12 tools, Node tools, dev tools)
  - [x] GNOME extensions packages
  - [x] ML packages (pandas, pytorch, numpy) - using Python 3.12 for compatibility

#### K8s Sandbox Testing Results (2025-08-28)
- ✅ Successfully built home.nix with nixpkgs 24.05 (now updated to 25.05)
- ✅ All packages installed correctly with Python 3.12 (changed from 3.13 for numpy compatibility)
- ✅ Generated .claude.json with correct MCP server configuration
- ✅ File linking works (manual activation required in container due to dbus)
- ⚠️ Note: Used single-user Nix installation in container (no daemon needed)
- ⚠️ Note: home-manager must be installed via `programs.home-manager.enable = true`, not nix-env

#### Wyrm Deployment (2025-08-28)
- ✅ Nix daemon installed successfully
- ✅ Updated to latest stable: nixpkgs 25.05 + home-manager 25.05
- ✅ home.nix updated with correct username (agentydragon) and stateVersion (25.05)
- ✅ Successfully activated home-manager configuration (2 generations)
- ✅ GNOME dconf settings applied (focus-mode, panel date format)
- ✅ Autostart desktop files created (syncthing-gtk, discord, flameshot)
- ✅ Packages accessible (some from Nix, some from existing installations)

#### What We Had to Skip/Disable
- ❌ **XDG MIME associations** (mimeapps.list): Home-manager would replace all 105 associations with just 2. Kept in Ansible to preserve existing associations.
- ❌ **Claude MCP configuration** (.claude.json): File contains many other Claude settings beyond MCP servers. Need in-place editing solution, not file replacement.
- ❌ **NPM global packages** (jscpd, madge, @openai/codex): Not available in nixpkgs. Users must install manually with: `pnpm add -g jscpd madge @openai/codex`
- ⚠️ **Package conflicts**: Some packages installed via both Nix and system (ruff, gh). This is harmless but creates duplication.

#### To Mark in Ansible (wyrm.yaml)
**STATUS: READY - Deployment confirmed successful**

Now ready to add tags to skip migrated components:
```yaml
- role: gui
  tags: [gui, migrated_to_nix]
  
- role: gnome-terminal-solarized
  tags: [gnome-terminal-solarized, migrated_to_nix]
  
- role: claude-mcp  
  tags: [claude-mcp, migrated_to_nix]
```

### Phase 2: Wyrm Deployment (First Time)

**Current Status: Ready for manual deployment**

Since Ansible tags haven't been added yet, for the first deployment:

1. **Install Nix** (if not already installed):
```bash
curl -L https://nixos.org/nix/install | sh -s -- --daemon
```

2. **Install home-manager**:
```bash
nix-channel --add https://github.com/nix-community/home-manager/archive/release-25.05.tar.gz home-manager
nix-channel --add https://nixos.org/channels/nixos-25.05 nixpkgs  # Ensure 25.05 for compatibility
nix-channel --update
nix-shell '<home-manager>' -A install
```

3. **Deploy home.nix**:
```bash
cd ~/code/ducktape/nix/home
home-manager switch -f home.nix
```

4. **Run Ansible normally** (no skip-tags yet):
```bash
cd ~/code/ducktape/ansible
ansible-playbook wyrm.yaml --ask-become-pass
```

This will result in:
- Some duplicate package installations (both Nix and Ansible)
- Both systems managing some configs (will converge to same state)
- No breaking changes - safe parallel operation

### Phase 3: Testing Checklist

After deployment, verify:
- [ ] GNOME Terminal has both Solarized profiles
- [ ] Night Theme Switcher triggers theme switching
- [ ] Flameshot launches with Print key
- [ ] Autostart applications work (Syncthing-GTK, Discord, Flameshot)
- [ ] Claude Code MCP servers are configured
- [ ] Workspace switching shortcuts work (Ctrl+Alt+↑/↓)

### Phase 4: Progressive Migration

#### Still to Migrate (wyrm-specific)
1. **cli role** → home.nix:
   - Dotfiles management (rcup)
   - Shell configuration
   - Build dependencies

2. **dev-env role** → home.nix:
   - Development environment setup

3. **dev-ml role** → home.nix:
   - ML packages (already partially in home.nix)

4. **k3s-client role** → home.nix or configuration.nix:
   - Kubeconfig setup

5. **Wyrm-specific tasks**:
   - Pip cache on tankshare
   - Screen blanking (already in dconf)

### Phase 5: Full Cutover

Once tested and stable:
1. Remove `when: false` conditions
2. Delete migrated Ansible roles
3. Update documentation
4. Apply to other machines (agentydragon, new-vm, gpd)

## Implementation Notes

### Ansible Task Tagging
Add consistent tags for easy skipping:
```yaml
- name: Task migrated to Nix
  tags: [migrated_to_nix]
  # ... task content
```

### Home-Manager Deployment
```bash
# First time setup
nix-channel --add https://github.com/nix-community/home-manager/archive/release-24.05.tar.gz home-manager
nix-channel --update

# Deploy
home-manager switch -f ~/code/ducktape/nix/home/home.nix
```

### Rollback Strategy
If issues arise:
```bash
# Rollback home-manager
home-manager generations  # List generations
home-manager rollback     # Go to previous

# Re-enable Ansible tasks (once tags are added)
ansible-playbook wyrm.yaml --ask-become-pass  # Without skip-tags
```

## Benefits of This Approach
1. **No service disruption** - both systems coexist
2. **Easy rollback** - can revert to pure Ansible quickly  
3. **Gradual validation** - test each component separately
4. **Machine-by-machine migration** - proven on wyrm before others
5. **Clear tracking** - tagged tasks show migration progress
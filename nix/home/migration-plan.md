# Nix/Home-Manager Migration Plan for Wyrm

## Strategy: Parallel Deployment with Progressive Cutover

Your proposed strategy makes perfect sense! Here's the refined plan:

### Phase 1: Mark & Disable (Current)
**Status: In Progress**

#### Already Migrated to Nix (home.nix)
- [x] **GUI role (partial)**:
  - [x] dconf settings (GNOME preferences, workspace shortcuts, night light)
  - [x] GNOME Shell extensions configuration
  - [x] XDG autostart entries (Syncthing-GTK, Discord, Flameshot)
  - [x] XDG MIME associations
  - [x] Flameshot keybinding
- [x] **gnome-terminal-solarized role**:
  - [x] Solarized Light & Dark profiles (using nix-colors)
- [x] **claude-mcp role**:
  - [x] MCP server configuration
- [x] **Package management**:
  - [x] User-level packages (Python tools, Node tools, dev tools)
  - [x] GNOME extensions packages

#### To Disable in Ansible (wyrm.yaml)
Add `when: false` or tags to skip:
```yaml
- role: gui
  when: false  # Migrated to home.nix
  
# Or use tags:
- role: gui  
  tags: [gui, skip_migrated]
```

### Phase 2: Parallel Deployment Script

Create deployment script:
```bash
#!/usr/bin/env bash
# deploy-wyrm.sh

set -e

echo "=== Deploying Wyrm with Ansible + Nix ==="

# 1. Run Ansible with migrated tasks skipped
echo "Running Ansible (skipping migrated tasks)..."
cd ~/code/ducktape/ansible
ansible-playbook wyrm.yaml --ask-become-pass --skip-tags "gui,gnome-terminal-solarized,claude-mcp"

# 2. Deploy Nix home-manager configuration
echo "Deploying home-manager configuration..."
cd ~/code/ducktape/nix/home
home-manager switch -f home.nix

# 3. Verify critical services
echo "Verifying configuration..."
# Check GNOME extensions are loaded
dconf read /org/gnome/shell/enabled-extensions
# Check terminal profiles exist
dconf list /org/gnome/terminal/legacy/profiles:/

echo "=== Deployment complete ==="
```

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

# Re-enable Ansible tasks
ansible-playbook wyrm.yaml --ask-become-pass  # Without skip-tags
```

## Benefits of This Approach
1. **No service disruption** - both systems coexist
2. **Easy rollback** - can revert to pure Ansible quickly  
3. **Gradual validation** - test each component separately
4. **Machine-by-machine migration** - proven on wyrm before others
5. **Clear tracking** - tagged tasks show migration progress
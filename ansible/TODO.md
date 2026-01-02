# Ansible TODO

## Remote Desktop Infrastructure

**Branch**: `authentik-remote-desktop`
**Status**: Work in Progress - DO NOT MERGE

There is ongoing work to implement a VPS-based remote desktop environment protected by Authentik SSO.

See the `authentik-remote-desktop` branch for:

- Authentik identity provider role
- Plans for browser-based remote desktop
- Tailscale/Headscale-only access configuration

The implementation is incomplete and needs:

- [ ] Remote desktop server selection and setup (Guacamole/Apache Guacamole/etc)
- [ ] Integration between Authentik and remote desktop
- [ ] Desktop environment configuration
- [ ] User provisioning automation
- [ ] Performance optimization over Tailscale/Headscale
- [ ] Security hardening

**DO NOT** uncomment the authentik role in `vps.yaml` until this work is complete.

## Nix/Home-Manager Migration

### Systems Using Home-Manager

- **wyrm** - deployed 2025-08-28
- **atlas** - deployed 2025-08-30
- **agentydragon** - deployed 2025-08-31

### Legacy Systems (without Home-Manager)

- **gpd** - uses `legacy_without_home_manager/*` roles
- **vps** - uses `legacy_without_home_manager/*` roles

### Migration Pattern

Tools migrated to Nix are provided by:

- **Home-manager systems**: Via `nix/home/home.nix`
- **Legacy systems**: Via `roles/legacy_without_home_manager/*` roles

The `legacy_without_home_manager/` roles contain Ansible fallbacks for tools that home-manager provides on migrated systems.

## Other TODOs

- [ ] Update to latest Ansible version
- [ ] Migrate deprecated modules
- [ ] Add molecule tests for roles
- [ ] Document vault variable requirements
- [ ] git-commit-ai: include standard diff scaffolding; show progress with rich or similar
- [ ] Add nix role to wyrm.yaml and agentydragon.yaml for consistency (atlas already has it)

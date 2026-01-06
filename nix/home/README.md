# Nix/Home-Manager User Configuration

This directory contains the Nix/home-manager configuration for user environments, migrating from Ansible-based setup.

## Deployed Systems

- **wyrm** - Primary development machine (Pop!\_OS/Ubuntu) - deployed 2025-08-28
- **atlas** - Proxmox host (Debian) - deployed 2025-08-30
- **agentydragon** - ThinkPad X1 Extreme (Pop!\_OS) - deployed 2025-08-31

## Remaining Systems (not yet migrated to Nix)

- **gpd** - GPD Win Max 2 laptop
- **vps** - VPS server

## Kubernetes Sandbox

A Kubernetes-based sandbox environment is available for testing changes before deployment.

## Setup

```bash
# 1. Create API keys secret (optional, for Claude/OpenAI tools):
kubectl create secret generic api-keys -n nix-sandbox \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"

# 2. Deploy the StatefulSet:
kubectl apply -f statefulset.yaml

# 3. Wait for pod to be ready:
kubectl -n nix-sandbox wait --for=condition=ready pod/nix-sandbox-0

# 3. Shell into the container:
kubectl -n nix-sandbox exec -it nix-sandbox-0 -- bash

# 4. Inside the container, install Nix:
# As ubuntu user (should already be this user)
sh <(curl -L https://nixos.org/nix/install) --no-daemon
source ~/.nix-profile/etc/profile.d/nix.sh

# 5. Install home-manager:
nix-channel --add https://github.com/nix-community/home-manager/archive/master.tar.gz home-manager
nix-channel --update
nix-shell '<home-manager>' -A install
```

## Applying Home Manager Configuration

```bash
# 1. Copy the home.nix config to the container (to the default location):
kubectl -n nix-sandbox exec nix-sandbox-0 -- mkdir -p /home/ubuntu/.config/home-manager
kubectl -n nix-sandbox cp ~/code/ducktape/nix/home/home.nix nix-sandbox-0:/home/ubuntu/.config/home-manager/home.nix

# 2. Apply the configuration:
kubectl -n nix-sandbox exec -it nix-sandbox-0 -- bash
# Switch to ubuntu user if needed
su - ubuntu
# Apply
home-manager switch
# Alternatively, explicit config path:
home-manager -f ~/home.nix switch
```

## Home Manager Commands

```bash
# Preview what would change (build without activating)
home-manager build

# Edit config and immediately apply
home-manager edit  # Opens $EDITOR, then prompts to switch

# List installed packages
home-manager packages
```

### Generation Management

```bash
# List all generations (versions)
home-manager generations

home-manager rollback
home-manager switch --rollback <generation-number>
home-manager expire-generations "-7 days"
```

### Diffing Changes

Nix doesn't have built-in config diff, but you can:

```bash
# See what packages would change
nix-store -q --references $(home-manager build) | sort > /tmp/new-packages
nix-store -q --references ~/.nix-profile | sort > /tmp/old-packages
diff /tmp/old-packages /tmp/new-packages

# Or use nix-diff tool
nix-env -iA nixpkgs.nix-diff
nix-diff $(home-manager generations | head -2)
```

**Key concept**: Each `switch` creates a new immutable "generation" you can rollback to anytime.

## Usage

The pod has two persistent volumes:

- `/nix` - The Nix store (20GB)
- `/home/ubuntu` - User home directory (10GB)

This ensures that Nix packages and user configuration persist across pod restarts.

## Connecting from local machine

You can also port-forward to work with the container:

```bash
# If we add SSH server later
kubectl -n nix-sandbox port-forward nix-sandbox-0 2222:22
```

Or copy files:

```bash
kubectl -n nix-sandbox cp ./my-config nix-sandbox-0:/home/ubuntu/
```

## Cleanup

To remove everything (including the secret):

```bash
kubectl delete -f statefulset.yaml
kubectl delete secret api-keys -n nix-sandbox  # If created
```

This will also delete the namespace, PVCs, and all data. The secret is automatically deleted when the namespace is removed.

# Nix Sandbox for User Configuration Migration

This is a Kubernetes-based sandbox environment for experimenting with migrating user configuration from Ansible to Nix/home-manager.

## Setup

1. Create API keys secret (optional, for Claude/OpenAI tools):
```bash
kubectl create secret generic api-keys -n nix-sandbox \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY"
```

2. Deploy the StatefulSet:
```bash
kubectl apply -f statefulset.yaml
```

2. Wait for pod to be ready:
```bash
kubectl -n nix-sandbox wait --for=condition=ready pod/nix-sandbox-0
```

3. Shell into the container:
```bash
kubectl -n nix-sandbox exec -it nix-sandbox-0 -- bash
```

4. Inside the container, install Nix:
```bash
# As ubuntu user (should already be this user)
sh <(curl -L https://nixos.org/nix/install) --no-daemon
source ~/.nix-profile/etc/profile.d/nix.sh
```

5. Install home-manager:
```bash
nix-channel --add https://github.com/nix-community/home-manager/archive/master.tar.gz home-manager
nix-channel --update
nix-shell '<home-manager>' -A install
```

## Applying Home Manager Configuration

1. Copy the home.nix config to the container (to the default location):
```bash
# First create the directory in the container
kubectl -n nix-sandbox exec nix-sandbox-0 -- mkdir -p /home/ubuntu/.config/home-manager

# Copy the config
kubectl -n nix-sandbox cp ~/code/ducktape/nix/home/home.nix nix-sandbox-0:/home/ubuntu/.config/home-manager/home.nix
```

2. Apply the configuration:
```bash
# Get into the container
kubectl -n nix-sandbox exec -it nix-sandbox-0 -- bash

# Switch to ubuntu user if needed
su - ubuntu

# Apply the home-manager configuration
home-manager switch
```

Alternatively, specify the config path explicitly:
```bash
home-manager -f ~/home.nix switch
```

## Home Manager Commands

### Basic Operations
```bash
# Apply configuration changes
home-manager switch

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

# Rollback to previous generation
home-manager rollback

# Switch to specific generation
home-manager switch --rollback <generation-number>

# Remove old generations
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
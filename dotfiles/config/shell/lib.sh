# Shared between zsh and bash

# Run after changes in ~/.config/environment.d/*.conf to apply them in this shell.
reload-env() {
  # 1. re-run the environment-d generator ⇒ manager picks up new *.conf vars
  systemctl --user daemon-reload # re-runs generators on systemd ≥250

  # 2. pull the manager’s block into *this* shell
  while IFS='=' read -r k v; do
    [ "$k" ] && export "$k=$v"
  done < <(systemctl --user show-environment) # prints the refreshed env
}

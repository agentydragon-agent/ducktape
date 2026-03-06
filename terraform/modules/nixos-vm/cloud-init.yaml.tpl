#cloud-config
# Minimal bootstrap for NixOS VMs
# After first boot, configuration is managed via flake at:
#   github:agentydragon/ducktape?dir=nix/nixos&ref=devel#${nixos_host}

hostname: ${hostname}

users:
  - name: ${username}
    gecos: ${username}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, wheel
    shell: /run/current-system/sw/bin/bash
%{ if ssh_public_key != "" ~}
    ssh_authorized_keys:
      - ${ssh_public_key}
%{ endif ~}
    lock_passwd: true

package_update: false
package_upgrade: false

%{ if k8s_cluster_join != null ~}
write_files:
  # Kubernetes cluster CA certificate
  - path: /etc/kubernetes/pki/ca.crt
    owner: root:root
    permissions: '0644'
    content: |
      ${indent(6, k8s_cluster_join.ca_cert)}

  # Bootstrap kubeconfig for kubelet TLS bootstrap
  # Server URL is https://localhost:7445 — HAProxy proxies to api.allegedly.works:6443
  - path: /etc/kubernetes/bootstrap-kubelet.conf
    owner: root:root
    permissions: '0600'
    content: |
      ${indent(6, k8s_cluster_join.bootstrap_kubeconfig)}

  # kubespand configuration (KubeSpan mesh credentials)
  - path: /etc/kubespan/agent.yaml
    owner: root:root
    permissions: '0600'
    content: |
      cluster:
        id: "${k8s_cluster_join.cluster_id}"
        secret: "${k8s_cluster_join.cluster_secret}"
      kubernetes:
        advertise_networks: true
        kubeconfig_path: "/var/lib/kubelet/kubelet.conf"
        node_name: "${k8s_cluster_join.node_name}"
        service_cidrs:
          - "10.96.0.0/12"
%{ endif ~}

runcmd:
  # Step 1: Generate hardware configuration
  - /run/current-system/sw/bin/nixos-generate-config --show-hardware-config > /etc/nixos/hardware-configuration.nix

  # Step 2: Initial NixOS rebuild from flake (runcmd runs as root, no sudo needed)
  # --impure allows the flake to import /etc/nixos/hardware-configuration.nix
  # --no-write-lock-file since we're pulling from GitHub and can't write back
  # Uses 'boot' instead of 'switch' because:
  # 1. The cloud image is a minimal bootstrap, new config may have incompatible services
  # 2. A clean reboot ensures the new system starts properly
  # 3. Network config changes (e.g., NetworkManager vs systemd-networkd) need reboot
  - |
    echo "Applying NixOS configuration from flake..."
    /run/current-system/sw/bin/nixos-rebuild boot --flake '${nixos_flake_url}#${nixos_host}' --impure --no-write-lock-file --install-bootloader 2>&1 | tee /var/log/nixos-rebuild.log || echo "nixos-rebuild failed, check /var/log/nixos-rebuild.log"

  # Step 3: Reboot into the new NixOS configuration
  # The NixOS config includes home-manager-init service that runs once on first boot
  - |
    echo "Rebooting into new NixOS configuration..."
    echo "Home-manager will be set up automatically after reboot."
    /run/current-system/sw/bin/systemctl reboot

final_message: "NixOS VM '${hostname}' bootstrapped. Rebooting to apply full configuration."

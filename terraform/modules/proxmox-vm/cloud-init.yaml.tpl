#cloud-config
# Secrets injection for pre-built NixOS VM images.
# The NixOS config and home-manager are baked into the qcow2 image.
# This cloud-init only writes credential files needed at runtime.

%{ if k8s_cluster_join != null ~}
write_files:
  # Kubernetes cluster CA certificate
  - path: /etc/kubernetes/pki/ca.crt
    owner: root:root
    permissions: '0644'
    content: |
      ${indent(6, k8s_cluster_join.ca_cert)}

  # Bootstrap kubeconfig for kubelet TLS bootstrap
  - path: /etc/kubernetes/bootstrap-kubelet.conf
    owner: root:root
    permissions: '0600'
    content: |
      ${indent(6, k8s_cluster_join.bootstrap_kubeconfig)}

  # Nebula mesh credentials
  - path: /etc/nebula/config.yaml
    owner: root:root
    permissions: '0600'
    content: |
      ${indent(6, k8s_cluster_join.nebula_config)}

  - path: /etc/nebula/ca.crt
    owner: root:root
    permissions: '0644'
    content: |
      ${indent(6, k8s_cluster_join.nebula_ca_cert)}

  - path: /etc/nebula/host.crt
    owner: root:root
    permissions: '0644'
    content: |
      ${indent(6, k8s_cluster_join.nebula_host_cert)}

  - path: /etc/nebula/host.key
    owner: root:root
    permissions: '0600'
    content: |
      ${indent(6, k8s_cluster_join.nebula_host_key)}
%{ endif ~}

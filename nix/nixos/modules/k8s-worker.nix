# Kubernetes worker node module
# Joins a NixOS machine as a worker to an external (Talos) K8s cluster
# via KubeSpan (WireGuard mesh).
#
# Does NOT use services.kubernetes — it's designed as a self-contained cluster
# provisioner, not for joining external clusters. Specifically:
#   - Custom CFSSL-based PKI (no --bootstrap-kubeconfig support)
#   - Forces flannel as CNI and wipes /opt/cni/bin on every kubelet start
#   - Deploys its own CoreDNS addon (conflicts with existing cluster DNS)
#   - Kubelet unit depends on local kube-apiserver.service
#   - Builds/seeds a custom pause container instead of registry.k8s.io/pause
#
# Credential placement:
#   Cloud-init (via terraform/modules/proxmox-vm) writes bootstrap kubeconfig, CA cert,
#   and kubespand config. Services auto-start on boot.
#
# Manual step after boot:
#   Approve the CSR on the cluster:
#     kubectl get csr
#     kubectl certificate approve <csr-name>
{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.ducktape.k8sWorker;

  kubeletDeps = with pkgs; [
    kubernetes
    iptables
    socat
    conntrack-tools
    util-linux
    nftables
    wireguard-tools
    tcpdump
    iproute2
    openiscsi # Longhorn requires iscsiadm on the host
  ];

  kubeletConfigYaml = pkgs.writeText "kubelet-config.yaml" (
    builtins.toJSON {
      kind = "KubeletConfiguration";
      apiVersion = "kubelet.config.k8s.io/v1beta1";
      authentication = {
        anonymous.enabled = false;
        webhook.enabled = true;
        x509.clientCAFile = cfg.caCertPath;
      };
      authorization.mode = "Webhook";
      clusterDomain = "cluster.local";
      clusterDNS = [ cfg.clusterDNS ];
      cgroupDriver = "systemd";
      containerRuntimeEndpoint = "unix:///run/containerd/containerd.sock";
      serverTLSBootstrap = true;
      tlsMinVersion = "VersionTLS12";
      # Some nodes (e.g. laptops) have swap enabled; don't fail on it.
      failSwapOn = false;
    }
  );

  # Use the host's real IPv4 (from default route) as kubelet node IP.
  # NOT the KubeSpan IPv6 ULA — using that causes Cilium to detect the
  # kubespan interface (IPv6-only) as the direct routing device, which
  # fails with "IPv4 direct routing device IP not found" since Cilium
  # needs IPv4 for VXLAN tunnel mode.
  resolveNodeIp = pkgs.writeShellScript "resolve-kubespan-ip" ''
    ${pkgs.iproute2}/bin/ip -4 route get 1.1.1.1 \
      | ${pkgs.gnugrep}/bin/grep -oP 'src \K\S+' > /run/kubelet-node-ip
    if [ ! -s /run/kubelet-node-ip ]; then
      echo "Failed to read host IPv4 from default route" >&2
      exit 1
    fi
  '';
in
{
  imports = [ ./kubespand.nix ];

  options.ducktape.k8sWorker = {
    enable = lib.mkEnableOption "Kubernetes worker node (joins external Talos cluster via KubeSpan)";

    clusterDNS = lib.mkOption {
      type = lib.types.str;
      default = "10.96.0.10";
      description = "Cluster DNS service IP";
    };

    caCertPath = lib.mkOption {
      type = lib.types.str;
      default = "/etc/kubernetes/pki/ca.crt";
      description = "Path to the cluster CA certificate (placed manually)";
    };

    nodeLabels = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = {
        "topology.kubernetes.io/region" = "roaming";
        "node.kubernetes.io/role" = "roaming";
      };
      description = "Labels to apply to the node on registration";
    };

    nodeTaints = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      # Example for roaming/laptop nodes:
      # [ "node-role.kubernetes.io/roaming=true:NoSchedule" ]
      description = "Taints to apply on registration (key=value:effect format)";
    };

    enableNvidiaRuntime = lib.mkEnableOption "NVIDIA GPU support via CDI (Container Device Interface)";

  };

  config = lib.mkIf cfg.enable {
    # iSCSI — required by Longhorn (iscsiadm on host)
    services.openiscsi = {
      enable = true;
      name = "iqn.2020-08.org.nixos:${config.networking.hostName}";
    };

    # Kernel prerequisites for container networking
    boot.kernelModules = [
      "overlay"
      "br_netfilter"
    ];
    boot.kernel.sysctl = {
      "net.bridge.bridge-nf-call-iptables" = 1;
      "net.bridge.bridge-nf-call-ip6tables" = 1;
      "net.ipv4.ip_forward" = 1;
      # Disable reverse path filtering for KubeSpan. Packets decrypted by
      # WireGuard arrive on kubespan with source IPs whose reverse path goes
      # through ens18 (e.g., VPS public IPs). Both the kernel sysctl rpfilter
      # and iptables rpfilter module must be disabled/loosened independently.
      # default.rp_filter controls new interfaces (kubespan is created at
      # runtime by kubespand); all.rp_filter is max'd with per-interface value.
      "net.ipv4.conf.default.rp_filter" = 0;
      "net.ipv4.conf.all.rp_filter" = 0;
    };

    # Loose iptables rpfilter for the same reason as above — the iptables
    # rpfilter module is a separate check from the kernel sysctl.
    networking.firewall.checkReversePath = "loose";

    # Containerd
    virtualisation.containerd = {
      enable = true;
      settings = {
        version = 2;
        plugins."io.containerd.grpc.v1.cri" = {
          sandbox_image = "registry.k8s.io/pause:3.10";
          containerd.default_runtime_name = "runc";
          containerd.runtimes.runc = {
            runtime_type = "io.containerd.runc.v2";
            options.SystemdCgroup = true;
          };
          # NVIDIA runtime for GPU workloads. Uses CDI specs generated by
          # hardware.nvidia-container-toolkit to inject /dev/nvidia*, driver
          # libs, and glibc into containers. The device plugin DaemonSet uses
          # this runtime (via RuntimeClass) so NVML can discover GPUs.
          containerd.runtimes.nvidia = lib.mkIf cfg.enableNvidiaRuntime {
            runtime_type = "io.containerd.runc.v2";
            options = {
              BinaryName = "${pkgs.nvidia-container-toolkit.tools}/bin/nvidia-container-runtime.cdi";
              SystemdCgroup = true;
            };
          };
          enable_cdi = lib.mkIf cfg.enableNvidiaRuntime true;
          cdi_spec_dirs = lib.mkIf cfg.enableNvidiaRuntime [
            "/etc/cdi"
            "/var/run/cdi"
          ];
          # Cilium DaemonSet installs cilium-cni to /opt/cni/bin.
          # We symlink base CNI plugins there too (see systemd.tmpfiles below).
          cni.bin_dir = "/opt/cni/bin";
          cni.conf_dir = "/etc/cni/net.d";
        };
      };
    };

    # Ensure CDI specs are generated before containerd starts
    systemd.services.containerd = lib.mkIf cfg.enableNvidiaRuntime {
      after = [ "nvidia-container-toolkit-cdi-generator.service" ];
      wants = [ "nvidia-container-toolkit-cdi-generator.service" ];
    };

    # Cilium DaemonSet installs cilium-cni + loopback into /opt/cni/bin at runtime.
    # We just need the directory to exist.
    systemd.tmpfiles.rules = [ "d /opt/cni/bin 0755 root root -" ];

    environment.systemPackages = kubeletDeps;

    # Kubelet config file
    environment.etc."kubernetes/kubelet-config.yaml".source = kubeletConfigYaml;

    # Kubelet systemd service
    systemd.services.kubelet = {
      description = "Kubernetes Kubelet";
      after = [
        "network-online.target"
        "containerd.service"
        "kubespand.service"
      ];
      wants = [
        "network-online.target"
        "containerd.service"
      ];
      # Hard dependency — kubelet stops if kubespand dies
      requires = [ "kubespand.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        # Prepend /run/wrappers/bin for NixOS setuid mount/umount wrappers.
        Environment = "PATH=/run/wrappers/bin:${lib.makeBinPath kubeletDeps}:/usr/bin:/bin";
        ExecStartPre = resolveNodeIp;
        ExecStart = pkgs.writeShellScript "kubelet-start" ''
          NODE_IP=$(</run/kubelet-node-ip)
          exec ${pkgs.kubernetes}/bin/kubelet \
            --bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf \
            --kubeconfig=/var/lib/kubelet/kubelet.conf \
            --config=/etc/kubernetes/kubelet-config.yaml \
            --node-ip="$NODE_IP" \
            ${
              lib.optionalString (cfg.nodeLabels != { })
                "--node-labels=${lib.concatStringsSep "," (lib.mapAttrsToList (k: v: "${k}=${v}") cfg.nodeLabels)}"
            } \
            ${lib.optionalString (
              cfg.nodeTaints != [ ]
            ) "--register-with-taints=${lib.concatStringsSep "," cfg.nodeTaints}"}
        '';
        Restart = "always";
        RestartSec = "10";
      };
    };

    # KubeSpan mesh (includes KubePrism: localhost:7445 → discovered CP endpoints)
    ducktape.kubespand.enable = true;

    # Firewall: allow VXLAN (Cilium) and kubelet
    networking.firewall.allowedUDPPorts = [
      8472 # VXLAN (Cilium overlay)
    ];
    networking.firewall.allowedTCPPorts = [
      10250 # kubelet API
    ];
  };
}

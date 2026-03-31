# Kubernetes worker node module
# Joins a NixOS machine as a worker to an external (Talos) K8s cluster
# via Nebula mesh overlay.
#
# Does NOT use services.kubernetes — it's designed as a self-contained cluster
# provisioner, not for joining external clusters. Specifically:
#   - Custom CFSSL-based PKI (no --bootstrap-kubeconfig support)
#   - Forces flannel as CNI and wipes /opt/cni/bin on every kubelet start
#   - Deploys its own CoreDNS addon (conflicts with existing cluster DNS)
#   - Kubelet unit depends on local kube-apiserver.service
#   - Builds/seeds a custom pause container instead of registry.k8s.io/pause
#
# API server access: haproxy on 127.0.0.1:7445 load-balances across all control
# plane Nebula IPs with TCP health checks (replaces kubeprism).
#
# Credential placement: sops-nix decrypts CA cert + bootstrap token at activation
# time. The module generates the bootstrap kubeconfig from these components with
# the local haproxy as the server endpoint.
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
      # Graceful node shutdown: kubelet listens for systemd's PrepareForShutdown
      # DBus signal, sets the node NotReady, and terminates pods in priority order
      # before releasing the inhibitor lock. Without this, Longhorn engine pods
      # get killed during shutdown, iSCSI targets vanish, and mounted volumes hit
      # I/O errors and EXT4 journal corruption.
      shutdownGracePeriod = "60s";
      shutdownGracePeriodCriticalPods = "15s";
      # Some nodes (e.g. laptops) have swap enabled; don't fail on it.
      failSwapOn = false;
      # Default is 110; wyrm2 runs 113+ pods with harbor/inventree/ollama/monitoring.
      maxPods = 300;
      # NixOS uses systemd-resolved in stub mode, so /etc/resolv.conf has
      # nameserver 127.0.0.53. Point kubelet at the real upstream resolv.conf
      # so all pods (including dnsPolicy:Default like CoreDNS) get real
      # upstreams instead of the stub. See debug/coredns-loop-nixos.md.
      resolvConf = "/run/systemd/resolve/resolv.conf";
    }
  );

  # Resolve kubelet node IP from the Nebula mesh interface.
  # TODO: Consider a more robust approach — e.g. a nodeIP option with subnet
  # matching (like Talos's validSubnets), or reading the IP from the Nebula cert.
  # Currently we just grab whatever IPv4 is on nebula1.
  resolveNodeIp = pkgs.writeShellScript "resolve-node-ip" ''
    ${pkgs.iproute2}/bin/ip -4 addr show nebula1 \
      | ${pkgs.gnugrep}/bin/grep -oP 'inet \K[^/]+' > /run/kubelet-node-ip
    if [ ! -s /run/kubelet-node-ip ]; then
      echo "Failed to read IPv4 from nebula1 interface" >&2
      exit 1
    fi
  '';

  # Generate bootstrap kubeconfig from components (CA cert + token + local haproxy).
  # Runs as ExecStartPre because sops secrets are only available at runtime.
  # Bootstrap kubeconfig template — everything except the token (runtime secret).
  # builtins.toJSON produces valid YAML (JSON is a YAML subset).
  bootstrapKubeconfigTemplate = pkgs.writeText "bootstrap-kubeconfig-template.json" (
    builtins.toJSON {
      apiVersion = "v1";
      kind = "Config";
      clusters = [
        {
          cluster = {
            certificate-authority = cfg.caCertPath;
            server = "https://127.0.0.1:7445";
          };
          name = "default";
        }
      ];
      contexts = [
        {
          context = {
            cluster = "default";
            user = "kubelet-bootstrap";
          };
          name = "default";
        }
      ];
      current-context = "default";
      users = [
        {
          name = "kubelet-bootstrap";
          user = {
            token = "__BOOTSTRAP_TOKEN__";
          };
        }
      ];
    }
  );

  # Substitute the sops-decrypted token into the template at runtime.
  generateBootstrapKubeconfig = pkgs.writeShellScript "generate-bootstrap-kubeconfig" ''
    TOKEN=$(<"${cfg.bootstrapTokenPath}")
    ${pkgs.gnused}/bin/sed "s/__BOOTSTRAP_TOKEN__/$TOKEN/" \
      ${bootstrapKubeconfigTemplate} > /run/kubelet-bootstrap-kubeconfig
    ${pkgs.coreutils}/bin/chmod 600 /run/kubelet-bootstrap-kubeconfig
  '';

  haproxyServerLines = lib.concatStringsSep "\n    " (
    lib.imap1 (
      i: ep: "server cp-${toString i} ${ep} check inter 5s fall 3 rise 2"
    ) cfg.controlPlaneEndpoints
  );
in
{
  imports = [ ./nebula-mesh.nix ];

  options.ducktape.k8sWorker = {
    enable = lib.mkEnableOption "Kubernetes worker node (joins external Talos cluster via Nebula mesh)";

    clusterDNS = lib.mkOption {
      type = lib.types.str;
      default = "10.96.0.10";
      description = "Cluster DNS service IP";
    };

    caCertPath = lib.mkOption {
      type = lib.types.str;
      default = "/etc/kubernetes/pki/ca.crt";
      description = "Path to the cluster CA certificate";
    };

    bootstrapTokenPath = lib.mkOption {
      type = lib.types.str;
      description = "Path to the bootstrap token file (sops secret). The module generates the kubeconfig.";
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

    # TODO: Enable on wyrm2 and verify CSI volumes still attach correctly.
    #   Test: enable, reboot, check pods schedule, CSI volumes mount,
    #   `wc -l /proc/self/mountinfo` drops, gvfs-udisks2-volume-monitor
    #   CPU drops to ~0%. If a CSI driver uses MountPropagation:Bidirectional
    #   to create host-visible mounts (not just block devices), this will break.
    isolateMountNamespace = lib.mkEnableOption ''
      mount namespace isolation for kubelet/containerd.
      Runs containerd in a slave mount namespace and has kubelet join it,
      so container overlay/snapshot/shm/netns mounts don't appear in the
      host's /proc/self/mountinfo. Fixes gvfs-udisks2-volume-monitor
      burning CPU on desktop workers by eliminating mount event churn.
      Host mounts (iSCSI devices, etc.) still propagate into the namespace.
    '';

    controlPlaneEndpoints = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [
        "10.42.0.1:6443" # talos-vps-cp-0
        "10.42.0.2:6443" # talos-vps-cp-1
        "10.42.0.10:6443" # talos-pve-cp-0
      ];
      description = "Control plane API server endpoints (IP:port) for the local haproxy load balancer";
    };

  };

  config = lib.mkIf cfg.enable {
    # Hide Longhorn iSCSI CSI volumes from UDisks2 so it doesn't offer
    # to manage them. Note: this alone does NOT fix the
    # gvfs-udisks2-volume-monitor CPU burn (~18% on wyrm2). The real
    # cause is GVFS polling /proc/self/mountinfo on every mount event,
    # which is huge on k8s workers (hundreds of containerd overlays).
    # GVFS has no path-based filter for mountinfo. To fix the CPU burn,
    # mask the monitor: systemctl --user mask gvfs-udisks2-volume-monitor
    services.udev.extraRules = ''
      SUBSYSTEM=="block", ENV{ID_VENDOR}=="IET", ENV{ID_MODEL}=="VIRTUAL-DISK", ENV{UDISKS_IGNORE}="1"
    '';

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
      # Disable reverse path filtering. Cilium manages its own source
      # validation; kernel rp_filter breaks pod-to-node hairpin traffic
      # (e.g., hubble-relay → hubble-peer via ClusterIP routed to local
      # node). The kernel uses max(all, interface) semantics, so per-
      # interface values of 2 override all=0. The wildcard overrides
      # systemd's 50-default.conf which sets conf.*.rp_filter = 2.
      # See: https://docs.cilium.io/en/stable/operations/system_requirements/
      #      https://github.com/cilium/cilium/issues/31565
      "net.ipv4.conf.default.rp_filter" = 0;
      "net.ipv4.conf.all.rp_filter" = 0;
      "net.ipv4.conf.*.rp_filter" = 0;
    };

    # Disable iptables rpfilter (nixos-fw-rpfilter chain in mangle/
    # PREROUTING). nebula-mesh.nix sets "loose", but even loose rpfilter
    # drops pod-to-node hairpin traffic. Talos has no iptables rpfilter.
    # See: https://github.com/NixOS/nixpkgs/issues/298165
    networking.firewall.checkReversePath = lib.mkForce false;

    # Containerd
    # CLEANUP(2026-03-23): Remove override once nixpkgs bumps containerd to ≥2.2.2.
    #   containerd 2.2.1 (current in nixos-25.11) is built with Go 1.24, which
    #   introduced a stricter os.Root API that rejects absolute symlinks inside
    #   container image layers. NixOS-based images (e.g., ghcr.io/zhaofengli/attic)
    #   use absolute symlinks for /etc/passwd → /nix/store/..., causing
    #   "CreateContainerError: path escapes from parent". Fixed in containerd 2.2.2
    #   via PR #12732.
    nixpkgs.overlays = [
      (final: prev: {
        containerd = prev.containerd.overrideAttrs (old: rec {
          version = "2.2.2";
          src = final.fetchFromGitHub {
            owner = "containerd";
            repo = "containerd";
            rev = "v${version}";
            hash = "sha256-1jYiyNHR1sXBwXdS33KWE+IB1tOZbiJyUxhsVeXwSrc=";
          };
        });
      })
    ];

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
    systemd.services.containerd = lib.mkMerge [
      (lib.mkIf cfg.enableNvidiaRuntime {
        after = [ "nvidia-container-toolkit-cdi-generator.service" ];
        wants = [ "nvidia-container-toolkit-cdi-generator.service" ];
      })
      (lib.mkIf cfg.isolateMountNamespace {
        serviceConfig.MountFlags = "slave";
      })
    ];

    # Cilium DaemonSet installs cilium-cni + loopback into /opt/cni/bin at runtime.
    # We just need the directory to exist.
    systemd.tmpfiles.rules = [ "d /opt/cni/bin 0755 root root -" ];

    environment.systemPackages = kubeletDeps;

    # Kubelet config file
    environment.etc."kubernetes/kubelet-config.yaml".source = kubeletConfigYaml;

    # haproxy TCP proxy for kube-apiserver HA (replaces kubeprism).
    # Load-balances across all control plane Nebula IPs with health checks.
    services.haproxy = {
      enable = true;
      config = ''
        global
          maxconn 1024

        defaults
          mode tcp
          timeout connect 5s
          timeout client 30s
          timeout server 30s
          retries 3

        frontend kube-apiserver
          bind 127.0.0.1:7445
          default_backend kube-apiserver

        backend kube-apiserver
          option tcp-check
          balance roundrobin
          ${haproxyServerLines}
      '';
    };

    # haproxy needs Nebula up to reach CP nodes
    systemd.services.haproxy = {
      after = [ "nebula.service" ];
      requires = [ "nebula.service" ];
    };

    # Kubelet systemd service
    systemd.services.kubelet = {
      description = "Kubernetes Kubelet";
      # Restart kubelet when its config file changes. kubelet reads --config
      # only at startup; a nixos-rebuild switch that changes the config won't
      # take effect until kubelet restarts.
      restartTriggers = [ kubeletConfigYaml ];
      after = [
        "network-online.target"
        "containerd.service"
        "nebula.service"
        "haproxy.service"
      ];
      wants = [
        "network-online.target"
        "containerd.service"
      ];
      # Hard dependencies — kubelet stops if mesh or API proxy dies
      requires = [
        "nebula.service"
        "haproxy.service"
      ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        # Prepend /run/wrappers/bin for NixOS setuid mount/umount wrappers.
        Environment = "PATH=/run/wrappers/bin:${lib.makeBinPath kubeletDeps}:/usr/bin:/bin";
        ExecStartPre = [
          resolveNodeIp
          generateBootstrapKubeconfig
        ];
        ExecStart = pkgs.writeShellScript "kubelet-start" ''
          NODE_IP=$(</run/kubelet-node-ip)
          exec ${pkgs.kubernetes}/bin/kubelet \
            --bootstrap-kubeconfig=/run/kubelet-bootstrap-kubeconfig \
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
      }
      // lib.optionalAttrs cfg.isolateMountNamespace {
        JoinsNamespacesOf = "containerd.service";
      };
    };

    # Nebula mesh overlay (inter-node connectivity)
    ducktape.nebulaMesh.enable = true;

    # Firewall: allow VXLAN (Cilium) and kubelet
    networking.firewall.allowedUDPPorts = [
      8472 # VXLAN (Cilium overlay)
    ];
    networking.firewall.allowedTCPPorts = [
      10250 # kubelet API
    ];
    # Trust cluster-internal interfaces. Without this, the NixOS firewall
    # drops inter-node and pod-to-node traffic to ports not explicitly
    # opened (hubble-peer 4244, cilium health 4240, etc.). Talos has no
    # host firewall. nebula1 carries all inter-node cluster traffic;
    # cilium_host and lxc* carry pod-to-node traffic (lxc* are Cilium's
    # per-pod veth interfaces on the host side).
    # See: https://github.com/cilium/cilium/issues/31565
    #      https://github.com/NixOS/nixpkgs/issues/437920
    networking.firewall.trustedInterfaces = [
      "nebula1"
      "cilium_host"
      "lxc+"
    ];
  };
}

# Kubernetes worker node module
# Joins a NixOS machine as a worker to an external (Talos) K8s cluster.
# Does NOT use services.kubernetes (too opinionated toward all-NixOS clusters).
#
# Manual steps after boot:
# 1. Extract bootstrap kubeconfig from Talos control plane:
#      talosctl -n <cp-ip> cat /etc/kubernetes/bootstrap-kubeconfig > bootstrap-kubelet.conf
#      talosctl -n <cp-ip> cat /etc/kubernetes/pki/ca.crt > ca.crt
#      sed -i 's|https://localhost:7445|https://<cp-ip>:6443|g' bootstrap-kubelet.conf
# 2. Copy to this machine:
#      sudo mkdir -p /etc/kubernetes/pki
#      sudo cp ca.crt /etc/kubernetes/pki/
#      sudo cp bootstrap-kubelet.conf /etc/kubernetes/
# 3. Register with Headscale:
#      sudo tailscale up --login-server=https://headscale.allegedly.works
# 4. Start kubelet:
#      sudo systemctl start kubelet
# 5. Approve the CSR on the cluster:
#      kubectl get csr
#      kubectl certificate approve <csr-name>
{
  config,
  pkgs,
  lib,
  ...
}:
let
  cfg = config.ducktape.k8sWorker;

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
    }
  );

  haproxyConfig = lib.concatStringsSep "\n" (
    [
      "global"
      "  maxconn 256"
      ""
      "defaults"
      "  mode tcp"
      "  timeout connect 5s"
      "  timeout client 30s"
      "  timeout server 30s"
      "  retries 3"
      ""
      "frontend kube-apiserver-local"
      "  bind 127.0.0.1:7445"
      "  default_backend kube-apiserver"
      ""
      "backend kube-apiserver"
      "  option tcp-check"
      "  balance roundrobin"
    ]
    ++ lib.imap0 (
      i: ep: "  server cp-${toString i} ${ep} check inter 5s fall 3 rise 2"
    ) cfg.controlPlaneEndpoints
  );
in
{
  options.ducktape.k8sWorker = {
    enable = lib.mkEnableOption "Kubernetes worker node (joins external Talos cluster)";

    controlPlaneEndpoints = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      description = "Control plane endpoints as ip:port strings for HAProxy backends";
      example = [
        "203.0.113.10:6443"
        "203.0.113.11:6443"
      ];
    };

    clusterDNS = lib.mkOption {
      type = lib.types.str;
      default = "10.96.0.10";
      description = "Cluster DNS service IP";
    };

    headscaleUrl = lib.mkOption {
      type = lib.types.str;
      default = "https://headscale.allegedly.works";
      description = "Headscale control server URL for Tailscale";
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
      default = [ "node-role.kubernetes.io/roaming=true:NoSchedule" ];
      description = "Taints to apply on registration (key=value:effect format)";
    };
  };

  config = lib.mkIf cfg.enable {
    # Kernel prerequisites for container networking
    boot.kernelModules = [
      "overlay"
      "br_netfilter"
    ];
    boot.kernel.sysctl = {
      "net.bridge.bridge-nf-call-iptables" = 1;
      "net.bridge.bridge-nf-call-ip6tables" = 1;
      "net.ipv4.ip_forward" = 1;
    };

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
          # Cilium DaemonSet installs cilium-cni to /opt/cni/bin.
          # We symlink base CNI plugins there too (see systemd.tmpfiles below).
          cni.bin_dir = "/opt/cni/bin";
          cni.conf_dir = "/etc/cni/net.d";
        };
      };
    };

    # Cilium DaemonSet installs cilium-cni + loopback into /opt/cni/bin at runtime.
    # We just need the directory to exist.
    systemd.tmpfiles.rules = [ "d /opt/cni/bin 0755 root root -" ];

    environment.systemPackages = with pkgs; [
      kubernetes # for kubelet, kubectl
      iptables
      socat
      conntrack-tools
    ];

    # Kubelet config file
    environment.etc."kubernetes/kubelet-config.yaml".source = kubeletConfigYaml;

    # Kubelet systemd service
    systemd.services.kubelet = {
      description = "Kubernetes Kubelet";
      after = [
        "network-online.target"
        "containerd.service"
        "haproxy.service"
      ];
      wants = [
        "network-online.target"
        "containerd.service"
      ];
      # Don't start automatically — wait for manual credential placement
      wantedBy = [ ];
      path = with pkgs; [
        kubernetes
        iptables
        socat
        conntrack-tools
        util-linux
      ];
      serviceConfig = {
        # NixOS mount wrappers live at /run/wrappers/bin (setuid mount/umount).
        # Kubelet needs mount(8) to set up projected/tmpfs volumes.
        Environment = "PATH=/run/wrappers/bin:${
          lib.makeBinPath (
            with pkgs;
            [
              kubernetes
              iptables
              socat
              conntrack-tools
              util-linux
            ]
          )
        }:/usr/bin:/bin";
        ExecStart = lib.concatStringsSep " " (
          [
            "${pkgs.kubernetes}/bin/kubelet"
            "--bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf"
            "--kubeconfig=/var/lib/kubelet/kubelet.conf"
            "--config=/etc/kubernetes/kubelet-config.yaml"
            "--container-runtime-endpoint=unix:///run/containerd/containerd.sock"
          ]
          ++ lib.optional (cfg.nodeLabels != { }) (
            "--node-labels=${lib.concatStringsSep "," (lib.mapAttrsToList (k: v: "${k}=${v}") cfg.nodeLabels)}"
          )
          ++ lib.optional (cfg.nodeTaints != [ ]) (
            "--register-with-taints=${lib.concatStringsSep "," cfg.nodeTaints}"
          )
        );
        Restart = "always";
        RestartSec = "10";
      };
    };

    # HAProxy — replaces KubePrism (localhost:7445 → control plane)
    # Cilium agent expects k8sServiceHost=localhost, k8sServicePort=7445
    services.haproxy = {
      enable = true;
      config = haproxyConfig;
    };

    # Tailscale for Headscale mesh connectivity
    services.tailscale = {
      enable = true;
      extraUpFlags = [
        "--login-server=${cfg.headscaleUrl}"
        "--accept-routes=true"
      ];
      openFirewall = true;
    };

    # Firewall: allow VXLAN (Cilium) and kubelet
    networking.firewall.allowedUDPPorts = [
      8472 # VXLAN (Cilium overlay)
    ];
    networking.firewall.allowedTCPPorts = [
      10250 # kubelet API
    ];
  };
}

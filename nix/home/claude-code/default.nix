{
  config,
  pkgs,
  lib,
  ...
}: let
  # Helper to generate Bash permission strings from command names
  # Exact match (no wildcard)
  mkBashPerms = cmds: map (cmd: "Bash(${cmd})") cmds;
  mkBashPermsSudo = cmds: map (cmd: "Bash(sudo ${cmd})") cmds;
  # Prefix match (with :* wildcard)
  mkBashPermsWildcard = cmds: map (cmd: "Bash(${cmd}:*)") cmds;
  mkBashPermsSudoWildcard = cmds: map (cmd: "Bash(sudo ${cmd}:*)") cmds;

  # Helper to generate multiple subcommands/flags for same base command
  # mkCmdWithFlags "smartctl" ["-a" "-H" "-i"] => ["smartctl -a" "smartctl -H" "smartctl -i"]
  mkCmdWithFlags = baseCmd: flags: map (flag: "${baseCmd} ${flag}") flags;

  # Helper to generate Read/Grep/Glob permissions for directories
  # Allows recursive access to all files in specified directories
  # Pattern syntax: https://code.claude.com/docs/en/settings
  #   - Supports glob patterns: ** for recursive, * for wildcard
  #   - Supports ~ for home directory expansion
  mkReadPerms = dirs:
    lib.flatten (map (
        dir:
          map (tool: "${tool}(${dir}/**)") ["Read" "Grep" "Glob"]
      )
      dirs);

  # Directories where Read/Grep/Glob are always allowed without prompting
  # /code contains all git repos organized by host (github.com, gitlab.com, etc.)
  # ~/code contains symlinks to specific projects within /code, plus some direct subdirs
  alwaysAllowedReadDirs = [
    "~/.claude" # Claude Code session history, settings, commands
    "/code" # Primary code location (canonical git repos by host)
    "/home/agentydragon/code" # Convenience symlinks + some direct projects
  ];

  # KEEP IN SYNC - BEGIN: System inspection sudo commands from Ansible
  #   ansible/roles/system_inspection_nopasswd/defaults/main.yml (system_inspection_nopasswd_commands)
  #
  # NOTE: Some Ansible restrictions cannot be perfectly mapped to Claude Code permissions:
  # - File path restrictions (e.g., "tail /var/log/*" only) - Claude Code will allow broader access
  # - Specific command arguments - we approximate with :* wildcards where Ansible is more specific

  # Commands that DON'T need sudo (allowed without sudo for convenience)
  noSudoInspectionCommands = [
    # Hardware information (user-accessible)
    "lspci"
    "lsusb"
    "lscpu"
    "lsblk"
    "sensors"
    # Process information
    "ps"
    "pstree"
    "top"
    "htop"
    "pgrep"
    # Memory information
    "free"
    "vmstat"
    # Disk information
    "df"
    "du"
    "findmnt"
    # Network information
    "netstat"
    "ss"
    "dig"
    "nslookup"
    "host"
    "traceroute"
    "mtr"
    "nmap"
    # Kernel module information
    "lsmod"
    # Security/user information
    "last"
    "w"
    "who"
    "users"
    "id"
    "groups"
  ];

  # Commands that NEED sudo - simple commands allowing any arguments
  sudoSimpleInspectionCommands = [
    # Hardware information (needs sudo for full access)
    "lshw"
    "dmidecode"
    "hwinfo"
    "biosdecode"
    "ownership"
    "vpddecode"
    "inxi"
    "acpi"
    "acpitool"
    "sensors-detect"
    "ipmitool"
    "ipmi-sensors"
    "fwupdmgr"
    "nvidia-smi"
    "nvidia-settings"
    # System information
    "uname"
    "hostnamectl"
    "timedatectl"
    "localectl"
    "loginctl"
    "bootctl"
    # Process information (sudo for all processes)
    "iotop"
    "pidstat"
    # Memory information
    "slabtop"
    "cat /proc/meminfo"
    # Disk information
    "blkid"
    # Service information
    "journalctl"
    # File system information - display commands only
    "lvdisplay"
    "vgdisplay"
    "pvdisplay"
    # Kernel information
    "modinfo"
    "dmesg"
    # Security information
    "lastlog"
    "aa-status"
    "sestatus"
    # Performance monitoring
    "iostat"
    "mpstat"
    "sar"
  ];

  # Commands with specific safe subcommands (Ansible restricts to these)
  # Use exact match (no :*) for fixed arguments, wildcard (:*) for variable args
  sudoSpecificSubcommandsExact =
    # Disk partitioning - ONLY read-only list modes (exact commands)
    mkCmdWithFlags "fdisk" ["-l"]
    ++ mkCmdWithFlags "parted" ["-l"]
    # NVMe info - ONLY read operations (exact commands)
    ++ ["nvme list"]
    # Network information - ONLY show/list operations (exact commands)
    ++ mkCmdWithFlags "ip" ["addr show" "-s addr show" "route show" "-s route show" "link show" "-s link show" "neighbor show" "netns list"]
    # Service information - ONLY safe subcommands (exact commands)
    ++ mkCmdWithFlags "systemctl" ["list-units" "list-unit-files" "list-timers" "list-sockets"]
    # File systems - ONLY read commands (exact commands)
    ++ ["zfs list"]
    ++ mkCmdWithFlags "zpool" ["status" "list"]
    ++ mkCmdWithFlags "btrfs" ["filesystem show" "device stats"]
    # Package managers - ONLY list modes (exact commands)
    ++ ["apt list" "dpkg -l" "snap list" "flatpak list"]
    # System control - ONLY read modes (exact commands)
    ++ mkCmdWithFlags "sysctl" ["-a" "-N"]
    # Firewall - ONLY list/show modes (exact commands)
    ++ ["firewall-cmd --list-all"]
    ++ mkCmdWithFlags "iptables" ["-L" "-S"]
    ++ mkCmdWithFlags "ip6tables" ["-L" "-S"]
    ++ ["nft list ruleset"]
    # Container/VM - ONLY read-only info (exact commands)
    ++ mkCmdWithFlags "docker" ["ps" "images" "info" "version"]
    ++ mkCmdWithFlags "podman" ["ps" "images"]
    ++ ["virsh list" "qm list"];

  # Commands that need variable arguments (use wildcard)
  # Pattern "cmd:*" matches "cmd" followed by anything (including spaces/args)
  sudoSpecificSubcommandsWildcard =
    # SMART disk info - needs device path
    mkCmdWithFlags "smartctl" ["-a" "-H" "-i" "-l"]
    # NVMe info - needs device path
    ++ mkCmdWithFlags "nvme" ["smart-log" "id-ctrl" "id-ns"]
    # Service status - needs service name
    ++ mkCmdWithFlags "systemctl" ["status" "show"]
    # System control - read specific variable
    ++ ["sysctl -n"]
    # Proxmox - needs path argument
    ++ ["pvesh get"]
    # Performance monitoring - needs args
    ++ mkCmdWithFlags "perf" ["stat" "top"];
  # OMITTED from Claude Code permissions (cannot express these restrictions):
  # - sudo tail -f /var/log/* (path restriction)
  # - sudo head /var/log/* (path restriction)
  # - sudo cat /var/log/* (path restriction)
  # - sudo less /var/log/* (path restriction)
  # - sudo zcat /var/log/*.gz (path restriction)
  # - sudo bzcat /var/log/*.bz2 (path restriction)
  #
  # Claude Code uses prefix matching only. We cannot restrict commands to specific paths.
  # Ansible makes these log viewing commands passwordless for convenience, but we omit them
  # from Claude Code auto-allow to avoid granting unrestricted file access.
  # KEEP IN SYNC - END

  # Auto-discover all .md files in commands/ directory
  commandsDir = ./commands;
  commandFiles = builtins.readDir commandsDir;
  commands =
    lib.mapAttrs' (
      name: type:
        lib.nameValuePair
        (lib.removeSuffix ".md" name)
        (commandsDir + "/${name}")
    ) (lib.filterAttrs (
        name: type:
          type == "regular" && lib.hasSuffix ".md" name
      )
      commandFiles);

  # Skills directory for Claude Code
  # Skills are model-invoked capabilities that Claude automatically uses based on context
  # Each skill is a subdirectory containing SKILL.md and optional supporting files
  skillsDir = ./skills;
in {
  programs.claude-code = {
    enable = true;
    package = pkgs.claude-code;

    commands = commands;

    settings = {
      theme = "dark";
      includeCoAuthoredBy = false;
      permissions = {
        allow =
          [
            "Read"
            "Edit"
            "Write"
            "MultiEdit"
            "Search"
            "Task"
            "Bash(git status:*)"
            "Bash(git diff:*)"
            "Bash(git stash show:*)"
            "Bash(git stash list:*)"
            "WebFetch"
            "WebSearch"
          ]
          ++ mkReadPerms alwaysAllowedReadDirs
          ++ mkBashPermsWildcard noSudoInspectionCommands
          ++ mkBashPermsSudoWildcard sudoSimpleInspectionCommands
          ++ mkBashPermsSudo sudoSpecificSubcommandsExact
          ++ mkBashPermsSudoWildcard sudoSpecificSubcommandsWildcard;
        # ask = ["Bash(*)"];  - use Bash without parens to allow all commands
        deny = [];
        defaultMode = "default";
      };
    };
  };

  # Deploy skills to ~/.claude/skills/
  # Skills are stored in nix/home/claude-code/skills/ and symlinked for declarative management
  home.file =
    lib.mapAttrs' (
      skillName: skillType:
        lib.nameValuePair
        ".claude/skills/${skillName}"
        {
          source = skillsDir + "/${skillName}";
          recursive = true;
        }
    ) (lib.filterAttrs (
        name: type:
          type == "directory"
      )
      (builtins.readDir skillsDir));
}

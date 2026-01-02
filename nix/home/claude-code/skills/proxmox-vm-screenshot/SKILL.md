---
name: proxmox-vm-screenshot
description: Take and view screenshots of Proxmox VMs using QEMU monitor screendump
---

# Proxmox VM Screenshot Skill

This skill captures screenshots of VMs running on Proxmox hosts using QEMU monitor commands and makes them viewable in Claude Code.

## Instructions

When asked to take a screenshot or view the console of a Proxmox VM, use the automated script:

```bash
~/.claude/skills/proxmox-vm-screenshot/vm-screenshot.sh <VM_ID>
```

The script will:

1. Take screenshot via SSH to Proxmox host
2. Copy PPM file to local machine
3. Convert to PNG using local imagemagick
4. Clean up temporary files
5. Output final PNG path for viewing with Read tool

## Examples

**Taking screenshot of VM 106:**

```bash
~/.claude/skills/proxmox-vm-screenshot/vm-screenshot.sh 106
```

Then use Read tool to view `/tmp/vm106-current.png`

**Manual process (if script unavailable):**

```bash
# Take screenshot (non-interactive)
ssh root@atlas 'echo "screendump /tmp/vm110-screenshot.ppm" | qm monitor 110'

# Copy and convert locally
scp root@atlas:/tmp/vm110-screenshot.ppm /tmp/vm110-screenshot.ppm
convert /tmp/vm110-screenshot.ppm /tmp/vm110-screenshot.png
```

**Debugging VM boot issues:**

- Useful when VMs are not responding on network
- Shows console output, kernel messages, boot progress
- Can identify stuck boot processes or network configuration issues

## Notes

- Requires ImageMagick (`convert` command) on Proxmox host
- Screenshots capture the current console state
- Works for any VM ID on the Proxmox host
- Useful for debugging boot issues, network problems, or checking VM status

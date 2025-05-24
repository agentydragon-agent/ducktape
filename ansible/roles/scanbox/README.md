Printer "push-scan" sandbox share
=================================

Installs a size-capped loop-back ext4 image and exposes it as a Samba
share *ScanBox* writable only by a dedicated unprivileged user. Access is
locked to printer’s IP.

Usage
-----

```yaml
- hosts: laptop
  become: true
  roles:
    - role: scanbox
      vars:
        scanbox_size: 500M          # optional overrides
        scanbox_printer_ip: 192.168.0.123
```

After running, set a password:

```bash
sudo smbpasswd -s -a scanbox
```

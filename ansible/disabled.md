```yaml
- name: Install Steam
  become: true
  ansible.builtin.apt:
    pkg:
      - steam
```

## Anki mini-format-pack

Disabled - seems I deleted my fork.

```yaml
- name: Install mini-format-pack
  tags: [anki, anki-addon]
  vars:
    ankiaddons_dir: "{{ ansible_user_dir }}/.local/share/Anki2/addons21"
    addon_id: 295889520
    addon_dir: "{{ ankiaddons_dir }}/{{ addon_id }}"
  block:
    # https://github.com/glutanimate/anki-addon-builder
    - ansible.builtin.pip:
        executable: pip3
        name: aab
    - ansible.builtin.tempfile:
        state: directory
        suffix: mini-format-pack
      register: temp_dir
    - ansible.builtin.git:
        # note: my own fork
        repo: https://github.com/agentydragon/mini-format-pack
        dest: "{{ temp_dir.path }}"
        version: 725bb8595631e4dbc56bf881427aeada848e43c9  # https://github.com/glutanimate/mini-format-pack/pull/13
      changed_when: false
    - ansible.builtin.command: "{{ ansible_user_dir }}/.local/bin/aab build -d local -t anki21 725bb85"
      args:
        chdir: "{{ temp_dir.path }}"
      changed_when: false
    - ansible.builtin.file:
        path: "{{ addon_dir }}"
        state: directory
    - ansible.builtin.unarchive:
        remote_src: true
        src: "{{ temp_dir.path }}/build/mini-format-pack-725bb85-anki21.ankiaddon"
        dest: "{{ addon_dir }}"
```

## Chrome remote desktop

```yaml
# Installation steps for Chrome Remote Desktop.
# https://cloud.google.com/solutions/chrome-desktop-remote-on-compute-engine
- name: "Install chrome remote desktop, chrome"
  become: true
  when: ansible_architecture == "amd64"
  ansible.builtin.apt:
    deb: https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb
- name: Set 2D cinnamon
  become: true
  ansible.builtin.copy:
    mode: 0755
    content: "exec /etc/X11/Xsession /usr/bin/cinnamon-session-cinnamon2d"
    dest: /etc/chrome-remote-desktop-session

# Prevent screensaver from getting enabled (to prevent getting locked
# out on machines with no password set up).
- name: Disable screensaver to not get locked out of VM (with no password)
  block:
    - name: Disable locking on screensaver
      dconf:
        key: /org/cinnamon/desktop/screensaver/lock-enabled
        value: "false"
    - name: Disable automatic screensaver when idle
      dconf:
        key: /org/cinnamon/desktop/screensaver/session/idle-delay
        value: "uint32 0"
    - name: Disable locking on suspend
      dconf:
        key: /org/cinnamon/settings-daemon/plugins/power/lock-on-suspend
        value: "false"

- name: Disable desktop effects (for faster remote desktop)
  block:
    - name: Disable desktop effects
      dconf:
        key: /org/cinnamon/desktop-effects
        value: "false"
    - name: Set desktop close effect to traditional
      dconf:
        key: /org/cinnamon/desktop-effects-close-effect
        value: "'traditional'"
    - name: Set desktop map effect to traditional
      dconf:
        key: /org/cinnamon/desktop-effects-map-effect
        value: "'traditional'"
    - name: Turn off maximize effect
      dconf:
        key: /org/cinnamon/desktop-effects-maximize-effect
        value: "'none'"
    - name: Set minimize effect to traditional
      dconf:
        key: /org/cinnamon/desktop-effects-minimize-effect
        value: "'traditional'"
    - name: Turn off tile effect
      dconf:
        key: /org/cinnamon/desktop-effects-tile-effect
        value: "'none'"
    - name: Turn off unmaximize effect
      dconf:
        key: /org/cinnamon/desktop-effects-unmaximize-effect
        value: "'none'"
    - name: Turn off dialog desktop effects
      dconf:
        key: /org/cinnamon/desktop-effects-on-dialogs
        value: "false"
    - name: "No desktop effects on menus"
      dconf:
        key: /org/cinnamon/desktop-effects-on-menus
        value: "false"
    - name: "No vfade"
      dconf:
        key: /org/cinnamon/enable-vfade
        value: "false"
    - name: "No startup animation"
      dconf:
        key: /org/cinnamon/startup-animation
        value: "false"
# fails with "no such service"
# - name: disable display manager
#   systemd:
#     name: lightdm.service
#     enabled: no
```

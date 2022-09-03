---
title: Making Neovim's color scheme follow system light/dark preference on GNOME
---

GNOME has a feature where there's a system-level setting for whether user
prefers light or dark theme. This got added relatively recently (in the last
~year or so). Its intended use is so that apps can automatically adjust to match
the user's preferences without hacks. Hacks like "read the current GTK theme
and try to figure out whether it's light or dark based on some heuristic".

Today I've managed to put together one annoying missing piece of personal infra.
I've had `gnome-terminal` sorta-following the setting for a while, and tonight
I've made [Neovim][neovim] also do that. To celebrate, I wanted to share how
this works.

Those are the dependencies:

```bash
pip install pynvim absl-py dbus-python
```

## Shared setup

### Night Theme Switcher

Install the [Night Theme Switcher][night-theme-switcher] GNOME extension.
This extension lets you attach scripts to when the theme is changed.

### Light/dark scripts

Create a pair of scripts, `set_light_theme` and `set_dark_theme`, put them
wherever. Mine are currently in `~/bin` (with `PATH` set to point there), but
it doesn't matter.

Point Night Theme Switcher to run those when the theme is changed.

## Neovim

In my particular case, I like [Solarized colors][solarized], which I have
everywhere I can (VSCode, Neovim, `gnome-terminal`, even this site - as of now).
I use the `[vim-colors-solarized][vim-colors-solarized]` plugin which adds
both light and dark variants, toggled by `set background=light` or `dark`.

### `init.vim`

Open `~/.config/nvim/init.vim` and add this hunk somewhere near the top.
It'll read the current setting from `gsettings` and update Vim's background to
match.

```vim
" Set color theme to light/dark based on current system preferences.
" Done early to prefer flashing of the wrong theme before this runs.
" Will later be picked up when setting up Solarized colors.
" Called on theme switches by set_light_theme, set_dark_theme scripts.
function! UpdateThemeFromGnome()
  if !executable('gsettings')
    return
  endif

  let color_scheme = system('gsettings get org.gnome.desktop.interface color-scheme')
  " remove newline character from color_scheme
  let color_scheme = substitute(color_scheme, "\n", "", "")

  if color_scheme == 'prefers-light'
    set background=light
  else
    set background=dark
  endif
endfunction

UpdateThemeFromGnome()
```

### `update_nvim_theme_from_gnome.py`

Create this script somewhere. I named it `update_nvim_theme_from_gnome.py`.
It'll use `pynvim` to connect to running Neovim instances and run the function
we made above to update the background.

```python
#!/usr/bin/python
# Updates the theme on all running Neovim instances.

import glob
import os

from pynvim import attach

background = "dark"

# TODO: should probably only try to do this to *my* neovim instances
for dir in glob.glob('/tmp/nvim*'):
    socket = os.path.join(dir, '0')
    nvim = attach("socket", path=socket)
    nvim.command("call UpdateThemeFromGnome()")
```

Update `set_light_theme` and `set_dark_theme` to call it. This will make it so
that when you switch theme, it'll not just affect new Neovim instances, but also
all currently running ones.

There's a TODO in there. Exercise for the reader I guess - I don't particularly
care because I rarely run Neovim as `root`, but I expect this would crash
and burn if there were Neovim running as any user other than you. Cause it would
probably not let you write into that socket.

## `gnome-terminal`

I have another script for `gnome-terminal` doing something similar.

It assumes that you have a light and dark profile set up in `gnome-terminal`.
Open Preferences and note down the names of the profiles you wanna use in
light/dark configurations

### `switch_gnome_terminal_profile.py`

Let's call our script `switch_gnome_terminal_profile.py`:

```python
#!/usr/bin/python
# Requirements: absl-py

import json
import re
import subprocess
import dbus
from xml.etree import ElementTree
from absl import app, flags

_PROFILE = flags.DEFINE_string('profile', None,
                               'Name of profile to set everywhere')


def main(_):
    base_path = '/org/gnome/terminal/legacy/profiles:/'
    out = subprocess.check_output(["dconf", "list", base_path]).decode('utf-8')
    uuids = set()
    uuid_by_name = {}
    for line in out.splitlines():
        if ':' not in line:
            continue  # not a profile
        profile = re.fullmatch(r":(.+)/", line)[1]

        name = subprocess.check_output([
            "dconf", "read", base_path + ':' + profile + '/visible-name'
        ]).decode('utf-8').strip()
        # unquote. TODO: do nicer.
        name = re.fullmatch(r"'(.+)'", name)[1]
        uuid_by_name[name] = profile
        uuids.add(profile)

    if _PROFILE.value in uuids:
        uuid = _PROFILE.value
    elif _PROFILE.value in uuid_by_name:
        uuid = uuid_by_name[_PROFILE.value]
    else:
        raise Exception("No such profile (by UUID or name)")

    # Change default profile.
    subprocess.check_output(
        ["dconf", "write", base_path + 'default', f"'{uuid}'"]).decode('utf-8')

    bus = dbus.SessionBus()

    obj = bus.get_object('org.gnome.Terminal', '/org/gnome/Terminal/window')
    iface = dbus.Interface(obj, 'org.freedesktop.DBus.Introspectable')

    tree = ElementTree.fromstring(iface.Introspect())
    windows = [child.attrib['name'] for child in tree if child.tag == 'node']

    for window in windows:
        window_path = f'/org/gnome/Terminal/window/{window}'

        obj = bus.get_object('org.gnome.Terminal', window_path)
        iface = dbus.Interface(obj, 'org.gtk.Actions')
        iface.SetState('profile', uuid, [])
        # TODO: this only includes currently active tabs, not background tabs :/


if __name__ == '__main__':
    flags.mark_flag_as_required(_PROFILE.name)
    app.run(main)
```

This script expects a profile name in `--profile`, and when called, it'll
update `gnome-terminal`'s `dconf` setting to have that profile be the default.
That will make any new terminal windows/tabs use that profile.

Then it'll talk to `gnome-terminal` over [dbus][dbus] and update the profile
of each window. Unfortunately, this only updates the theme on windows that
are currently active - i.e., not on background tabs. I've not yet figured out
how to fix this - I've looked into [`gnome-terminal`'s source
code][gnome-terminal-source] when I originally wrote the script, and I even
faintly remember reporting this as an issue. Basically that the dbus interface
should be a bit extended. If you know how to fix this, let me know.

## Putting it together

Just make your `set_light_theme` and `set_dark_theme` scripts call the
appropriate scripts for `gnome-terminal` and Neovim. Here's how they look for
me:

### `set_dark_theme`

```bash
#!/bin/bash
switch_gnome_terminal_profile --profile='Solarized Dark'
python ~/repos/ducktape/update_nvim_theme_from_gnome.py
```

### `set_light_theme`

```bash
#!/bin/bash
switch_gnome_terminal_profile --profile='Solarized Light'
python ~/repos/ducktape/update_nvim_theme_from_gnome.py
```

Why is one on `PATH` and not the other? Tech debt in my personal infra.
Deployment step of built artifacts isn't separated and my old scripts repo isn't
yet merged into my [maximally glorious Ducktape monorepo][ducktape]. Sue me :P

Still, over time, I've made it a project to make the duct tape holding together
my computer have a better CI setup than many commercial software projects :P

<figure>
  <img src="/static/im-not-proud-of-it.gif" alt="I'm not proud of it. I am a bit." />
</figure>

## Short update

Oh also I'm now in San Francisco and at [OpenAI][openai], working on
reinforcement learning. Long time, much news. Also [Copilot][copilot] is
a thing and has surprised me very strongly by how good and useful it is.
Sometime I'll be writing some sorta summary of last year or two, but today is
not the day and this is not that blogpost.

Cheers, have a nice long weekend if you're in the US.

[neovim]: https://neovim.io/
[night-theme-switcher]: https://extensions.gnome.org/extension/2236/nightthemeswitcher/
[vim-colors-solarized]: https://github.com/altercation/vim-colors-solarized
[solarized]: https://ethanschoonover.com/solarized/
[dbus]: https://dbus.freedesktop.org/doc/dbus-python/tutorial.html
[gnome-terminal-source]: https://gitlab.gnome.org/GNOME/gnome-terminal/-/tree/master
[ducktape]: https://gitlab.com/agentydragon/ducktape
[copilot]: https://github.com/features/copilot/
[openai]: https://openai.com/

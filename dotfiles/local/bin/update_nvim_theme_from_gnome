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

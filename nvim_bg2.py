#!/usr/bin/env python

# 2022-09-03: this actually works!

import glob
import os

from pynvim import attach

background = "dark"

for dir in glob.glob('/tmp/nvim*'):
    socket = os.path.join(dir, '0')
    nvim = attach("socket", path=socket)
    # TODO: would be nicer if I could just call the same neovim code as i have
    # in init.vim so that it works
    nvim.command(f"set background={background}")

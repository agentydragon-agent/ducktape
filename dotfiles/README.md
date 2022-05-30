Dotfiles
========

This directory contains my dotfiles.
I use [rcm](https://github.com/thoughtbot/rcm) to manage them.

To install dotfiles:
```
# Clone to ~/.dotfiles
git clone git@github.com:MichalPokorny/dotfiles .dotfiles

# Apply symlinks
rcup -x README.md
```

To list rc: `lsrc`

To add new RC files: `mkrc ~/.tigrc`

`rcup -B agentydragon`

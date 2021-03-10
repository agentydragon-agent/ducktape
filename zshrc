# ~/.zshrc
. /etc/profile

# Path to your oh-my-zsh installation.
export ZSH=$HOME/.oh-my-zsh

# Uncomment to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment to change how often to auto-update (in days).
# export UPDATE_ZSH_DAYS=13

# Uncomment to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Disable command auto-correction.
DISABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# COMPLETION_WAITING_DOTS="true"

# Disable marking untracked files under VCS as dirty.
# This makes repository status check for large repositories much, much faster.
DISABLE_UNTRACKED_FILES_DIRTY="true"

# Change the command execution time stamp shown in the history command output.
# The optional three formats: "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
HIST_STAMPS="yyyy-mm-dd"

# gitfast
# git: gc, gca, gs, ...
# interesting plugins: 'z'
#plugins=(git gpg-agent gem web-search colored-man)
plugins=()

# Agnoster is a ZSH theme assuming Solarized and Powerline-patched fonts.
# Right prompt: current time
RPROMPT='%*'
DEFAULT_USER='agentydragon'
ZSH_THEME='agnoster'

source $ZSH/oh-my-zsh.sh

# Nechci completion automaticky kdyz je to ambiguous
unsetopt menu_complete
unsetopt auto_menu

zstyle ':completion:*' completer _complete _ignored
zstyle ':completion:*' group-name ''
#zstyle ':completion:*' list-colors ${(s.:.)LS_COLORS}
zstyle ':completion:*' matcher-list ''

#autoload -Uz compinit
#compinit

HISTFILE=~/.histfile
# https://github.com/bamos/zsh-history-analysis#increasing-the-history-file-size
HISTSIZE=10000000
SAVEHIST=10000000
setopt EXTENDED_HISTORY

setopt autocd

# vi mode
#bindkey -v

# emacs mode
bindkey -e

# Record keystrokes
# alias vim='vim -w ~/.vim-keylog "$@"'

ZSH_THEME_TERM_TITLE_IDLE="%n: %~ $"

unsetopt share_history # Don't share command history between zsh's

#eval `dircolors ~/.dir_colors/dircolors`
export MC_SKIN=~/.config/mc/solarized.ini

# for enca/enconv
export DEFAULT_CHARSET=utf8

alias gs='git status --short --branch'
source $HOME/.aliases

# The next line updates PATH for the Google Cloud SDK.
#if [ -f '/home/agentydragon/bin/google-cloud-sdk/path.zsh.inc' ]; then source '/home/agentydragon/bin/google-cloud-sdk/path.zsh.inc'; fi

# The next line enables shell command completion for gcloud.
#if [ -f '/home/agentydragon/bin/google-cloud-sdk/completion.zsh.inc' ]; then source '/home/agentydragon/bin/google-cloud-sdk/completion.zsh.inc'; fi
#
# Do not paginate if less than 1 page.
export LESS="-F -X $LESS"

# SDK for Remarkable
#. /usr/local/oecore-x86_64/environment-setup-cortexa9hf-neon-oe-linux-gnueabi


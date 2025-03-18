--set tabstop=8
--set shiftwidth=8
--set softtabstop=8
--
--set smartindent
--
--set encoding=utf-8
--set wildmenu
--set hidden
--
--set ttyfast
--
--" fold by syntax, open all by default
--set foldmethod=syntax
--set foldlevelstart=20
--
--" chci aspon 5 radku mezi koncem stranky a kurzorem
--set scrolloff=5
--
--set omnifunc=syntaxcomplete#Complete
--
--" to byvalo <S-M>, ale to koliduje s 'vyber prostredni radku'
--noremap <Leader>m :make<CR>
--
--" no mistyped :w or :q...
--:command W w
--:command Q q
--
--set showcmd
--set laststatus=2
--
--" Plug 'wincent/command-t'
--" Plug 'tpope/vim-fugitive'
--Plug 'derekwyatt/vim-scala'
--Plug 'pbrisbin/vim-mkdir' " mkdir needed dirs before writing buffer
--Plug 'bazelbuild/vim-ft-bzl'
--Plug 'google/vim-maktaba'  " dependency of vim-codefmt
--Plug 'google/vim-codefmt'
--Plug 'google/vim-glaive'  " used to configure codefmt's maktaba flags
--Plug 'leafgarland/typescript-vim'
--Plug 'cespare/vim-toml'
--Plug 'wellle/context.vim'
--
--set textwidth=80
--
--" This is taken from: https://github.com/cespare/vim-toml/blob/master/ftdetect/toml.vim
--" TODO: Why is this necessary?
--autocmd BufNewFile,BufRead *.toml,Gopkg.lock,Cargo.lock,*/.cargo/config,*/.cargo/credentials,Pipfile setf toml
--
--autocmd Filetype c setlocal cindent nosmartindent
--" TODO: enable this settings
--" autocmd Filetype cpp setlocal cindent nosmartindent tabstop=2 softtabstop=2 expandtab
--
--" Hide stuff in:
--"   anything from .gitignore,
--"   the . and .. entries,
--"   Vim swapfiles,
--"   .git directory
--"   unuseful stuff in ~
--let g:netrw_list_hide= join([
--\ netrw_gitignore#Hide(),
--\  '.*\.sw?$',
--\  '^\./$',
--\  '^\.\./$',
--\  '.*/\.git/$'],
--\',')
--" Hide netrw banner
--let g:netrw_banner=0
--
--let g:matchparen_insert_timeout=5
--
--" Highlight end of line whitespace and mixed spaces and tabs
--highlight ExtraWhitespace ctermbg=darkgreen guibg=darkgreen
--autocmd ColorScheme * highlight ExtraWhitespace ctermbg=red guibg=red
--match ExtraWhitespace /\s\+$\| \+\ze\t/
--au InsertEnter * match ExtraWhitespace /\s\+\%#\@<!$\| \+\ze\t/
--au InsertLeave * match ExtraWhitespace /\s\+$\| \+\ze\t/
--
--" u mad bro?
--inoremap <Left> ←
--inoremap <Right> →
--inoremap <Up> ↑
--inoremap <Down> ↓
--inoremap <S-Left> ⇐
--inoremap <S-Right> ⇒
--inoremap <S-Up> ⇑
--inoremap <S-Down> ⇓
--
--" Highlight column 80
--set colorcolumn=80,+0
--
--" set t_Co=256
--
--" Jump to last position on opening files (stolen from Destroy All Software)
--" ('\" == mark when last exiting buffer, g` = go to, jumplist-nondestructive)
--autocmd BufReadPost * if line("'\"") > 0 && line("'\"") <= line("$") | exe "normal g`\"" | endif
--
--" Don't clear screen after exiting Vim.
--" http://www.shallowsky.com/linux/noaltscreen.html
--" set t_ti= t_te=
--
--" Set codefmt autoformatter settings
--augroup autoformat_settings
--  autocmd FileType bzl AutoFormatBuffer buildifier
--  autocmd FileType c,cpp,proto,javascript AutoFormatBuffer clang-format
--  autocmd FileType go AutoFormatBuffer gofmt
--  autocmd FileType rust AutoFormatBuffer rustfmt
--  " autocmd FileType html,css,json AutoFormatBuffer js-beautify
--  autocmd FileType java AutoFormatBuffer google-java-format
--augroup END
--
--set foldmethod=syntax
--set foldcolumn=1
--let javaScript_fold=1 "activate folding by JS syntax
--set foldlevelstart=99
--
--" Map Alt-T to paste current datetime
--inoremap <A-t> <C-R>=strftime('%Y-%m-%d %H:%M:%S')<C-M>
--
--" Copilot
--let g:copilot_filetypes = {
--\ 'yaml': v:true,
--\ 'markdown': v:true,
--\ }
local opt = vim.opt
opt.number = true -- Show line numbers
opt.hlsearch = true -- Highlight search matches
opt.incsearch = true -- Show search matches as you type
opt.wrap = false -- Disable line wrap
opt.expandtab = true -- Use spaces instead of tabs
opt.ignorecase = true -- Case-insensitive search...
opt.smartcase = true -- ... but case-sensitive if uppercase char present
opt.undofile = true -- Enable persistent undo
opt.updatetime = 1000 -- write swap file if nothing typed for 1000 ms (default is 4000ms)

opt.shiftwidth = 4 -- Indent size (width of an indent)
opt.tabstop = 4 -- Number of spaces tabs count for
opt.smartindent = true -- Smart indenting on new lines
-- opt.cursorline = true           -- Highlight the current line
opt.termguicolors = true -- Enable true color support (recommended for modern UI)

-- (not mine, need to check:)
-- opt.swapfile = false            -- Don't use swapfile
-- opt.backup = false              -- Don't create backup files

-- maybe -- try out:
-- opt.relativenumber = true       -- Relative line numbers
-- opt.splitright = true           -- Split vertical windows to the right
-- opt.splitbelow = true           -- Split horizontal windows to the bottom

-- Set up color scheme updating
-- Set color theme to light/dark based on current system preferences.
-- Done early to prefer flashing of the wrong theme before this runs.
-- Will later be picked up when setting up Solarized colors.
-- Called on theme switches by set_light_theme, set_dark_theme scripts.
---_G.UpdateThemeFromGnome = function()
---	-- Run gsettings
---	local color_scheme = vim.fn.system("gsettings get org.gnome.desktop.interface color-scheme")
---	-- strip newline
---	color_scheme = color_scheme:gsub("\n", "")
---	-- remove quotes
---	color_scheme = color_scheme:gsub("'", "")
---
---	if color_scheme == "prefer-dark" then
---		vim.o.background = "dark"
---	else
---		vim.o.background = "light"
---	end
---end
---_G.UpdateThemeFromGnome()

-- Make sure to setup `mapleader` and `maplocalleader` before
-- loading lazy.nvim so that mappings are correct.
-- This is also a good place to setup other settings (vim.opt)
vim.g.mapleader = " "
vim.g.maplocalleader = "\\"

require("config.lazy")

-- NeoSolarized: status line not rendered with any usable color:
-- {
--   "Tsuzat/NeoSolarized.nvim",
--   lazy = false, -- make sure we load this during startup if it is your main colorscheme
--   priority = 1000, -- make sure to load this before all the other start plugins
--   config = function() vim.cmd([[ colorscheme NeoSolarized ]]) end,
-- }

-- Django template formatter:
-- { "yaegassy/coc-htmldjango" }

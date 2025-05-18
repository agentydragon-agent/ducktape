local M = {
	"nvim-treesitter/nvim-treesitter",
	build = ":TSUpdate",
	--build = function()
	--	require("nvim-treesitter.install").update({ with_sync = true })()
	--end,
	event = { "BufReadPost", "BufNewFile" },
	config = function()
		-- Setup folding
		-- (Start with all folds open, but allow closing them)
		-- https://chatgpt.com/c/6829a714-cd44-8011-9607-bbcd1386db22
		vim.opt.foldmethod = "expr"
		vim.opt.foldexpr = "nvim_treesitter#foldexpr()"
		vim.opt.foldlevelstart = 99
		vim.opt.foldlevel = 99

		require("nvim-treesitter.configs").setup({
			-- List of parser name to always have installed, or "all"
			ensure_installed = {
				"bash",
				"bibtex",
				"c",
				"c_sharp",
				"clojure",
				"cmake",
				"cpp",
				"css",
				"csv",
				"desktop",
				"diff",
				"dockerfile",
				"git_config",
				"git_rebase",
				"gitattributes",
				"gitcommit",
				"gitignore",
				"go",
				"gomod",
				"gosum",
				"gotmpl",
				"haskell",
				"html",
				"htmldjango",
				"http",
				"ini",
				"java",
				"javadoc",
				"javascript",
				"jinja",
				"jq",
				"jsdoc",
				"json",
				"jsonnet",
				-- "latex",  -- TODO: needs tree-sitter CLI, but not installed via Ansible
				"lua",
				"luadoc",
				"make",
				"markdown",
				"nginx",
				"nix",
				"proto",
				"python",
				"requirements",
				"rust",
				"scss",
				"sql",
				"ssh_config",
				"starlark",
				"textproto",
				"tmux",
				"toml",
				"typescript",
				"vim",
				"vimdoc",
				"xml",
			},
			-- Install parsers asynchronously (only applied to `ensure_installed`)
			sync_install = false,
			-- Automatically install missing parsers when entering buffer
			-- Recommendation: set to false if you don't have `tree-sitter`
			-- CLI installed locally
			auto_install = true,
			highlight = { enable = true },
			indent = { enable = true },
		})
	end,
}
return { M }

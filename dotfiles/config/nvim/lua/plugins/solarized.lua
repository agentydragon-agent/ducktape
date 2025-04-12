return {
	"maxmx03/solarized.nvim",
	lazy = false,
	priority = 1000, -- priority < vim-lumen
	---@type solarized.config
	opts = {},
	config = function(_, opts)
		vim.o.termguicolors = true
		vim.o.background = "light"
		require("solarized").setup(opts)
		vim.cmd.colorscheme("solarized")
	end,
}

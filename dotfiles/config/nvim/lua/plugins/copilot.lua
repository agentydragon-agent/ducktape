--- https://github.com/zbirenbaum/copilot-cmp maybe ? (turns copilot into cmp source)
return {
	"github/copilot.vim",
	init = function()
		vim.g.copilot_filetypes = {
			yaml = true,
			markdown = true,
		}
	end,
}

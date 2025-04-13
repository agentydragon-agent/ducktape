return {
	"willmcpherson2/gnome.nvim",
	lazy = false,
	priority = 1100, -- priority > solarized => load before the color scheme
	config = function()
		require("gnome").setup({})
	end,
	--  require("gnome").setup
	--    -- these are the default options and can be omitted
	--    on_light = function()
	--      vim.api.nvim_set_option("background", "light")
	--    end,
	--    on_dark = function()
	--      vim.api.nvim_set_option("background", "dark")
	--    end,
	--  }
	--end
}

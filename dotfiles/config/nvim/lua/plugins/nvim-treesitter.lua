local M = {
    "nvim-treesitter/nvim-treesitter",
    build = function()
        require("nvim-treesitter.install").update({ with_sync = true })()
    end,
    event = { "BufReadPost", "BufNewFile" },
    config = function()
        require("nvim-treesitter.configs").setup({
            -- List of parser names, or "all" (listed parsers MUST always be installed)
            ensure_installed = {
                "python", "c", "lua", "vim", "vimdoc", "query",
                "markdown", "markdown_inline", "rust", "javascript",
            },
            -- Automatically install missing parsers when entering buffer
            -- Recommendation: set to false if you don't have `tree-sitter` CLI installed locally
            auto_install = true,
            highlight = { enable = true },
        })
    end,
}
return { M }



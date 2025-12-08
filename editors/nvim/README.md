# spork.nvim

Neovim plugin for [Spork](https://github.com/spork-lang/spork) - a Lisp that compiles to Python.

## Features

- Syntax highlighting for `.spork` files
- LSP integration via `nvim-lspconfig`
- Lisp-style indentation
- Filetype detection

## Requirements

- Neovim 0.8.0 or later
- Spork CLI installed (`spork` command available)
- [nvim-lspconfig](https://github.com/neovim/nvim-lspconfig) (for LSP features)

## Installation

### Using [lazy.nvim](https://github.com/folke/lazy.nvim)

```lua
{
  "spork-lang/spork",
  config = function()
    -- Add the nvim plugin to runtimepath
    vim.opt.runtimepath:append("/path/to/spork/editors/nvim")
    require("spork").setup()
  end,
}
```

### Using [packer.nvim](https://github.com/wbthomason/packer.nvim)

```lua
use {
  "/path/to/spork/editors/nvim",
  config = function()
    require("spork").setup()
  end,
}
```

### Manual Installation

Add the plugin directory to your runtimepath in `init.lua`:

```lua
vim.opt.runtimepath:append("/path/to/spork/editors/nvim")
require("spork").setup()
```

Or in `init.vim`:

```vim
set runtimepath+=/path/to/spork/editors/nvim
lua require("spork").setup()
```

## Configuration

### Basic Setup

```lua
require("spork").setup()
```

### Custom Configuration

```lua
require("spork").setup({
  -- Path to spork executable (default: "spork")
  cmd = "spork",

  -- Additional LSP server arguments
  cmd_args = { "lsp" },

  -- Enable LSP (default: true)
  lsp = true,

  -- Enable default keybindings (default: true)
  default_keymaps = true,

  -- LSP on_attach callback (called after default keymaps are set)
  on_attach = function(client, bufnr)
    -- Your custom on_attach logic
  end,

  -- LSP capabilities (merged with defaults)
  capabilities = nil,
})
```

### LSP Configuration with nvim-lspconfig

If you prefer to configure the LSP manually with nvim-lspconfig:

```lua
-- First, set up the spork plugin for syntax/filetype
require("spork").setup({ lsp = false })

-- Then configure LSP manually
local lspconfig = require("lspconfig")
local configs = require("lspconfig.configs")

-- Register the spork LSP if not already registered
if not configs.spork then
  configs.spork = {
    default_config = {
      cmd = { "spork", "lsp" },
      filetypes = { "spork" },
      root_dir = lspconfig.util.root_pattern("spork.it", ".git"),
      settings = {},
    },
  }
end

lspconfig.spork.setup({
  on_attach = your_on_attach,
  capabilities = your_capabilities,
})
```

## Key Mappings

The plugin sets up default keybindings when LSP attaches to a buffer:

| Key | Mode | Action |
|-----|------|--------|
| `K` | Normal | Hover documentation |
| `gd` | Normal | Go to definition |
| `gD` | Normal | Go to declaration |
| `gl` | Normal | Show line diagnostics |
| `[d` | Normal | Previous diagnostic |
| `]d` | Normal | Next diagnostic |
| `<leader>q` | Normal | Show all diagnostics in location list |
| `<leader>ds` | Normal | Document symbols |
| `<C-Space>` | Insert | Trigger completion |
| `<C-k>` | Insert | Signature help |

### Disabling Default Keymaps

If you prefer to set up your own keymaps:

```lua
require("spork").setup({
  default_keymaps = false,
  on_attach = function(client, bufnr)
    -- Your custom keybindings here
    local opts = { buffer = bufnr, noremap = true, silent = true }
    vim.keymap.set("n", "gd", vim.lsp.buf.definition, opts)
    -- etc.
  end,
})
```

## Commands

The plugin provides the following commands:

| Command | Description |
|---------|-------------|
| `:SporkInfo` | Show Spork LSP information |
| `:SporkRestart` | Restart the Spork LSP server |

## LSP Features

When the LSP is enabled, you get:

- **Completion**: Symbols, special forms, and macros
- **Hover**: Documentation and type information
- **Go to Definition**: Jump to symbol definitions
- **Diagnostics**: Parse and compile errors
- **Document Symbols**: Outline of definitions in the file

## Troubleshooting

### LSP not starting

1. Ensure `spork` is in your PATH:
   ```bash
   which spork
   ```

2. Test the LSP server manually:
   ```bash
   echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | spork lsp
   ```

3. Check the LSP log:
   ```lua
   vim.lsp.set_log_level("debug")
   -- Then check :LspLog
   ```

### Syntax highlighting not working

Ensure the plugin is loaded before opening `.spork` files:
```lua
:set runtimepath?
-- Should include the nvim plugin path
```

## License

See the main Spork project for license information.
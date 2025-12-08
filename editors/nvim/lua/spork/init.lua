-- spork.nvim - Neovim plugin for the Spork programming language
--
-- This module provides LSP integration and editor support for Spork,
-- a Lisp that compiles to Python.

local M = {}

-- Default configuration
M.config = {
  -- Path to spork executable
  cmd = "spork",

  -- Additional arguments for the LSP server
  cmd_args = { "lsp" },

  -- Enable LSP integration
  lsp = true,

  -- Enable default keybindings
  default_keymaps = true,

  -- LSP on_attach callback
  on_attach = nil,

  -- Additional LSP capabilities
  capabilities = nil,
}

-- Default keybindings for LSP features
local function setup_keymaps(bufnr)
  local opts = { buffer = bufnr, noremap = true, silent = true }

  -- Hover documentation
  vim.keymap.set("n", "K", vim.lsp.buf.hover, opts)

  -- Go to definition
  vim.keymap.set("n", "gd", vim.lsp.buf.definition, opts)

  -- Go to declaration (if available)
  vim.keymap.set("n", "gD", vim.lsp.buf.declaration, opts)

  -- Show line diagnostics
  vim.keymap.set("n", "gl", vim.diagnostic.open_float, opts)

  -- Navigate diagnostics
  vim.keymap.set("n", "[d", vim.diagnostic.goto_prev, opts)
  vim.keymap.set("n", "]d", vim.diagnostic.goto_next, opts)

  -- Show all diagnostics in location list
  vim.keymap.set("n", "<leader>q", vim.diagnostic.setloclist, opts)

  -- Completion (insert mode)
  vim.keymap.set("i", "<C-Space>", vim.lsp.buf.completion, opts)

  -- Signature help
  vim.keymap.set("i", "<C-k>", vim.lsp.buf.signature_help, opts)

  -- Document symbols
  vim.keymap.set("n", "<leader>ds", vim.lsp.buf.document_symbol, opts)
end

-- Check if a command exists
local function command_exists(cmd)
  local handle = io.popen("command -v " .. cmd .. " 2>/dev/null")
  if handle then
    local result = handle:read("*a")
    handle:close()
    return result ~= ""
  end
  return false
end

-- Create the on_attach function that sets up keymaps
local function create_on_attach(user_on_attach, setup_default_keymaps)
  return function(client, bufnr)
    -- Set up default keymaps if enabled
    if setup_default_keymaps then
      setup_keymaps(bufnr)
    end

    -- Call user's on_attach if provided
    if user_on_attach then
      user_on_attach(client, bufnr)
    end
  end
end

-- Setup the LSP client
local function setup_lsp(opts)
  -- Try to use nvim-lspconfig if available
  local ok, lspconfig = pcall(require, "lspconfig")
  if not ok then
    -- Fall back to manual LSP setup
    M.setup_lsp_manual(opts)
    return
  end

  local configs = require("lspconfig.configs")

  -- Register spork LSP configuration if not already registered
  if not configs.spork then
    configs.spork = {
      default_config = {
        cmd = { opts.cmd, unpack(opts.cmd_args) },
        filetypes = { "spork" },
        root_dir = lspconfig.util.root_pattern("spork.it", ".git"),
        settings = {},
        single_file_support = true,
      },
    }
  end

  -- Build LSP setup options
  local lsp_opts = {
    on_attach = create_on_attach(opts.on_attach, opts.default_keymaps),
  }

  if opts.capabilities then
    lsp_opts.capabilities = opts.capabilities
  end

  -- Setup the LSP
  lspconfig.spork.setup(lsp_opts)
end

-- Manual LSP setup without nvim-lspconfig
function M.setup_lsp_manual(opts)
  vim.api.nvim_create_autocmd("FileType", {
    pattern = "spork",
    callback = function(args)
      local client_id = vim.lsp.start({
        name = "spork",
        cmd = { opts.cmd, unpack(opts.cmd_args) },
        root_dir = vim.fs.dirname(
          vim.fs.find({ "spork.it", ".git" }, { upward = true, path = vim.fs.dirname(args.file) })[1]
        ) or vim.fn.getcwd(),
        capabilities = opts.capabilities,
      })

      if client_id then
        local client = vim.lsp.get_client_by_id(client_id)

        -- Set up default keymaps if enabled
        if opts.default_keymaps then
          setup_keymaps(args.buf)
        end

        -- Call user's on_attach if provided
        if client and opts.on_attach then
          opts.on_attach(client, args.buf)
        end
      end
    end,
  })
end

-- Create user commands
local function setup_commands()
  vim.api.nvim_create_user_command("SporkInfo", function()
    local clients = vim.lsp.get_clients({ name = "spork" })
    if #clients == 0 then
      print("Spork LSP is not running")
      return
    end

    local client = clients[1]
    print("Spork LSP Information:")
    print("  ID: " .. client.id)
    print("  Name: " .. client.name)
    print("  Root: " .. (client.config.root_dir or "none"))
    print("  Command: " .. table.concat(client.config.cmd, " "))
  end, { desc = "Show Spork LSP information" })

  vim.api.nvim_create_user_command("SporkRestart", function()
    local clients = vim.lsp.get_clients({ name = "spork" })
    for _, client in ipairs(clients) do
      vim.lsp.stop_client(client.id)
    end

    -- Wait a bit then restart
    vim.defer_fn(function()
      vim.cmd("edit")
    end, 100)

    print("Spork LSP restarted")
  end, { desc = "Restart the Spork LSP server" })
end

-- Main setup function
function M.setup(opts)
  -- Merge user options with defaults
  opts = vim.tbl_deep_extend("force", M.config, opts or {})
  M.config = opts

  -- Verify spork command exists
  if opts.lsp and not command_exists(opts.cmd) then
    vim.notify(
      "Spork executable not found: " .. opts.cmd .. "\nLSP features will be disabled.",
      vim.log.levels.WARN
    )
    opts.lsp = false
  end

  -- Setup commands
  setup_commands()

  -- Setup LSP if enabled
  if opts.lsp then
    setup_lsp(opts)
  end
end

-- Get the current configuration
function M.get_config()
  return M.config
end

return M

#!/usr/bin/env bash
set -Eeuo pipefail
readonly ARLO_MODEL="${ARLO_MODEL:-qwen3:14b}"
# shellcheck disable=SC2155
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
info() {
    printf '\n[%s] %s\n' "${ASSISTANT_NAME:-Installer}" "$1"
}

fail() {
    printf '\n[%s] ERROR: %s\n' "${ASSISTANT_NAME:-Installer}" "$1" >&2
    exit 1
}
to_unix_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -u "$1"
    elif command -v wslpath >/dev/null 2>&1; then
        wslpath -u "$1"
    else
        printf '%s\n' "$1"
    fi
}
to_windows_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    elif command -v wslpath >/dev/null 2>&1; then
        wslpath -w "$1"
    else
        printf '%s\n' "$1"
    fi
}
find_powershell() {
    if command -v pwsh.exe >/dev/null 2>&1; then
        POWERSHELL_BIN="$(command -v pwsh.exe)"
    elif command -v powershell.exe >/dev/null 2>&1; then
        POWERSHELL_BIN="$(command -v powershell.exe)"
    else
        fail "PowerShell is unavailable. This installer is designed for Windows."
    fi
}
get_windows_folder() {
    "$POWERSHELL_BIN" -NoProfile -Command 
        "[Environment]::GetFolderPath('$1')" | tr -d '\r'
}
find_winget() {
    if command -v winget.exe >/dev/null 2>&1; then
        WINGET_BIN="$(command -v winget.exe)"
        return 0
    fi
local candidate="${LOCAL_APP_DATA_UNIX}/Microsoft/WindowsApps/winget.exe"

if [[ -x "$candidate" ]]; then
    WINGET_BIN="$candidate"
    return 0
fi

return 1

}
winget_install() {
    local package_id="$1"
"$WINGET_BIN" install \
    --id "$package_id" \
    --exact \
    --source winget \
    --silent \
    --accept-package-agreements \
    --accept-source-agreements \
    --disable-interactivity

}
download_file() {
    local url="$1"
    local destination="$2"
command -v curl >/dev/null 2>&1 || fail \
    "curl is required to download an installer when WinGet is unavailable."

curl \
    --fail \
    --location \
    --retry 3 \
    --output "$destination" \
    "$url"

}
verify_authenticode_signature() {
    local installer_windows
    installer_windows="$(to_windows_path "$1")"
ARLO_INSTALLER_TO_VERIFY="$installer_windows" \
    "$POWERSHELL_BIN" -NoProfile -Command \
    '$Signature = Get-AuthenticodeSignature -LiteralPath $env:ARLO_INSTALLER_TO_VERIFY;
    if ($Signature.Status -ne "Valid") {
        Write-Error "Invalid installer signature: $($Signature.Status)"
        exit 1
    }'

}
install_python_directly() {
    local installer="${TMPDIR:-/tmp}/ARLO-python-3.12.10-$RANDOM.exe"
    TEMP_INSTALLERS+=("$installer")
info "Downloading the official Python 3.12.10 installer..."

download_file \
    "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" \
    "$installer"

local actual_hash

actual_hash="$(
    sha256sum "$installer" |
    awk '{ print toupper($1) }'
)"

[[ "$actual_hash" == "67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB" ]] \
    || fail "The downloaded Python installer failed SHA-256 verification."

MSYS2_ARG_CONV_EXCL='*' "$installer" \
    /quiet \
    InstallAllUsers=0 \
    PrependPath=1 \
    Include_test=0

}
install_ollama_directly() {
    local installer="${TMPDIR:-/tmp}/ARLO-ollama-setup-$RANDOM.exe"
    TEMP_INSTALLERS+=("$installer")
info "Downloading the official Ollama installer..."

download_file \
    "https://ollama.com/download/OllamaSetup.exe" \
    "$installer"

verify_authenticode_signature "$installer"

MSYS2_ARG_CONV_EXCL='*' "$installer" \
    /VERYSILENT \
    /NORESTART

}
cleanup_installers() {
    local installer
for installer in "${TEMP_INSTALLERS[@]:-}"; do
    [[ -n "$installer" ]] && rm -f -- "$installer"
done

}
python_works() {
    "$@" -c 
        'import sys, struct; raise SystemExit(0 if sys.platform == "win32" and (3, 12) <= sys.version_info < (3, 13) and struct.calcsize("P") == 8 else 1)' 
        >/dev/null 2>&1
}
find_python() {
    PYTHON_CMD=()
if command -v py.exe >/dev/null 2>&1 && python_works py.exe -3.12; then
    PYTHON_CMD=(py.exe -3.12)
    return 0
fi

local command_name

for command_name in python.exe python3.exe python3 python; do
    if command -v "$command_name" >/dev/null 2>&1 \
            && python_works "$(command -v "$command_name")"; then
        PYTHON_CMD=("$(command -v "$command_name")")
        return 0
    fi
done

local candidate

for candidate in \
    "${LOCAL_APP_DATA_UNIX}/Programs/Python/Python312/python.exe" \
    "${USER_PROFILE_UNIX}/.python/python.exe" \
    "${PROGRAM_FILES_UNIX}/Python312/python.exe"; do

    if [[ -x "$candidate" ]] && python_works "$candidate"; then
        PYTHON_CMD=("$candidate")
        return 0
    fi
done

return 1

}
find_ollama() {
    if command -v ollama.exe >/dev/null 2>&1; then
        OLLAMA_BIN="$(command -v ollama.exe)"
        return 0
    fi
local candidate

for candidate in \
    "${LOCAL_APP_DATA_UNIX}/Programs/Ollama/ollama.exe" \
    "${PROGRAM_FILES_UNIX}/Ollama/ollama.exe"; do

    if [[ -x "$candidate" ]]; then
        OLLAMA_BIN="$candidate"
        return 0
    fi
done

return 1

}
find_git() {
    if command -v git.exe >/dev/null 2>&1; then
        GIT_BIN="$(command -v git.exe)"
        return 0
    fi
if command -v git >/dev/null 2>&1; then
    GIT_BIN="$(command -v git)"
    return 0
fi

local candidate

for candidate in \
    "${PROGRAM_FILES_UNIX}/Git/cmd/git.exe" \
    "${PROGRAM_FILES_UNIX}/Git/bin/git.exe" \
    "${LOCAL_APP_DATA_UNIX}/Programs/Git/cmd/git.exe"; do

    if [[ -x "$candidate" ]]; then
        GIT_BIN="$candidate"
        return 0
    fi
done

return 1

}
find_neovim() {
    if command -v nvim.exe >/dev/null 2>&1; then
        NVIM_BIN="$(command -v nvim.exe)"
        return 0
    fi
if command -v nvim >/dev/null 2>&1; then
    NVIM_BIN="$(command -v nvim)"
    return 0
fi

local candidate

for candidate in \
    "${PROGRAM_FILES_UNIX}/Neovim/bin/nvim.exe" \
    "${LOCAL_APP_DATA_UNIX}/Programs/Neovim/bin/nvim.exe"; do

    if [[ -x "$candidate" ]]; then
        NVIM_BIN="$candidate"
        return 0
    fi
done

return 1
}
ensure_ollama_server() {
    if "$OLLAMA_BIN" list >/dev/null 2>&1; then
        return 0
    fi
info "Starting the local Ollama service..."

local log_file="${TMPDIR:-/tmp}/ARLO-ollama.log"

nohup "$OLLAMA_BIN" serve >"$log_file" 2>&1 &

local attempt

for attempt in {1..30}; do
    if "$OLLAMA_BIN" list >/dev/null 2>&1; then
        return 0
    fi

    sleep 1
done

fail "Ollama did not respond within 30 seconds. Check ${log_file}."
}
configure_neovim() {
    local nvim_dir="${LOCAL_APP_DATA_UNIX}/nvim"
    local lua_dir="${nvim_dir}/lua/diego"
    local core_dir="${lua_dir}/core"
    local plugins_dir="${lua_dir}/plugins"
info "Preparing Neovim configuration at ${LOCAL_APP_DATA_WINDOWS}\\nvim..."

if [[ -d "$nvim_dir" ]] && [[ -n "$(find "$nvim_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    local backup="${LOCAL_APP_DATA_UNIX}/nvim.backup.$(date +%Y%m%d-%H%M%S)"

    info "Existing Neovim configuration found; backing it up to $(to_windows_path "$backup")..."
    mv "$nvim_dir" "$backup"
fi

mkdir -p \
    "$core_dir" \
    "$plugins_dir"

cat >"${nvim_dir}/init.lua" <<'EOF'
require("diego.core")
require("diego.lazy")
EOF
cat >"${lua_dir}/lazy.lua" <<'EOF'
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.uv.fs_stat(lazypath) then
  local result = vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "--branch=stable",
    "https://github.com/folke/lazy.nvim.git",
    lazypath,
  })
  if vim.v.shell_error ~= 0 then
    error("Failed to install lazy.nvim:\n" .. result)
  end
end
vim.opt.rtp:prepend(lazypath)
require("lazy").setup({
  spec = {
    { import = "diego.plugins" },
  },
  install = {
    colorscheme = { "catppuccin" },
  },
  checker = {
    enabled = false,
  },
  change_detection = {
    notify = false,
  },
})
EOF
cat >"${core_dir}/init.lua" <<'EOF'
require("diego.core.options")
require("diego.core.keymaps")
EOF
cat >"${core_dir}/options.lua" <<'EOF'
vim.cmd("let g:netrw_liststyle = 3")
local opt = vim.opt
opt.number = true
opt.relativenumber = false
opt.tabstop = 2
opt.shiftwidth = 2
opt.expandtab = true
opt.autoindent = true
opt.wrap = false
opt.ignorecase = true
opt.smartcase = true
opt.cursorline = true
opt.termguicolors = true
opt.background = "dark"
opt.signcolumn = "yes"
opt.backspace = "indent,eol,start"
opt.clipboard:append("unnamedplus")
opt.completeopt = { "menu", "menuone", "noselect" }
opt.splitright = true
opt.splitbelow = true
opt.scrolloff = 4
opt.sidescrolloff = 8
opt.undofile = true
opt.updatetime = 250
opt.timeoutlen = 400
EOF
cat >"${core_dir}/keymaps.lua" <<'EOF'
vim.g.mapleader = " "
vim.g.maplocalleader = " "
local keymap = vim.keymap
keymap.set("n", "<leader>to", "<cmd>tabnew<CR>", {
  desc = "Open new tab",
})
keymap.set("n", "<leader>tx", "<cmd>tabclose<CR>", {
  desc = "Close current tab",
})
keymap.set("n", "<leader>w", "<cmd>write<CR>", {
  desc = "Save file",
})
keymap.set("n", "<leader>q", "<cmd>quit<CR>", {
  desc = "Quit",
})
keymap.set("n", "<Esc>", "<cmd>nohlsearch<CR>")
EOF
cat >"${plugins_dir}/colorscheme.lua" <<'EOF'
return {
  "catppuccin/nvim",
  name = "catppuccin",
  priority = 1000,
  config = function()
    require("catppuccin").setup({
      flavour = "macchiato",
    })
vim.cmd.colorscheme("catppuccin")
  end,
}
EOF
cat >"${plugins_dir}/indent-blankline.lua" <<'EOF'
return {
  "lukas-reineke/indent-blankline.nvim",
  event = { "BufReadPre", "BufNewFile" },
  main = "ibl",
  opts = {
    indent = {
      char = "│",
    },
    scope = {
      enabled = true,
    },
  },
}
EOF
cat >"${plugins_dir}/nvim-tree.lua" <<'EOF'
return {
  "nvim-tree/nvim-tree.lua",
  dependencies = {
    "nvim-tree/nvim-web-devicons",
  },
  config = function()
    vim.g.loaded_netrw = 1
    vim.g.loaded_netrwPlugin = 1
local nvimtree = require("nvim-tree")

nvimtree.setup({
  view = {
    width = 35,
    relativenumber = true,
  },

  renderer = {
    indent_markers = {
      enable = true,
    },

    icons = {
      glyphs = {
        folder = {
          arrow_closed = "",
          arrow_open = "",
        },
      },
    },
  },

  filters = {
    custom = {
      ".DS_Store",
    },
  },

  git = {
    ignore = false,
  },
})

vim.keymap.set("n", "<leader>ee", "<cmd>NvimTreeToggle<CR>", {
  desc = "Toggle file explorer",
})

vim.keymap.set("n", "<leader>ef", "<cmd>NvimTreeFindFileToggle<CR>", {
  desc = "Toggle file explorer on current file",
})
  end,
}
EOF
cat >"${plugins_dir}/nvim-cmp.lua" <<'EOF'
return {
  "hrsh7th/nvim-cmp",
  event = "InsertEnter",
  dependencies = {
    "hrsh7th/cmp-buffer",
    "hrsh7th/cmp-path",
    "hrsh7th/cmp-nvim-lsp",
{
  "L3MON4D3/LuaSnip",
  version = "v2.*",
},

"saadparwaiz1/cmp_luasnip",
"rafamadriz/friendly-snippets",
"onsails/lspkind.nvim",
  },
  config = function()
    local cmp = require("cmp")
    local luasnip = require("luasnip")
    local lspkind = require("lspkind")
require("luasnip.loaders.from_vscode").lazy_load()

cmp.setup({
  snippet = {
    expand = function(args)
      luasnip.lsp_expand(args.body)
    end,
  },

  mapping = cmp.mapping.preset.insert({
    ["<C-k>"] = cmp.mapping.select_prev_item(),
    ["<C-j>"] = cmp.mapping.select_next_item(),
    ["<C-b>"] = cmp.mapping.scroll_docs(-4),
    ["<C-f>"] = cmp.mapping.scroll_docs(4),
    ["<C-Space>"] = cmp.mapping.complete(),
    ["<C-e>"] = cmp.mapping.abort(),

    ["<CR>"] = cmp.mapping.confirm({
      select = false,
    }),

    ["<Tab>"] = cmp.mapping(function(fallback)
      if cmp.visible() then
        cmp.select_next_item()
      elseif luasnip.expand_or_jumpable() then
        luasnip.expand_or_jump()
      else
        fallback()
      end
    end, { "i", "s" }),

    ["<S-Tab>"] = cmp.mapping(function(fallback)
      if cmp.visible() then
        cmp.select_prev_item()
      elseif luasnip.jumpable(-1) then
        luasnip.jump(-1)
      else
        fallback()
      end
    end, { "i", "s" }),
  }),

  sources = cmp.config.sources({
    {
      name = "nvim_lsp",
    },
    {
      name = "luasnip",
    },
  }, {
    {
      name = "buffer",
    },
    {
      name = "path",
    },
  }),

  formatting = {
    format = lspkind.cmp_format({
      maxwidth = 50,
      ellipsis_char = "...",
    }),
  },
})
  end,
}
EOF
cat >"${plugins_dir}/treesitter.lua" <<'EOF'
return {
  "nvim-treesitter/nvim-treesitter",
  branch = "master",
  event = {
    "BufReadPost",
    "BufNewFile",
  },
  build = ":TSUpdate",
  dependencies = {
    {
      "windwp/nvim-ts-autotag",
      opts = {},
    },
  },
  config = function()
    local treesitter = require("nvim-treesitter.configs")
treesitter.setup({
  highlight = {
    enable = true,
  },

  indent = {
    enable = true,
  },

  ensure_installed = {
    "bash",
    "c",
    "css",
    "dockerfile",
    "gitignore",
    "graphql",
    "html",
    "javascript",
    "json",
    "lua",
    "markdown",
    "markdown_inline",
    "prisma",
    "query",
    "svelte",
    "tsx",
    "typescript",
    "vim",
    "vimdoc",
    "yaml",
  },

  auto_install = true,

  incremental_selection = {
    enable = true,

    keymaps = {
      init_selection = "<C-space>",
      node_incremental = "<C-space>",
      scope_incremental = false,
      node_decremental = "<BS>",
    },
  },
})
  end,
}
EOF
cat >"${nvim_dir}/.stylua.toml" <<'EOF'
column_width = 160
line_endings = "Unix"
indent_type = "Spaces"
indent_width = 2
quote_style = "AutoPreferSingle"
call_parentheses = "None"
EOF
}
bootstrap_neovim() {
    info "Installing Neovim plugins..."
"$NVIM_BIN" \
    --headless \
    "+Lazy! sync" \
    +qa

info "Neovim configuration installed successfully."
}
find_powershell
[[ -f "${SCRIPT_DIR}/requirements.txt" ]] || fail 
    "${SCRIPT_DIR}/requirements.txt was not found."
[[ -f "${SCRIPT_DIR}/ARLO.ps1" ]] || fail 
    "${SCRIPT_DIR}/ARLO.ps1 was not found."
readonly LOCAL_APP_DATA_WINDOWS="${LOCALAPPDATA:-$(get_windows_folder LocalApplicationData)}"
readonly USER_PROFILE_WINDOWS="${USERPROFILE:-$(get_windows_folder UserProfile)}"
readonly PROGRAM_FILES_WINDOWS="${PROGRAMFILES:-$(get_windows_folder ProgramFiles)}"
[[ -n "$LOCAL_APP_DATA_WINDOWS" ]] || fail 
    "Windows LocalAppData could not be located."
[[ -n "$USER_PROFILE_WINDOWS" ]] || fail 
    "The Windows user profile could not be located."
[[ -n "$PROGRAM_FILES_WINDOWS" ]] || fail 
    "Windows Program Files could not be located."
readonly LOCAL_APP_DATA_UNIX="$(to_unix_path "$LOCAL_APP_DATA_WINDOWS")"
readonly USER_PROFILE_UNIX="$(to_unix_path "$USER_PROFILE_WINDOWS")"
readonly PROGRAM_FILES_UNIX="$(to_unix_path "$PROGRAM_FILES_WINDOWS")"
TEMP_INSTALLERS=()
trap cleanup_installers EXIT
WINGET_BIN=""
find_winget || true
info "Checking for Python 3.12..."
PYTHON_CMD=()
if ! find_python; then
    info "No compatible Python installation found; installing Python 3.12..."
if [[ -n "$WINGET_BIN" ]]; then
    winget_install "Python.Python.3.12" || install_python_directly
else
    install_python_directly
fi

find_python || fail \
    "Python was installed, but python.exe could not be located."
fi
"${PYTHON_CMD[@]}" --version
ASSISTANT_NAME="$(
    cd -- "$SCRIPT_DIR"
    "${PYTHON_CMD[@]}" -c 'from agent import Assistant; print(Assistant().name)'
)"
readonly ASSISTANT_NAME
readonly VENV_DIR="${SCRIPT_DIR}/.venv"
readonly VENV_DIR_WINDOWS="$(to_windows_path "$VENV_DIR")"
readonly REQUIREMENTS_WINDOWS="$(to_windows_path "${SCRIPT_DIR}/requirements.txt")"
readonly VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
info "Creating or updating the virtual environment..."
"${PYTHON_CMD[@]}" -m venv "$VENV_DIR_WINDOWS"
[[ -x "$VENV_PYTHON" ]] || fail 
    "The virtual environment could not be created at ${VENV_DIR}."
info "Installing dependencies from requirements.txt..."
"$VENV_PYTHON" -m pip install 
    --upgrade 
    pip 
    setuptools 
    wheel
"$VENV_PYTHON" -m pip install 
    --requirement "$REQUIREMENTS_WINDOWS"
"$VENV_PYTHON" -m pip check
info "Checking for Git..."
GIT_BIN=""
if ! find_git; then
    [[ -n "$WINGET_BIN" ]] || fail 
        "Git is required by Neovim plugins, but WinGet is unavailable."
info "Git was not found; installing it..."

winget_install "Git.Git"

find_git || fail \
    "Git was installed, but git.exe could not be located."
fi
"$GIT_BIN" --version
info "Checking for Neovim..."
NVIM_BIN=""
if ! find_neovim; then
    [[ -n "$WINGET_BIN" ]] || fail 
        "Neovim is not installed and WinGet is unavailable."
info "Neovim was not found; installing it..."

winget_install "Neovim.Neovim"

find_neovim || fail \
    "Neovim was installed, but nvim.exe could not be located."
fi
"$NVIM_BIN" --version
configure_neovim
bootstrap_neovim

VOICE_NAME="es_MX-claude-high"
VOICE_DIR="$SCRIPT_DIR/src/voices"
mkdir -p "$VOICE_DIR"
if [[ ! -f "$VOICE_DIR/$VOICE_NAME.onnx" ]] ||
   [[ ! -f "$VOICE_DIR/$VOICE_NAME.onnx.json" ]]; then
    info "Downloading ARLO's voice ($VOICE_NAME)..."
    "$VENV_PYTHON" -m piper.download_voices \
        --download-dir "$VOICE_DIR" \
        "$VOICE_NAME"
else
    info "ARLO's voice is already installed."
fi

info "Checking for Ollama..."
OLLAMA_BIN=""
if ! find_ollama; then
    info "Ollama was not found; installing it..."
if [[ -n "$WINGET_BIN" ]]; then
    winget_install "Ollama.Ollama" || install_ollama_directly
else
    install_ollama_directly
fi

find_ollama || fail \
    "Ollama was installed, but ollama.exe could not be located."
fi
"$OLLAMA_BIN" --version
ensure_ollama_server
info "Downloading/verifying ${ARLO_MODEL} (approximately 9.3 GB)..."
"$OLLAMA_BIN" pull "$ARLO_MODEL"
readonly ARLO_SCRIPT="$(to_windows_path "${SCRIPT_DIR}/ARLO.ps1")"
cleanup_installers
trap - EXIT
info "Installation complete. Starting ${ASSISTANT_NAME}..."
exec "$POWERSHELL_BIN" 
    -NoProfile 
    -ExecutionPolicy Bypass 
    -File "$ARLO_SCRIPT"
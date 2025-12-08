#!/bin/sh
set -e

SPORK_HOME="$HOME/.spork"
BIN_DIR="$HOME/.local/bin"
VENV_DIR="$SPORK_HOME/venv"

echo "Installing Spork to $SPORK_HOME"

# Check for Python 3.9+
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: Python 3 is required."
    exit 1
fi

# Clean update
rm -rf "$VENV_DIR"
mkdir -p "$SPORK_HOME"

# Create venv
echo "   Creating virtual environment..."
python3 -m venv "$VENV_DIR"

# Install Spork
echo "   Downloading spork-lang from PyPI..."
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q spork-lang

# Symlink
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/spork" "$BIN_DIR/spork"

echo ""
echo "Spork installed successfully!"
echo "   Binary location: $BIN_DIR/spork"
echo ""

# Path check
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "   Warning: $BIN_DIR is not in your PATH."
       echo "   Add this to your shell config: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

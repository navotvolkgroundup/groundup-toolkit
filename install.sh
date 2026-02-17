#!/bin/bash
# GroundUp Toolkit - Server Installation Script
# Sets up all dependencies and configures cron jobs
#
# Usage: sudo bash install.sh
#
# Prerequisites:
#   - Ubuntu/Debian server (tested on Ubuntu 22.04 / 24.04)
#   - Root or sudo access
#   - config.yaml filled out (copy from config.example.yaml)
#   - .env filled out (copy from .env.example)

set -e

TOOLKIT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "=========================================="
echo "  GroundUp Toolkit Installer"
echo "=========================================="
echo "Installing from: $TOOLKIT_DIR"
echo ""

# --- Root check ---
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (or with sudo)."
    echo "  sudo bash install.sh"
    exit 1
fi

# --- Pre-flight checks ---
if [ ! -f "$TOOLKIT_DIR/config.yaml" ]; then
    echo "ERROR: config.yaml not found."
    echo "  cp config.example.yaml config.yaml"
    echo "  Then fill in your values and re-run."
    exit 1
fi

if [ ! -f "$TOOLKIT_DIR/.env" ]; then
    echo "ERROR: .env not found."
    echo "  cp .env.example .env"
    echo "  Then fill in your API keys and re-run."
    exit 1
fi

echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv jq curl ca-certificates gnupg > /dev/null 2>&1
echo "  Done."

echo ""
echo "[2/7] Installing Node.js 18+..."
# Check if Node.js >= 18 is already installed
NODE_OK=false
if command -v node &> /dev/null; then
    NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 18 ] 2>/dev/null; then
        NODE_OK=true
        echo "  Node.js already installed: $(node -v)"
    fi
fi

if [ "$NODE_OK" = false ]; then
    echo "  Installing Node.js 18 via NodeSource..."
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg 2>/dev/null
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_18.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
    apt-get update -qq
    apt-get install -y -qq nodejs > /dev/null 2>&1
    echo "  Installed: $(node -v)"
fi

echo ""
echo "[3/7] Installing OpenClaw..."
if command -v openclaw &> /dev/null; then
    echo "  OpenClaw already installed: $(openclaw --version)"
else
    npm install -g --ignore-scripts openclaw
    echo "  Installed: $(openclaw --version)"
fi

echo ""
echo "[4/7] Installing gog CLI (Google Workspace)..."
if command -v gog &> /dev/null; then
    echo "  gog already installed"
else
    npm install -g --ignore-scripts gog
    echo "  Installed gog CLI"
fi

echo ""
echo "[5/7] Installing Python dependencies..."
# Use a virtual environment to avoid PEP 668 "externally managed" errors
VENV_DIR="$TOOLKIT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "  Created virtual environment at .venv/"
fi
"$VENV_DIR/bin/pip" install -q pytz requests pyyaml anthropic 2>/dev/null
echo "  Done."
echo "  NOTE: Python scripts should be run with: $TOOLKIT_DIR/.venv/bin/python3"
echo "        Or activate first: source $TOOLKIT_DIR/.venv/bin/activate"

echo ""
echo "[6/7] Installing Node.js dependencies for meeting-bot..."
if [ -d "$TOOLKIT_DIR/skills/meeting-bot" ] && [ -f "$TOOLKIT_DIR/skills/meeting-bot/package.json" ]; then
    cd "$TOOLKIT_DIR/skills/meeting-bot"
    npm install --quiet --ignore-scripts 2>/dev/null
    cd "$TOOLKIT_DIR"
    echo "  Done."
else
    echo "  Skipped (meeting-bot not found)."
fi

# Install js-yaml for any scripts that need YAML config parsing in Node.js
echo "  Installing js-yaml (YAML parser for Node.js config loader)..."
cd "$TOOLKIT_DIR"
npm install --save --ignore-scripts js-yaml 2>/dev/null
echo "  Done."

echo ""
echo "[7/7] Setting up environment..."

# Load .env safely (line-by-line, no command substitution execution)
while IFS='=' read -r key value; do
    # Skip comments and blank lines
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    # Strip leading/trailing whitespace from key
    key=$(echo "$key" | xargs)
    # Only export valid variable names
    [[ "$key" =~ ^[A-Za-z_][A-Za-z_0-9]*$ ]] && export "$key=$value"
done < "$TOOLKIT_DIR/.env"

# Make scripts executable
chmod +x "$TOOLKIT_DIR/skills/"*/[a-z]* 2>/dev/null || true
chmod +x "$TOOLKIT_DIR/scripts/"*.sh 2>/dev/null || true

# Create symlink for easy access
if [ ! -L /usr/local/bin/groundup-toolkit ]; then
    ln -sf "$TOOLKIT_DIR" /usr/local/bin/groundup-toolkit
fi

echo "  Done."

echo ""
echo "=========================================="
echo "  Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "  1. Activate the Python virtual environment:"
echo "     source $TOOLKIT_DIR/.venv/bin/activate"
echo ""
echo "  2. Set up Google OAuth:"
echo "     gog auth login"
echo ""
echo "  3. Connect WhatsApp:"
echo "     openclaw channels login"
echo "     (scan QR code from your phone)"
echo ""
echo "  4. Start the OpenClaw gateway:"
echo "     nohup openclaw gateway > /var/log/openclaw-gateway.log 2>&1 &"
echo ""
echo "  5. Set up cron jobs (edit as needed):"
echo "     crontab -e"
echo "     # Then paste from cron/crontab.example"
echo ""
echo "  6. Test that everything works:"
echo "     openclaw channels status"
echo "     bash scripts/health-check.sh"
echo ""
echo "See docs/setup-guide.md for detailed instructions."

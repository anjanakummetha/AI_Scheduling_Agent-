#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Lexi iMessage Bridge — Mac Setup Script
# Run this on your Mac to install and configure the OpenClaw iMessage gateway.
# ─────────────────────────────────────────────────────────────────────────────
set -e

# ── Config ────────────────────────────────────────────────────────────────────
# Set this to your server's public URL (e.g. https://your-server.com)
# or use ngrok: ngrok http 8000
LEXI_SERVER_URL="${LEXI_SERVER_URL:-http://localhost:8000}"
COMPOSIO_API_KEY="${COMPOSIO_API_KEY:-}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "  ══════════════════════════════════════════"
echo "   Lexi iMessage Bridge — Mac Setup"
echo "  ══════════════════════════════════════════"
echo ""

# ── 1. Check macOS ─────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  echo -e "${RED}Error: This script must be run on a Mac (macOS).${NC}"
  exit 1
fi
echo -e "${GREEN}✓ macOS detected${NC}"

# ── 2. Check Homebrew ──────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo -e "${YELLOW}Installing Homebrew...${NC}"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
echo -e "${GREEN}✓ Homebrew ready${NC}"

# ── 3. Install imsg ────────────────────────────────────────────────────────
if ! command -v imsg &>/dev/null; then
  echo -e "${YELLOW}Installing imsg CLI...${NC}"
  brew install steipete/formulae/imsg
fi
echo -e "${GREEN}✓ imsg installed at: $(which imsg)${NC}"

# ── 4. Check Node.js ──────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
  echo -e "${YELLOW}Installing Node.js via Homebrew...${NC}"
  brew install node
fi
echo -e "${GREEN}✓ Node.js: $(node --version)${NC}"

# ── 5. Clone secure-openclaw ─────────────────────────────────────────────
OPENCLAW_DIR="$HOME/.lexi-openclaw"
if [ ! -d "$OPENCLAW_DIR" ]; then
  echo -e "${YELLOW}Cloning ComposioHQ/secure-openclaw...${NC}"
  git clone https://github.com/ComposioHQ/secure-openclaw.git "$OPENCLAW_DIR"
fi
echo -e "${GREEN}✓ OpenClaw at: $OPENCLAW_DIR${NC}"

cd "$OPENCLAW_DIR"
npm install --silent
echo -e "${GREEN}✓ npm dependencies installed${NC}"

# ── 6. Write OpenClaw config ─────────────────────────────────────────────
IMSG_PATH="$(which imsg)"
MESSAGES_DB="$HOME/Library/Messages/chat.db"

cat > "$OPENCLAW_DIR/config.json" <<EOF
{
  "composioApiKey": "${COMPOSIO_API_KEY}",
  "channels": {
    "imessage": {
      "enabled": true,
      "cliPath": "${IMSG_PATH}",
      "dbPath": "${MESSAGES_DB}",
      "dmPolicy": "allow",
      "webhook": {
        "url": "${LEXI_SERVER_URL}/webhooks/imessage",
        "method": "POST"
      }
    }
  },
  "agent": {
    "name": "Lexi",
    "webhookMode": true
  }
}
EOF

echo ""
echo -e "${GREEN}✓ OpenClaw config written to: $OPENCLAW_DIR/config.json${NC}"

# ── 7. Permissions reminder ───────────────────────────────────────────────
echo ""
echo -e "${YELLOW}ACTION REQUIRED — Grant Mac permissions:${NC}"
echo ""
echo "  1. Open System Settings → Privacy & Security → Full Disk Access"
echo "     → Add Terminal (or your terminal app)"
echo ""
echo "  2. Open System Settings → Privacy & Security → Automation"
echo "     → Allow your terminal to control Messages"
echo ""
echo "  3. Make sure Messages.app is open and signed in with your Apple ID"
echo ""

# ── 8. Start the gateway ──────────────────────────────────────────────────
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Setup complete! To start the iMessage bridge:${NC}"
echo ""
echo "  cd $OPENCLAW_DIR && node gateway.js"
echo ""
echo "  Or run in the background:"
echo "  nohup node $OPENCLAW_DIR/gateway.js > /tmp/lexi-imsg.log 2>&1 &"
echo ""
echo "  Server webhook URL: ${LEXI_SERVER_URL}/webhooks/imessage"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "You can now iMessage anyone on this Mac and they can chat with Lexi."
echo -e "Chat from your iPhone by messaging the same Apple ID signed into Messages."

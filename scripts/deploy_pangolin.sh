#!/usr/bin/env bash
# Deploy mtg-agent to pangolin. Run from your local machine.
# Usage: bash scripts/deploy_pangolin.sh
#
# Prerequisites:
#   1. MongoDB installed on pangolin (run scripts/setup_mongo.sh first)
#   2. .env file present at /home/admin/mtg_agent/.env on pangolin

set -euo pipefail

REMOTE="pangolin"
REMOTE_DIR="/home/admin/mtg_agent"

echo "==> Syncing project to pangolin..."
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.env' \
    /home/john/Projects/mcps/mtg-agent/ "${REMOTE}:${REMOTE_DIR}/"

echo "==> Installing Python dependencies..."
ssh "$REMOTE" "
    cd ${REMOTE_DIR}
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q -e .
"

echo "==> Installing systemd service..."
ssh "$REMOTE" "
    sudo cp ${REMOTE_DIR}/deploy/mtg-agent.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable mtg-agent
    sudo systemctl restart mtg-agent
    sleep 2
    sudo systemctl status mtg-agent --no-pager
"

echo ""
echo "Deployed. MCP server running on pangolin:8765 (stdio mode)."
echo "Check logs: ssh pangolin 'journalctl -u mtg-agent -f'"

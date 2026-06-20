#!/usr/bin/env bash
# Install MongoDB Community Edition 8.0 on Ubuntu and start it as a service.
# Run once on pangolin: bash scripts/setup_mongo.sh

set -euo pipefail

echo "==> Installing MongoDB 8.0..."
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc \
    | sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor

echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" \
    | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list

sudo apt-get update -qq
sudo apt-get install -y mongodb-org

echo "==> Enabling and starting mongod..."
sudo systemctl daemon-reload
sudo systemctl enable mongod
sudo systemctl start mongod

echo "==> MongoDB status:"
sudo systemctl status mongod --no-pager

echo ""
echo "MongoDB is running on localhost:27017 (no auth — localhost only)."
echo "Next: run 'python scripts/init_db.py' to create indexes."

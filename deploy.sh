#!/bin/bash
set -e

echo "=== Pulling Latest Code ==="
git pull origin main

echo "=== Updating Dependencies ==="
source venv/bin/activate
pip install -r requirements.txt

echo "=== Running Database Schema Migrations ==="
python3 app/database.py

echo "=== Restarting FastAPI Application ==="
sudo systemctl restart recipe-app

echo "=== Deployment Complete ==="

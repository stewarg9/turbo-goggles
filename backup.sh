#!/bin/bash
BACKUP_DIR="/home/pi/recipe-app/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

# Safe online backup command
sqlite3 /home/pi/recipe-app/recipes.db ".backup '$BACKUP_DIR/recipes_$TIMESTAMP.db'"

# Retain only the last 14 days of backups
find "$BACKUP_DIR" -type f -name "*.db" -mtime +14 -delete

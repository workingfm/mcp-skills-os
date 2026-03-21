#!/bin/bash
set -e

# ── Git init (solo al primo avvio, se .git non esiste) ─────────────────────
if [ ! -d "/app/.git" ]; then
  echo "[skill-os] Prima esecuzione: inizializzazione Git repository..."
  cd /app
  git init -q
  git config user.email "agent@skill-os.local"
  git config user.name  "skill-os-agent"
  # Mark /app as safe directory (needed when volume-mounted with different owner)
  git config --global --add safe.directory /app
  git add .
  git commit -q --message="feat: initial skill-os v1.2 setup"
  echo "[skill-os] Git inizializzato."
else
  # Ensure safe.directory is set for existing repos
  git config --global --add safe.directory /app 2>/dev/null || true
fi

# ── Cartelle runtime ────────────────────────────────────────────────────────
mkdir -p /app/logs /app/pending_approvals

# ── Avvio server ────────────────────────────────────────────────────────────
cd /app
exec python server/main.py

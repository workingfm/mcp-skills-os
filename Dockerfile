# syntax=docker/dockerfile:1
FROM python:3.11.12-slim AS base

LABEL maintainer="skill-os" \
      version="1.2" \
      description="skill-os — MCP Skill Registry auto-evolutivo"

# Git necessario per il versioning automatico delle skill
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dipendenze Python (layer separato per cache efficiente)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codice sorgente
COPY server/      ./server/
COPY skills/      ./skills/
COPY entrypoint.sh ./

# Cartelle runtime + permessi in un singolo layer
RUN chmod +x entrypoint.sh \
    && mkdir -p logs pending_approvals \
    && groupadd -r skillos \
    && useradd --no-log-init -r -g skillos -d /app skillos \
    && chown -R skillos:skillos /app

USER skillos

ENTRYPOINT ["./entrypoint.sh"]

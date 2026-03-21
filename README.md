# skill-os 🧠
### MCP Skill Registry Auto-Evolutivo

---

## Installazione — 1 comando

```bash
# 1. Estrai lo zip dove vuoi
unzip skill-os-docker.zip
cd skill-os-docker

# 2. Build + avvio (la prima volta impiega ~60s per scaricare l'immagine)
docker compose build

# 3. Apri questa cartella in Claude Code → rileva .mcp.json in automatico
```

**Fine.** Claude Code si connette al server via Docker al primo messaggio.

---

## Configurazione opzionale

```bash
# Copia il file di configurazione
cp .env.example .env

# Apri .env e aggiungi la tua API key Anthropic (opzionale)
# Senza: il sistema funziona con scoring euristico
# Con: eval LLM-powered + proposte automatiche di miglioramento
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Come funziona (architettura in 30 secondi)

```
Tu / Claude Code
      │
      │  stdio (MCP)
      ▼
┌─────────────────────────────────┐
│  skill-os container             │
│                                 │
│  main.py  ← FastMCP server      │
│  registry ← legge /skills/*     │
│  executor ← lancia sandbox      │
│                                 │
└──────────┬──────────────────────┘
           │ docker run (sandbox)
           ▼
    python:3.11-slim container
    (esegue il codice utente,
     isolato, no rete, 256MB RAM)
```

**3 skill incluse:**

| Skill | Cosa fa |
|-------|---------|
| `python_exec` | Esegue codice Python in sandbox Docker |
| `skill_manager` | Valuta e migliora le skill (eval + upsert) |
| `orchestrator` | Ciclo autonomo di auto-miglioramento |

---

## Comandi utili in Claude Code

```
# Scopri le skill disponibili
list_skills()

# Esegui codice Python
execute("python_exec:run_code", code="import pandas as pd; print(pd.__version__)")

# Valuta la qualità di una skill
execute("skill_manager:eval_skill", code='{"skill_id": "python_exec"}')

# Lancia un ciclo di miglioramento manuale
execute("orchestrator:run_cycle", code="")

# Vedi proposte in attesa di approvazione
list_pending_approvals()

# Approva una proposta
approve_pending("abc123", approve=True)
```

---

## Attivare l'orchestratore autonomo

```bash
# In .env:
ORCHESTRATOR_ENABLED=true
ANTHROPIC_API_KEY=sk-ant-...

# Poi riavvia:
docker compose build
```

L'orchestratore analizza i log ogni 30 minuti, sceglie la skill da migliorare,
lancia una valutazione automatica e — se trova margini — genera una proposta.
**Non applica nulla senza la tua approvazione.**

---

## Aggiungere una nuova skill

```bash
# Crea la cartella (il server la rileva automaticamente, no restart)
mkdir -p skills/mia_skill/tools
cp skills/python_exec/manifest.json skills/mia_skill/manifest.json
# Modifica id, description, entrypoint nel manifest
# Scrivi system_prompt.md e tools/run.py
```

---

## Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| `docker: command not found` | Installa Docker Desktop |
| Claude Code non trova il server | Assicurati di aprire la cartella `skill-os-docker/` in Claude Code |
| Sandbox Docker non funziona | Imposta `SKILL_OS_SANDBOX=mock` in `.env` |
| Git error al primo avvio | Normale — `entrypoint.sh` inizializza il repo automaticamente |

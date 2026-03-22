# skill-os

## MCP Skill Registry con ASR (Adaptive Skill Reinforcement)

Un server MCP (Model Context Protocol) con un sistema di **Reinforcement Learning applicato all'evoluzione di tool AI**. Le skill si evolvono automaticamente quando falliscono, convergendo verso la perfezione attraverso l'uso reale. Zero API key necessarie — il ragionamento LLM passa attraverso MCP sampling con l'abbonamento Claude Pro.

https://github.com/workingfm/mcp-skills-os/raw/main/assets/skill-os-explainer.mp4

---

## Quick Start

```bash
git clone https://github.com/workingfm/mcp-skills-os.git
cd mcp-skills-os
docker compose build
```

Apri la cartella in Claude Code. Il file `.mcp.json` viene rilevato automaticamente e il server si connette via Docker.

---

## Come funziona

```
Agente AI (Claude Code / qualsiasi client MCP)
      |
      |  stdio (MCP protocol)
      v
+-----------------------------------+
|  skill-os container (Docker)      |
|                                   |
|  FastMCP server (main.py)         |
|  Skill Registry (hot-reload)      |
|  Executor (sandbox Docker)        |
|  Safety engine + auto-approve     |
|  ASR Engine (Adaptive RL)         |
|  Orchestrator (background loop)   |
+----------------+------------------+
                 |  docker run (sandbox)
                 v
          python:3.11-slim
          (codice isolato,
           no rete, 256MB RAM)
```

### MCP Sampling: come usa il tuo abbonamento Pro

Il server non chiama API esterne. Quando serve ragionamento LLM (creare skill, valutare, proporre miglioramenti), usa **MCP sampling**: il server invia una richiesta al client (Claude Code), che la processa usando la tua sessione Claude Pro attiva. Nessun costo aggiuntivo.

```
Agente --> skill-os: "crea una skill per analisi CSV"
skill-os --> ctx.sample("genera manifest + codice...")
ctx.sample --> Claude Code: richiesta di sampling
Claude Code --> abbonamento Pro: genera la risposta
risposta --> skill-os: skill generata
skill-os --> Agente: "skill pronta, approva o rifiuta"
```

---

## Tool MCP disponibili

| Tool | Descrizione |
|------|-------------|
| `list_skills()` | Catalogo completo delle skill con tool e flag safety |
| `get_prompt(skill_id)` | Carica il system prompt di una skill (lazy loading) |
| `execute(tool_ref, code, input_data)` | Esegue un tool in sandbox. Formato: `skill_id:tool_id` |
| `create_skill(skill_id, description)` | Genera una nuova skill completa via LLM |
| `approve_pending(approval_id, approve)` | Approva o rifiuta una proposta |
| `list_pending_approvals()` | Elenca le proposte in attesa |
| `skill_fitness(skill_id)` | Stato RL della skill: fitness, generazione, curva di apprendimento |

---

## Workflow per agenti AI

### 1. Scoprire e usare skill esistenti

```python
# L'agente scopre cosa sa fare
list_skills()
# --> python_exec, skill_manager, orchestrator

# Carica il contesto della skill
get_prompt("python_exec")

# Esegue codice in sandbox
execute("python_exec:run_code", code="import pandas as pd; print(pd.__version__)")
```

### 2. Creare skill on-demand

Quando l'agente ha bisogno di una capacita' che non esiste, la crea al volo:

```python
# Creazione esplicita
create_skill("csv_analyzer", "analizza file CSV, produce statistiche e grafici")
# --> genera manifest.json + system_prompt.md + tools/run.py via LLM
# --> in attesa di approvazione (o auto-approvata se sicura)

# Creazione implicita: se la skill non esiste, execute() tenta di generarla
execute("csv_analyzer:run", code='{"file": "data.csv"}')
# --> skill non trovata --> generazione automatica via LLM
```

### 3. Ciclo di auto-evoluzione

L'agente puo' valutare e migliorare le skill esistenti:

```python
# Valuta una skill (score 0-10 + critique LLM)
execute("skill_manager:eval_skill", code='{"skill_id": "python_exec"}')

# Lancia un ciclo completo di miglioramento
execute("orchestrator:run_cycle")
# --> analizza log --> sceglie skill target --> eval --> propone miglioramento

# Approva la proposta
approve_pending("abc123", approve=True)
# --> applica changes su disco --> git commit --> hot-reload
```

### 4. Workflow completamente autonomo

Con la configurazione giusta, l'agente si auto-migliora senza intervento umano:

```bash
# .env
ORCHESTRATOR_ENABLED=true     # loop background ogni 30 min
AUTO_APPROVE_SAFE=true        # approva automaticamente le skill sicure
AUTO_APPROVE_MIN_SCORE=7.0    # soglia minima per auto-approve evoluzione
```

Il ciclo autonomo:
1. L'orchestratore valuta tutte le skill in background
2. Se una skill ha score basso, genera una proposta di miglioramento
3. Le proposte sicure (no side_effects, idempotent) vengono auto-approvate
4. Le proposte con side_effects restano in `pending_approvals/` per review umana
5. Ogni modifica viene committata in Git con versioning automatico

### 5. ASR — Adaptive Skill Reinforcement (v2.0)

Le skill si evolvono automaticamente quando falliscono. Nessun ciclo programmato — l'evoluzione e' **on-demand**, innescata dall'uso reale:

```python
# Esegui una skill — se fallisce, si evolve automaticamente
execute("python_exec:run_code", code="import openpyxl; print('ok')")

# Output:
# ⚡ Skill 'python_exec' in evoluzione — analisi del fallimento...
#    Diagnosi: ENVIRONMENT / missing_dependency (confidence: 0.95)
#    Mutazione: manifest.json → aggiunta dipendenza 'openpyxl'
#    Retry in corso...
# --> {"status": "ok", "stdout": "ok\n", "asr_info": {"evolved": true}}

# La prossima volta funziona al primo colpo!

# Consulta lo stato RL di una skill
skill_fitness("python_exec")
# --> fitness: 8.7/10, generation: 4, status: "stable"
# --> fitness_curve: [5.0, 6.1, 7.2, 8.7]  (curva di apprendimento)
```

**Come funziona il ciclo RL:**

```
Richiesta --> Skill invocata --> Successo? --> Risultato (skill resta ferma)
                                    |  No
                              Diagnosi automatica
                                    |
                              Snapshot pre-mutazione
                                    |
                              Mutazione (deterministica o LLM)
                                    |
                              Retry --> Successo? --> Skill evoluta per sempre
                                           |  No
                                        Rollback a snapshot precedente
```

| Concetto RL | skill-os ASR |
|---|---|
| Reward | +1.0 successo, -0.5 errore, -1.0 crash |
| Fitness | EMA dei reward, scala 0-10 |
| Mutazione | Deterministica (dependency, timeout) o LLM-guided (codice, prompt) |
| Convergenza | 10 successi consecutivi → skill "stabile" |
| Safety | Snapshot + rollback, solo skill sandboxed, 3 rollback → "degraded" |

```bash
# Configurazione ASR (.env)
ASR_ENABLED=true                  # attiva evoluzione adattiva
ASR_MAX_MUTATIONS_PER_DAY=5       # max mutazioni giornaliere per skill
ASR_COOLDOWN_SECONDS=300          # cooldown tra mutazioni (5 min)
```

---

## Struttura di una skill

Ogni skill vive in `skills/<skill_id>/` con questa struttura:

```
skills/
  csv_analyzer/
    manifest.json       # definizione: id, versione, tool, safety, runtime
    system_prompt.md    # istruzioni per l'LLM su come usare la skill
    tools/
      run.py            # codice eseguibile (entrypoint: main())
```

### manifest.json

```json
{
  "id": "csv_analyzer",
  "version": "1.0.0",
  "description": "Analizza file CSV e produce statistiche",
  "system_prompt_uri": "skill://csv_analyzer/system_prompt.md",
  "tools": [{
    "id": "run",
    "description": "Analizza un CSV e ritorna statistiche",
    "entrypoint": "tools/run.py:main",
    "execution": {
      "tier": "server",
      "sandbox": "docker",
      "timeout_seconds": 30
    },
    "safety": {
      "side_effects": false,
      "requires_human_approval": false,
      "idempotent": true
    },
    "runtime": {
      "language": "python",
      "version": "3.11",
      "dependencies": ["pandas"]
    }
  }]
}
```

### Safety flags

| Flag | Significato | Auto-approve |
|------|-------------|--------------|
| `side_effects: false` | Non modifica stato esterno | Si |
| `side_effects: true` | Scrive file, chiama API, etc. | No (richiede review) |
| `requires_human_approval: true` | Sempre approvazione manuale | No |
| `idempotent: true` | Eseguibile piu' volte senza effetti diversi | Requisito per auto-approve |

---

## Configurazione

### Variabili d'ambiente

```bash
# Sandbox
SKILL_OS_SANDBOX=mock          # "mock" (dev) | "docker" (produzione)

# Orchestratore autonomo
ORCHESTRATOR_ENABLED=false     # "true" per attivare il loop background
ORCHESTRATOR_INTERVAL=1800     # intervallo in secondi (default: 30 min)

# Auto-approvazione
AUTO_APPROVE_SAFE=false        # "true" per auto-approvare skill sicure
AUTO_APPROVE_MIN_SCORE=7.0     # score minimo per auto-approve evoluzione

# Altro
APPROVAL_TIMEOUT_SECONDS=300   # timeout per approvazioni manuali via upsert tool

# ASR — Adaptive Skill Reinforcement
ASR_ENABLED=true                  # attiva/disattiva evoluzione adattiva
ASR_MAX_MUTATIONS_PER_DAY=5       # max mutazioni giornaliere per skill
ASR_STABILITY_THRESHOLD=10        # successi consecutivi per status "stable"
ASR_DEGRADED_AFTER_ROLLBACKS=3    # rollback consecutivi per status "degraded"
ASR_COOLDOWN_SECONDS=300          # cooldown tra mutazioni sulla stessa skill
```

### Modalita' operative

| Modalita' | Config | Comportamento |
|-----------|--------|---------------|
| **Manuale** | default | L'agente chiede, tu approvi tutto |
| **Semi-autonomo** | `AUTO_APPROVE_SAFE=true` | Skill sicure auto-approvate, le altre richiedono review |
| **Autonomo** | `ORCHESTRATOR_ENABLED=true` + `AUTO_APPROVE_SAFE=true` | Auto-evoluzione completa in background |
| **ASR** | `ASR_ENABLED=true` | Le skill si evolvono on-demand quando falliscono (RL adattivo) |

---

## Uso con agenti AI

### Claude Code (integrato)

Il file `.mcp.json` nel progetto configura la connessione:

```json
{
  "mcpServers": {
    "skill-os": {
      "command": "docker",
      "args": ["compose", "run", "--rm", "-T", "skill-os"]
    }
  }
}
```

Claude Code rileva automaticamente `.mcp.json` e si connette al server.

### Agente custom (qualsiasi client MCP)

Qualsiasi client che implementa il protocollo MCP su stdio puo' connettersi:

```bash
# Il server si avvia su stdio
docker compose run --rm -T skill-os

# Invia messaggi JSON-RPC sulla stdin
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
```

Per costruire un agente custom con Claude Agent SDK:

```python
from anthropic import Anthropic
from anthropic.agent import Agent

agent = Agent(
    model="claude-sonnet-4-20250514",
    mcp_servers=[{
        "command": "docker",
        "args": ["compose", "run", "--rm", "-T", "skill-os"],
        "cwd": "/path/to/mcp-skills-os"
    }]
)

# L'agente puo' ora usare list_skills(), create_skill(), execute(), etc.
result = agent.run("Crea una skill per analizzare file JSON e usala")
```

---

## Sicurezza

- Il codice utente gira in container Docker isolati (no rete, 256MB RAM, read-only)
- Le skill con `side_effects: true` richiedono sempre approvazione umana
- Rate limiting: max 3 upsert/skill/giorno
- Ogni modifica viene tracciata con Git (commit automatici)
- L'auto-approve ha guardrail basati sui safety flag del manifest

---

## Skill incluse

| Skill | Descrizione | Tool |
|-------|-------------|------|
| `python_exec` | Esegue codice Python in sandbox Docker | `run_code` |
| `skill_manager` | Valuta e aggiorna le skill | `eval_skill`, `upsert_skill` |
| `orchestrator` | Ciclo autonomo di auto-evoluzione | `run_cycle` |

---

## Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| `docker: command not found` | Installa Docker Desktop |
| Claude Code non trova il server | Apri la cartella `mcp-skills-os/` in Claude Code |
| Sandbox Docker non funziona | Imposta `SKILL_OS_SANDBOX=mock` in `.env` |
| `on_startup` error | Versione FastMCP incompatibile, usa `>=2.0.0` |
| Skill non appare dopo creazione | Verifica `approve_pending()` o controlla i log |

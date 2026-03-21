# ASR — Adaptive Skill Reinforcement

**Data:** 2026-03-21
**Versione target:** skill-os v2.0
**Stato:** Approvato

## Concept

Reinforcement Learning applicato all'evoluzione di tool AI MCP attraverso feedback d'uso reale. Le skill si evolvono automaticamente quando falliscono, convergendo verso la perfezione attraverso pressione d'uso reale.

Nessuna evoluzione casuale. Nessun ciclo programmato. L'evoluzione avviene **on-demand**, innescata dal fallimento, visibile all'utente, con rollback automatico se la mutazione peggiora le cose.

## Principi

- **Evoluzione guidata dal fallimento**: una skill si evolve solo quando fallisce. Se funziona, resta ferma.
- **Visibile ma automatica**: l'utente vede il feedback dell'evoluzione in tempo reale.
- **Evoluzione totale**: prompt, codice e manifest possono tutti essere mutati.
- **Snapshot & rollback**: ogni mutazione e' preceduta da snapshot. Se peggiora, rollback istantaneo.
- **Convergenza**: dopo N successi consecutivi, la skill diventa "stabile" e non viene piu' toccata.
- **Safety-aware**: le mutazioni rispettano i safety flag del manifest. Skill con sandbox=none/host non vengono mai auto-mutate.
- **Concurrency-safe**: scritture atomiche al fitness store (write-to-temp + rename) con asyncio lock per skill.

## Mappatura RL

| RL Classico | Skill-OS ASR |
|---|---|
| Stato | Versione corrente della skill (prompt + codice + manifest) |
| Azione | Mutazione (cosa cambiare nella skill) |
| Reward | Esito dell'esecuzione (+1.0 successo, -0.5 errore, -1.0 crash/timeout) |
| Policy | Strategia di mutazione guidata dall'analisi del fallimento |
| Episodio | Singola invocazione -> feedback -> eventuale evoluzione |
| Convergenza | Skill che non fallisce piu' -> reward stabile -> nessuna mutazione |

## Architettura

```
                         Utente / Agente AI
                                |
                         execute("skill:tool", ...)
                                |
                                v
+-----------------------------------------------------+
|  main.py - execute()                                 |
|                                                      |
|  1. Esegue la skill normalmente                      |
|  2. Valuta il risultato -> reward signal             |
|  3. Se reward >= soglia -> ritorna risultato         |
|  4. Se reward < soglia -> chiama Evolution Engine    |
+-----------------------------------------------------+
                                |
                                v
+-----------------------------------------------------+
|  evolution.py - ASR Engine                           |
|                                                      |
|  +-------------+  +--------------+  +-----------+   |
|  | Fitness     |  | Failure      |  | Mutation  |   |
|  | Tracker     |  | Analyzer     |  | Strategy  |   |
|  +------+------+  +------+-------+  +-----+-----+  |
|         |                |                |          |
|         v                v                v          |
|  +----------------------------------------------+   |
|  | Snapshot Manager                              |   |
|  | save() -> rollback() -> compare()             |   |
|  +----------------------------------------------+   |
+-----------------------------------------------------+
                                |
                                v
+-----------------------------------------------------+
|  data/fitness_store.json - Persistent RL Memory      |
+-----------------------------------------------------+
```

### Componenti ASR Engine

| Componente | Responsabilita' |
|---|---|
| **Fitness Tracker** | Registra ogni reward, calcola fitness corrente (EMA alpha=0.3), rileva trend |
| **Failure Analyzer** | Analizza perche' la skill ha fallito, classifica in tassonomia, indica cosa mutare |
| **Mutation Strategy** | Decide cosa mutare in base alla diagnosi, genera mutazione (deterministica o LLM-guided) |
| **Snapshot Manager** | Salva stato pre-mutazione, rollback se la mutazione peggiora, cleanup vecchie snapshot |

## Ciclo RL - Episodio di Esecuzione

```
execute("skill:tool", code="...")
         |
         v
    FASE 1: ESECUZIONE
    Esegui skill normalmente
    result = executor.run(...)
         |
         v
    FASE 2: REWARD SIGNAL
    exit_code == 0                   -> reward +1.0
    exit_code != 0                   -> reward -0.5
    timeout / crash                  -> reward -1.0
         |
    reward >= 0 ?
    /          \
 Si              No
 |                |
 v                v
Ritorna       FASE 3: EVOLUTION
risultato     1. Feedback visibile all'utente
              2. snapshot_manager.save()
              3. failure_analyzer.diagnose()
              4. mutation_strategy.mutate() (via LLM se necessario)
              5. Applica mutazione su disco
              6. RETRY: esegui di nuovo
                        |
                   Retry OK?
                  /        \
               Si            No
               |              |
               v              v
         Ritorna risultato   Rollback a snapshot
         + "Skill evolved"   + ritorna errore originale
```

### Regole del ciclo

| Regola | Valore |
|---|---|
| Max retry per episodio | 1 (singolo tentativo di mutazione + retry) |
| Max mutazioni/giorno per skill | 5 |
| Soglia evoluzione | reward < 0 |
| Soglia stabilita' | 10 successi consecutivi -> status "stable" |
| Rollback | Se retry fallisce peggio -> ripristina snapshot |
| Degraded | 3 rollback consecutivi -> stop mutazioni, serve intervento umano |

## Fitness Store - Memoria RL Persistente

File: `data/fitness_store.json`

```json
{
  "python_exec": {
    "fitness": 8.7,
    "generation": 4,
    "status": "stable",
    "consecutive_successes": 12,
    "total_episodes": 47,
    "total_mutations": 3,
    "total_rollbacks": 1,
    "episodes": [
      {
        "id": "ep_a3f2c1",
        "timestamp": "2026-03-21T15:30:00Z",
        "tool_ref": "python_exec:run_code",
        "reward": 1.0,
        "generation": 4,
        "input_hash": "d4f8a2...",
        "error": null
      }
    ],
    "mutations": [
      {
        "id": "mut_x9k2",
        "timestamp": "2026-03-21T14:12:05Z",
        "trigger_episode": "ep_b7e4d9",
        "diagnosis": "missing_dependency",
        "changes": ["manifest.json: added openpyxl to dependencies"],
        "generation_before": 3,
        "generation_after": 4,
        "fitness_before": 7.2,
        "fitness_after": 8.7,
        "status": "applied"
      }
    ],
    "snapshots": [
      {
        "generation": 3,
        "timestamp": "2026-03-21T14:12:04Z",
        "path": "data/snapshots/python_exec/gen_3/"
      }
    ],
    "fitness_curve": [5.0, 6.1, 7.2, 8.7]
  }
}
```

### Calcolo fitness (EMA, scala 0-10)

```
ema_new = alpha * reward + (1 - alpha) * ema_old       # range [-1, +1]
fitness = (ema_new + 1.0) * 5.0                         # mappato a [0, 10]
alpha = 0.3
```

Una skill nuova parte con fitness 5.0 (EMA = 0). Successi consecutivi la spingono verso 10.0, fallimenti verso 0.

### Limiti retention

- Max 200 episodi per skill (FIFO)
- Max 20 snapshot per skill (FIFO)
- Compattazione automatica se fitness_store > 5MB

## Failure Analyzer - Tassonomia

```
Fallimento
+-- CODE_ERROR
|   +-- syntax_error        -> mutare: tools/run.py
|   +-- import_error         -> mutare: manifest.json (dependencies)
|   +-- runtime_exception    -> mutare: tools/run.py
|   +-- type_error           -> mutare: tools/run.py
|
+-- COVERAGE_GAP
|   +-- unhandled_input      -> mutare: tools/run.py + system_prompt.md
|   +-- missing_feature      -> mutare: tools/run.py + system_prompt.md
|   +-- edge_case            -> mutare: tools/run.py
|
+-- ENVIRONMENT
|   +-- missing_dependency   -> mutare: manifest.json (dependencies)
|   +-- timeout              -> mutare: manifest.json (timeout_seconds)
|   +-- memory_limit         -> mutare: manifest.json (o segnalare)
|
+-- PROMPT_MISMATCH
    +-- unclear_instructions -> mutare: system_prompt.md
    +-- wrong_examples       -> mutare: system_prompt.md
    +-- missing_context      -> mutare: system_prompt.md
```

### Due livelli di diagnosi

| Livello | Quando | Come |
|---|---|---|
| Euristico | Errori con pattern noto (ImportError, SyntaxError, Timeout) | Regex/pattern matching, zero costo LLM |
| LLM-assisted | Errori complessi o ambigui | MCP sampling |

Confidence < 0.6: nessuna mutazione, fallimento registrato per analisi futura.

## Mutation Strategy

### Matrice Diagnosi -> Mutazione

| Diagnosi | Strategia |
|---|---|
| missing_dependency | DETERMINISTICA: aggiungi modulo a manifest.json |
| timeout | DETERMINISTICA: +50% timeout nel manifest, max 120s |
| syntax_error | LLM: invia codice + errore, chiedi fix |
| runtime_exception | LLM: invia codice + stacktrace + input, chiedi fix |
| unhandled_input | LLM: invia prompt + codice + input fallito, chiedi estensione copertura |
| missing_feature | LLM: invia prompt + codice + descrizione mancanza, chiedi implementazione |
| unclear_instructions | LLM: riscrivi system_prompt.md con esempi migliori |

### Prompt di mutazione LLM

Il prompt include:
- Skill ID e generazione corrente
- Diagnosi con categoria e confidence
- Errore originale (stderr)
- Input che ha causato il fallimento
- File corrente da mutare
- **Storia mutazioni precedenti** (evita di ripetere fix fallite)

### Validazione post-mutazione

1. File valido? (JSON parsabile, Python compilabile)
2. Retry con stesso input
3. Reward del retry > reward originale? Si -> applica. No -> rollback.

## Snapshot Manager

### Struttura disco

```
data/
+-- fitness_store.json
+-- snapshots/
    +-- python_exec/
        +-- gen_1/
        |   +-- manifest.json
        |   +-- system_prompt.md
        |   +-- tools/run.py
        +-- gen_2/
            +-- ...
```

### Relazione con git_helper.py

Lo Snapshot Manager e' il meccanismo di rollback primario (veloce, in-memory path). Dopo ogni mutazione confermata, il sistema chiama anche `git_helper.commit_skill_update()` per persistere la modifica in git. In caso di rollback, lo snapshot viene ripristinato su disco e il rollback viene a sua volta committato in git. Git e' il registro di audit, lo snapshot e' il fast-path operativo.

### Regole rollback

| Situazione | Azione |
|---|---|
| Retry fallisce peggio | Rollback a gen precedente |
| Retry fallisce uguale | Rollback (mutazione inutile) |
| Retry ha successo | Nuova gen confermata |
| 3 rollback consecutivi | Skill marcata "degraded", stop mutazioni |
| Skill degraded + invocazione | Esegue normalmente, no evoluzione, ritorna warning |

## Integrazione con main.py

### Flusso execute() modificato

```
execute() -> executor.run() -> reward signal -> evolution? -> audit_log -> return
```

### Cambiamenti

| Componente | Cambia? |
|---|---|
| list_skills() | No |
| get_prompt() | No |
| execute() | Si - aggiunto reward + evolution cycle |
| create_skill() | No |
| approve_pending() | No |
| LLM enrichment | No - si attiva solo su reward positivo |
| Orchestrator loop | No |

### Nuovo tool MCP

```python
@mcp.tool()
def skill_fitness(skill_id: str = "") -> dict:
    """Ritorna lo stato RL di una o tutte le skill."""
```

Esempio di ritorno per una singola skill:

```json
{
  "skill_id": "python_exec",
  "fitness": 8.7,
  "generation": 4,
  "status": "stable",
  "consecutive_successes": 12,
  "total_episodes": 47,
  "total_mutations": 3,
  "total_rollbacks": 1,
  "fitness_curve": [5.0, 6.1, 7.2, 8.7],
  "last_mutation": "Added openpyxl to dependencies",
  "message": "Skill stabile - nessuna evoluzione necessaria"
}
```

## File coinvolti

### Nuovi

| File | Scopo |
|---|---|
| server/evolution.py | ASR Engine (~600-800 righe) |
| data/fitness_store.json | Memoria RL (creato a runtime) |
| data/snapshots/ | Snapshot generazioni (creato a runtime) |

### Modificati

| File | Cosa cambia |
|---|---|
| server/main.py | Import ASR, reward in execute(), tool skill_fitness() |
| docker-compose.yml | Volume data/, env vars ASR |
| .env.example | Variabili ASR |
| README.md | Sezione ASR |

### Invariati

server/registry.py, server/executor.py, server/safety.py, server/git_helper.py, skills/*

## Concurrency e Atomicita'

### Fitness store

- Un `asyncio.Lock` per skill_id protegge letture/scritture concorrenti al fitness store.
- Le scritture sono atomiche: write a file temporaneo + `os.rename()` (atomico su filesystem POSIX).
- Il background orchestrator e le chiamate `execute()` concorrenti non possono corrompere il file.

### Mutazioni su disco

- Prima di scrivere file mutati in `skills/<skill_id>/`, l'engine chiama `registry.reload()` esplicitamente dopo la scrittura (non si affida al watchdog debounce di 0.3s).
- Questo garantisce che il retry immediatamente successivo esegua il codice mutato.

## Sicurezza delle Mutazioni

### Sandbox gate

Le mutazioni ASR sono permesse **solo** per skill con `sandbox=docker` nel manifest. Le skill con `sandbox=none` o `sandbox=host` (come `skill_manager` e `orchestrator`) **non vengono mai auto-mutate** perche' eseguono codice con accesso diretto al filesystem e alla rete.

Se una skill non-sandboxed fallisce:
- Il fallimento viene registrato nel fitness store (reward, diagnosi)
- Nessuna mutazione automatica
- Il risultato include un campo `asr_info.sandbox_blocked = true` che segnala che serve intervento manuale

### Integrazione con il sistema di approvazione

Le mutazioni ASR passano attraverso la safety validation esistente:
1. Prima della mutazione, l'engine verifica `_is_safe_for_auto_approve()` sul manifest della skill
2. Se la skill ha `side_effects=true` o `requires_human_approval=true`, la mutazione viene scritta come `pending_approval` anziche' applicata direttamente
3. Solo le skill sicure (no side_effects, idempotent) vengono mutate e applicate in-line con retry immediato
4. Ogni mutazione confermata viene anche git-committata via `git_helper.commit_skill_update()` per auditabilita'

### Input deduplication

Se lo stesso input (per hash) causa fallimenti ripetuti, la seconda occorrenza e successive **non** triggerano nuove mutazioni — evita di sprecare il budget giornaliero sullo stesso errore noto. Il fallimento viene comunque registrato nel fitness store.

## Interazione con Orchestrator esistente

L'orchestrator background (ciclo ogni 30 min) e l'ASR sono due pressioni evolutive complementari:

| Aspetto | Orchestrator | ASR |
|---|---|---|
| Trigger | Timer (ogni 30 min) | Fallimento runtime on-demand |
| Scope | Tutte le skill | Solo la skill che ha fallito |
| Mutazione | Proposta LLM via eval | Fix mirata al fallimento specifico |
| Approval | Via pending_approvals/ | Inline per skill sicure, pending per le altre |

Se entrambi tentano di mutare la stessa skill contemporaneamente, il lock per skill_id serializza le operazioni. La seconda mutazione vedra' la generation aggiornata dalla prima.

## Prompt di mutazione LLM — Contenuto completo

Il prompt include sempre:
- Skill ID, generazione corrente, fitness attuale
- Diagnosi (categoria, subcategoria, confidence)
- Errore originale (stderr completo)
- Input che ha causato il fallimento (troncato a 2000 chars)
- **system_prompt.md corrente** (contesto sulla finalita' della skill)
- File target da mutare (contenuto completo)
- Storia delle mutazioni precedenti (per evitare fix gia' fallite)

## Variabili d'ambiente

```bash
ASR_ENABLED=true                  # Attiva/disattiva evoluzione adattiva
ASR_MAX_RETRIES=1                 # Max retry per episodio (1 mutazione + 1 retry)
ASR_MAX_MUTATIONS_PER_DAY=5       # Max mutazioni giornaliere per skill
ASR_STABILITY_THRESHOLD=10        # Successi consecutivi per status "stable"
ASR_DEGRADED_AFTER_ROLLBACKS=3    # Rollback consecutivi per status "degraded"
ASR_FITNESS_ALPHA=0.3             # Peso nuovo episodio nel calcolo fitness
ASR_MAX_EPISODES=200              # Max episodi nel fitness store
ASR_MAX_SNAPSHOTS=20              # Max snapshot per skill
ASR_COOLDOWN_SECONDS=300          # Cooldown tra mutazioni sulla stessa skill (5 min)
```

Nota: ASR_ENABLED viene letto all'avvio del server. Modifiche al `.env` richiedono restart.

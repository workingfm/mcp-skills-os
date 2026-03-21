"""
tools/run.py — Runner della skill python_exec.

Questo script gira DENTRO la sandbox (Docker o mock).
Riceve il codice utente montato in /sandbox/user_code.py
e lo esegue in un namespace isolato, catturando output ed errori.
"""
import sys
import traceback
from pathlib import Path

# Percorsi dentro la sandbox
USER_CODE_PATH = Path("/sandbox/user_code.py")
INPUT_PATH = Path("/sandbox/input.txt")

# Fallback per dev locale (mock mode)
if not USER_CODE_PATH.exists():
    import os
    sandbox_dir = os.getenv("SKILL_SANDBOX_DIR", ".")
    USER_CODE_PATH = Path(sandbox_dir) / "user_code.py"
    INPUT_PATH = Path(sandbox_dir) / "input.txt"


def main():
    if not USER_CODE_PATH.exists():
        print(f"[ERROR] user_code.py non trovato in {USER_CODE_PATH}", file=sys.stderr)
        sys.exit(1)

    user_code = USER_CODE_PATH.read_text(encoding="utf-8")

    # Namespace pulito per l'esecuzione
    exec_globals = {
        "__name__": "__main__",
        "__file__": str(USER_CODE_PATH),
        # Rende /sandbox/input.txt facilmente accessibile
        "__input_path__": str(INPUT_PATH),
    }

    try:
        exec(compile(user_code, str(USER_CODE_PATH), "exec"), exec_globals)
    except SystemExit as e:
        # Rispetta sys.exit() espliciti dall'utente
        sys.exit(e.code)
    except Exception:
        # Stampa traceback su stderr (sarà catturato dall'executor)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

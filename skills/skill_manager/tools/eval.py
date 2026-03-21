"""
tools/eval.py — Valuta una skill con test cases.

Input (user_code.py): JSON string
  {
    "skill_id": "python_exec",
    "test_cases": [                     # opzionale
      {"description": "desc", "code": "print(2+2)", "expected": "4"}
    ]
  }

Output (stdout): JSON con score 0-10, test_results, critique, recommendation.
La critique LLM viene generata da main.py via MCP sampling (Pro subscription).
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path

REPO_ROOT = Path(os.getenv("SKILL_ROOT", Path(__file__).parent.parent.parent.parent))
SKILLS_DIR = REPO_ROOT / "skills"

DEFAULT_TEST_CASES = {
    "python_exec": [
        {"description": "print semplice",  "code": "print('hello')",              "expected": "hello"},
        {"description": "calcolo base",    "code": "print(2 + 2)",                "expected": "4"},
        {"description": "importa pandas",  "code": "import pandas; print('ok')",  "expected": "ok"},
        {"description": "importa numpy",   "code": "import numpy; print('ok')",   "expected": "ok"},
        {"description": "gestione errore", "code": "raise ValueError('test')",    "expected": "ERROR"},
        {"description": "loop semplice",   "code": "for i in range(3): print(i)", "expected": "0\n1\n2"},
        {"description": "f-string",        "code": "x=42; print(f'val={x}')",     "expected": "val=42"},
    ],
}


def _run_tool(skill_id: str, tool_id: str, code: str) -> dict:
    skill_root = SKILLS_DIR / skill_id
    manifest = json.loads((skill_root / "manifest.json").read_text())
    tool_def = next((t for t in manifest.get("tools", []) if t["id"] == tool_id), None)
    if not tool_def:
        return {"status": "error", "stdout": "", "stderr": "Tool non trovato"}

    script_rel, _ = tool_def["entrypoint"].split(":")
    script_path = skill_root / script_rel

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "user_code.py").write_text(code)
        (Path(tmpdir) / "input.txt").write_text("")
        env = os.environ.copy()
        env["SKILL_SANDBOX_DIR"] = tmpdir
        env["SKILL_ROOT"] = str(REPO_ROOT)
        try:
            r = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(REPO_ROOT), capture_output=True,
                text=True, timeout=15, env=env,
            )
            return {"status": "ok" if r.returncode == 0 else "error",
                    "stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "exit_code": r.returncode}
        except subprocess.TimeoutExpired:
            return {"status": "error", "stdout": "", "stderr": "timeout", "exit_code": -1}


def _heuristic_critique(test_results: list) -> dict:
    """Scoring euristico basato su % test passati. La critique LLM
    viene aggiunta da main.py via MCP sampling se disponibile."""
    passed = sum(1 for t in test_results if t.get("passed"))
    total = max(len(test_results), 1)
    score = round((passed / total) * 10, 1)
    return {
        "score": score,
        "critique": {
            "strengths": [t["description"] for t in test_results if t.get("passed")][:3],
            "weaknesses": [t["description"] for t in test_results if not t.get("passed")][:3],
            "suggested_improvements": [],
        },
    }


def main():
    sandbox_dir = os.getenv("SKILL_SANDBOX_DIR", ".")
    code_file = Path(sandbox_dir) / "user_code.py"
    try:
        raw = code_file.read_text(encoding="utf-8").strip()
        params = json.loads(raw) if raw.startswith("{") else {"skill_id": raw}
    except Exception as e:
        print(json.dumps({"error": f"Input non valido: {e}"})); sys.exit(1)

    skill_id = params.get("skill_id", "python_exec")
    test_cases = params.get("test_cases") or DEFAULT_TEST_CASES.get(skill_id, [])

    if not test_cases:
        print(json.dumps({"error": f"Nessun test case per '{skill_id}'"})); sys.exit(1)

    version = "unknown"
    mp = SKILLS_DIR / skill_id / "manifest.json"
    if mp.exists():
        try: version = json.loads(mp.read_text()).get("version", "unknown")
        except Exception: pass

    test_results = []
    for tc in test_cases:
        r = _run_tool(skill_id, "run_code", tc.get("code", ""))
        expected = tc.get("expected", "").strip()
        actual = r.get("stdout", "").strip()
        passed = (expected == "ERROR" and r["status"] == "error") or \
                 (expected != "ERROR" and expected in actual)
        test_results.append({
            "description": tc.get("description", tc.get("code", "")[:40]),
            "passed": passed, "expected": expected, "actual": actual[:200],
            "error": r.get("stderr", "")[:200] if not passed else "",
        })

    heuristic = _heuristic_critique(test_results)
    score = heuristic.get("score", 0.0)
    print(json.dumps({
        "skill_id": skill_id, "version": version, "score": score,
        "test_results": test_results, "critique": heuristic.get("critique", {}),
        "recommendation": "ok" if score >= 8.5 else ("rebuild" if score < 5.0 else "improve"),
        "needs_llm_critique": True,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

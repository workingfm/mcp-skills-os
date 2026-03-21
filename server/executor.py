"""
Executor — esegue i tool in una sandbox.

Strategia per sandbox (dal manifest):
  "docker"  → container Docker effimero, isolato (default per codice utente)
  "none"    → subprocess locale sul server (per tool che scrivono su disco o usano rete)
  "mock"    → subprocess locale forzato (SKILL_OS_SANDBOX=mock, dev only)
"""
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("skill-os.executor")

SANDBOX_MODE = os.getenv("SKILL_OS_SANDBOX", "docker")

# Cache per immagini Docker pre-buildate con dipendenze
_image_cache: dict[str, str] = {}


class Executor:
    async def run(
        self,
        skill_id: str,
        tool_id: str,
        tool: dict,
        code: str,
        input_data: str = "",
    ) -> dict:
        execution = tool.get("execution", {})
        runtime = tool.get("runtime", {})
        timeout = execution.get("timeout_seconds", 30)
        entrypoint = tool.get("entrypoint", "")
        skill_root: Path = tool["_skill_root"]

        script_rel, _fn = entrypoint.split(":")
        script_path = (skill_root / script_rel).resolve()

        if not script_path.exists():
            return {"status": "error", "stdout": "", "exit_code": 1,
                    "stderr": f"Entrypoint non trovato: {script_path}"}

        # Scegli modalità: mock globale, oppure sandbox dal manifest
        manifest_sandbox = execution.get("sandbox", "docker")

        if SANDBOX_MODE == "mock" or manifest_sandbox in ("none", "host"):
            # Tool server-side (skill_manager, orchestrator) → subprocess locale
            logger.debug(f"[executor] local subprocess: {tool_id}")
            return await self._run_local(script_path, code, input_data, timeout, skill_root)
        else:
            # Codice utente → Docker sandbox
            return await self._run_docker(script_path, code, input_data, runtime, timeout)

    # ------------------------------------------------------------------ #
    #  Docker sandbox                                                      #
    # ------------------------------------------------------------------ #
    async def _get_or_build_image(self, py_version: str, deps: list[str]) -> str:
        """Costruisce (una volta) un'immagine Docker con le dipendenze pre-installate."""
        if not deps:
            return f"python:{py_version}-slim"

        cache_key = f"{py_version}:{','.join(sorted(deps))}"
        if cache_key in _image_cache:
            return _image_cache[cache_key]

        tag = f"skill-os-sandbox-{py_version}-{'_'.join(sorted(deps))[:50]}"
        # Verifica se l'immagine esiste gia
        check = await asyncio.create_subprocess_exec(
            "docker", "image", "inspect", tag,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await check.wait()
        if check.returncode == 0:
            _image_cache[cache_key] = tag
            return tag

        # Build immagine con deps pre-installate
        logger.info(f"[executor] building sandbox image: {tag}")
        dockerfile = f"FROM python:{py_version}-slim\nRUN pip install --no-cache-dir {' '.join(deps)}\n"
        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", tag, "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=dockerfile.encode())
        if proc.returncode == 0:
            _image_cache[cache_key] = tag
            logger.info(f"[executor] sandbox image built: {tag}")
            return tag

        # Fallback: immagine base (pip install ad ogni run)
        logger.warning(f"[executor] build fallita, fallback a pip install runtime")
        return f"python:{py_version}-slim"

    async def _run_docker(self, script_path, code, input_data, runtime, timeout):
        py_version = runtime.get("version", "3.11")
        deps = runtime.get("dependencies", [])
        image = await self._get_or_build_image(py_version, deps)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "user_code.py").write_text(code, encoding="utf-8")
            (tmp / "input.txt").write_text(input_data, encoding="utf-8")

            # Se l'immagine ha gia le deps, non serve pip install
            needs_pip = image.startswith("python:") and deps
            pip_install = f"pip install --quiet {' '.join(deps)}" if needs_pip else "true"
            run_cmd = f"{pip_install} && python /sandbox/run.py"

            cmd = [
                "docker", "run", "--rm",
                "--memory=256m", "--cpus=0.5",
                "--network=none" if not needs_pip else "--network=bridge",
                "--read-only",
                "--tmpfs=/tmp:size=64m",
                "-v", f"{script_path}:/sandbox/run.py:ro",
                "-v", f"{tmp / 'user_code.py'}:/sandbox/user_code.py:ro",
                "-v", f"{tmp / 'input.txt'}:/sandbox/input.txt:ro",
                image, "sh", "-c", run_cmd,
            ]
            return await self._exec(cmd, timeout)

    # ------------------------------------------------------------------ #
    #  Local subprocess (server-side tools: skill_manager, orchestrator)  #
    # ------------------------------------------------------------------ #
    async def _run_local(self, script_path, code, input_data, timeout, skill_root):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "user_code.py").write_text(code, encoding="utf-8")
            (tmp / "input.txt").write_text(input_data, encoding="utf-8")

            env = os.environ.copy()
            env["SKILL_SANDBOX_DIR"] = tmpdir
            env["SKILL_ROOT"] = str(skill_root.parent.parent)  # repo root

            cmd = [sys.executable, str(script_path)]
            return await self._exec(cmd, timeout, cwd=str(skill_root.parent.parent), env=env)

    # ------------------------------------------------------------------ #
    #  Subprocess helper                                                   #
    # ------------------------------------------------------------------ #
    async def _exec(self, cmd, timeout, cwd=None, env=None):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd, env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "status": "ok" if proc.returncode == 0 else "error",
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode,
            }
        except asyncio.TimeoutError:
            try: proc.kill()
            except Exception: pass
            return {"status": "error", "stdout": "", "exit_code": -1,
                    "stderr": f"Timeout ({timeout}s superato)"}
        except FileNotFoundError as e:
            hint = " — Docker non trovato. Usa SKILL_OS_SANDBOX=mock per dev locale." \
                   if "docker" in str(e) else ""
            return {"status": "error", "stdout": "", "exit_code": 127,
                    "stderr": f"Comando non trovato: {e}{hint}"}
        except Exception as e:
            return {"status": "error", "stdout": "", "exit_code": -1, "stderr": str(e)}

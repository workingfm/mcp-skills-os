"""
SkillRegistry — carica e gestisce i Skill Pack da disco.
Supporta hot-reload via watchdog: modifica un manifest.json
e il server lo ricarica senza restart.
"""
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("skill-os.registry")

DEBOUNCE_SECONDS = 0.3


class _SkillReloadHandler(FileSystemEventHandler):
    def __init__(self, registry: "SkillRegistry"):
        self._registry = registry
        self._last_trigger = 0.0
        self._timer: threading.Timer | None = None

    def _schedule_reload(self, event):
        if not event.src_path.endswith(("manifest.json", ".md", ".py")):
            return
        now = time.monotonic()
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(DEBOUNCE_SECONDS, self._do_reload, args=[event.src_path])
        self._timer.daemon = True
        self._timer.start()

    def _do_reload(self, src_path: str):
        logger.info(f"[hot-reload] rilevato cambio: {src_path}")
        self._registry.reload()

    def on_modified(self, event):
        self._schedule_reload(event)

    on_created = on_modified
    on_deleted = on_modified


class SkillRegistry:
    """
    Legge /skills/<skill_id>/manifest.json e costruisce
    un indice in memoria di tutte le skill disponibili.
    """

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir).resolve()
        self._skills: dict[str, dict] = {}
        self._lock = threading.RLock()
        self.reload()
        self._start_watcher()

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def reload(self):
        from safety import validate_manifest

        skills: dict[str, dict] = {}
        for manifest_path in self.skills_dir.glob("*/manifest.json"):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                warnings = validate_manifest(data)
                if warnings:
                    for w in warnings:
                        logger.warning(f"[registry] {manifest_path.parent.name}: {w}")
                skill_id = data["id"]
                data["_root"] = manifest_path.parent   # path assoluto
                skills[skill_id] = data
                logger.info(f"[registry] caricata skill '{skill_id}' "
                            f"(v{data.get('version','?')})")
            except Exception as e:
                logger.error(f"[registry] errore manifest {manifest_path}: {e}")

        with self._lock:
            self._skills = skills
        logger.info(f"[registry] {len(skills)} skill disponibili.")

    def _start_watcher(self):
        handler = _SkillReloadHandler(self)
        observer = Observer()
        observer.schedule(handler, str(self.skills_dir), recursive=True)
        observer.daemon = True
        observer.start()
        logger.info(f"[registry] watchdog attivo su {self.skills_dir}")

    # ------------------------------------------------------------------ #
    #  Query API                                                           #
    # ------------------------------------------------------------------ #

    def list_skills(self) -> dict:
        """
        Ritorna il catalogo pubblico di tutte le skill
        (senza path interni).
        """
        with self._lock:
            return {
                sid: {
                    "id": s["id"],
                    "version": s.get("version", "0.0.0"),
                    "description": s.get("description", ""),
                    "tools": [
                        {
                            "id": t["id"],
                            "ref": f"{sid}:{t['id']}",
                            "description": t.get("description", ""),
                            "safety": t.get("safety", {}),
                        }
                        for t in s.get("tools", [])
                    ],
                }
                for sid, s in self._skills.items()
            }

    def get_prompt(self, skill_id: str) -> str:
        """Carica il system_prompt.md di una skill (lazy)."""
        skill = self._get_skill_raw(skill_id)
        uri = skill.get("system_prompt_uri", "")
        # Risolve: "skill://python_exec/system_prompt.md"
        rel_path = uri.split(f"skill://{skill_id}/")[-1]
        prompt_path: Path = skill["_root"] / rel_path
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt non trovato: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def get_tool(self, skill_id: str, tool_id: str) -> dict:
        """Ritorna la definizione completa di un tool."""
        skill = self._get_skill_raw(skill_id)
        for tool in skill.get("tools", []):
            if tool["id"] == tool_id:
                # Inietta il path assoluto dell'entrypoint
                tool = dict(tool)
                tool["_skill_root"] = skill["_root"]
                return tool
        raise KeyError(f"Tool '{tool_id}' non trovato in skill '{skill_id}'")

    def _get_skill_raw(self, skill_id: str) -> dict:
        with self._lock:
            if skill_id not in self._skills:
                raise KeyError(f"Skill '{skill_id}' non trovata. "
                               f"Disponibili: {list(self._skills.keys())}")
            return self._skills[skill_id]

"""Persistent slash commands for server tasks."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit


DEFAULT_MACROS = {
    "flush": {
        "label": "Очистить DNS-кеш сервера",
        "command": "sudo resolvectl flush-caches",
        "file": "",
        "open_url": "https://qwill-dashboard.mooo.com",
    }
}
MAX_OUTPUT = 64 * 1024


class MacroStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.path = state_dir / "macros.json"
        self._lock = threading.RLock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {name: value.copy() for name, value in DEFAULT_MACROS.items()}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Файл макросов повреждён")
        return data

    def _write(self, data: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=".macros-", dir=self.state_dir)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def list(self) -> list[dict]:
        with self._lock:
            return [{"name": name, **value} for name, value in sorted(self._read().items())]

    def save(self, name: str, value: dict) -> dict:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
            raise ValueError("Имя макроса: латинские буквы, цифры, _ или -")
        cleaned = {key: str(value.get(key) or "").strip() for key in ("label", "command", "file", "open_url")}
        if not cleaned["command"] and not cleaned["file"]:
            raise ValueError("Добавьте команду или путь к исполняемому файлу")
        if len(cleaned["label"]) > 80 or len(cleaned["command"]) > 16000:
            raise ValueError("Описание или команда слишком длинные")
        if cleaned["file"] and not Path(cleaned["file"]).is_absolute():
            raise ValueError("Путь к исполняемому файлу должен быть абсолютным")
        if cleaned["open_url"]:
            url = urlsplit(cleaned["open_url"])
            if url.scheme not in {"http", "https"} or not url.netloc:
                raise ValueError("Укажите полный адрес http:// или https://")
        with self._lock:
            data = self._read()
            data[name] = cleaned
            self._write(data)
        return {"name": name, **cleaned}

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            if name not in data:
                raise KeyError(name)
            del data[name]
            self._write(data)

    def run(self, name: str) -> dict:
        with self._lock:
            macro = self._read().get(name)
        if macro is None:
            raise KeyError(name)

        output = []
        for title, command in (("Команда", ["/bin/bash", "-lc", macro["command"]] if macro["command"] else None),
                               ("Файл", [macro["file"]] if macro["file"] else None)):
            if command is None:
                continue
            output.append(f"$ {' '.join(command) if title == 'Файл' else macro['command']}\n")
            try:
                result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=120, check=False, cwd=Path.home())
                output.append(result.stdout)
                output.append(result.stderr)
                if result.returncode:
                    return {"success": False, "exit_code": result.returncode, "output": "".join(output)[-MAX_OUTPUT:], "open_url": ""}
            except subprocess.TimeoutExpired:
                return {"success": False, "exit_code": 124, "output": "".join(output)[-MAX_OUTPUT:] + "\nПревышено время выполнения (120 с)", "open_url": ""}
            except OSError as exc:
                return {"success": False, "exit_code": 127, "output": "".join(output)[-MAX_OUTPUT:] + f"\n{exc}", "open_url": ""}
        return {"success": True, "exit_code": 0, "output": "".join(output)[-MAX_OUTPUT:], "open_url": macro["open_url"]}

"""Browse and edit UTF-8 files on the host."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


MAX_FILE_BYTES = 4 * 1024 * 1024


class FileConflict(Exception):
    """The file changed since it was opened in the editor."""


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Укажите абсолютный путь")
    return path.resolve()


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(data: bytes) -> str:
    if b"\0" in data:
        raise ValueError("Двоичный файл нельзя открыть в текстовом редакторе")
    return data.decode("utf-8")


def read_directory(value: str) -> dict:
    path = _path(value)
    if not path.is_dir():
        raise ValueError("Каталог не найден")
    entries = []
    with os.scandir(path) as scan:
        for item in scan:
            try:
                is_dir = item.is_dir(follow_symlinks=True)
                size = item.stat(follow_symlinks=True).st_size if not is_dir else None
            except OSError:
                is_dir, size = False, None
            entries.append({"name": item.name, "path": str(path / item.name), "directory": is_dir, "size": size})
    entries.sort(key=lambda item: (not item["directory"], item["name"].casefold()))
    return {"path": str(path), "parent": str(path.parent), "entries": entries[:1000], "truncated": len(entries) > 1000}


def read_file(value: str) -> dict:
    path = _path(value)
    if not path.is_file():
        raise ValueError("Файл не найден")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Файл больше 4 МБ")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Файл больше 4 МБ")
    return {"path": str(path), "content": _text(data), "revision": _revision(data)}


def _backup_dir(path: Path, state_dir: Path) -> Path:
    return state_dir / "backups" / _revision(str(path).encode("utf-8"))[:20]


def read_backups(value: str, state_dir: Path) -> list[dict]:
    directory = _backup_dir(_path(value), state_dir)
    if not directory.exists():
        return []
    return [{"id": item.name, "size": item.stat().st_size} for item in sorted(directory.glob("*.bak"), reverse=True)[:30]]


def read_backup(value: str, backup_id: str, state_dir: Path) -> dict:
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.bak", backup_id):
        raise ValueError("Некорректный номер копии")
    path = _backup_dir(_path(value), state_dir) / backup_id
    if not path.is_file():
        raise ValueError("Копия не найдена")
    data = path.read_bytes()
    return {"content": _text(data), "id": backup_id}


def write_file(value: str, content: str, revision: str | None, state_dir: Path) -> dict:
    path = _path(value)
    if path.is_dir():
        raise ValueError("Путь указывает на каталог")
    if not path.parent.is_dir():
        raise ValueError("Родительский каталог не найден")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Файл больше 4 МБ")

    exists = path.exists()
    if exists and path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Файл больше 4 МБ")
    old = path.read_bytes() if exists else None
    if exists and revision != _revision(old):
        raise FileConflict("Файл изменился на сервере. Откройте его заново перед сохранением.")
    if not exists and revision is not None:
        raise FileConflict("Файл был удалён на сервере. Откройте каталог заново.")

    backup_id = None
    if old is not None:
        backup_dir = _backup_dir(path, state_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + ".bak"
        (backup_dir / backup_id).write_bytes(old)

    previous = path.stat() if exists else None
    handle, temp_name = tempfile.mkstemp(prefix=".dashboard-", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if previous:
            os.chmod(temp_name, stat.S_IMODE(previous.st_mode))
            if hasattr(os, "chown"):
                os.chown(temp_name, previous.st_uid, previous.st_gid)
        else:
            os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return {"path": str(path), "revision": _revision(data), "backup": backup_id}

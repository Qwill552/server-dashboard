"""Stream an interactive Linux shell over a WebSocket."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from fastapi import WebSocket


def resize_pty(fd: int, cols: int, rows: int) -> None:
    import fcntl
    import struct
    import termios

    cols = min(500, max(20, cols))
    rows = min(200, max(5, rows))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def write_pty(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        remaining = remaining[os.write(fd, remaining):]


async def serve_terminal(websocket: WebSocket) -> None:
    await websocket.accept()
    if os.name != "posix":
        await websocket.send_text(json.dumps({"type": "error", "message": "Терминал доступен на Linux-сервере"}))
        await websocket.close()
        return

    try:
        master, slave = os.openpty()
    except OSError:
        await websocket.send_text(json.dumps({"type": "error", "message": "PTY недоступен. Проверьте настройку сервиса."}))
        await websocket.close()
        return
    process = None
    try:
        resize_pty(master, 100, 28)
        environment = os.environ.copy()
        environment.update({"TERM": "xterm-256color", "COLORTERM": "truecolor"})
        try:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name("terminal_child.py"))],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(Path.home()),
                env=environment,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            await websocket.send_text(json.dumps({"type": "error", "message": f"Не удалось открыть оболочку: {exc}"}))
            await websocket.close()
            return
        os.close(slave)
        slave = -1

        async def output() -> None:
            while True:
                try:
                    chunk = await asyncio.to_thread(os.read, master, 16384)
                except OSError:
                    break
                if not chunk:
                    break
                await websocket.send_bytes(chunk)

        async def input_() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await asyncio.to_thread(write_pty, master, message["bytes"])
                elif message.get("text"):
                    try:
                        control = json.loads(message["text"])
                        if control.get("type") == "resize":
                            resize_pty(master, int(control["cols"]), int(control["rows"]))
                    except (ValueError, KeyError, TypeError):
                        continue

        tasks = [asyncio.create_task(output()), asyncio.create_task(input_())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            if task.exception():
                raise task.exception()
    finally:
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                await asyncio.to_thread(process.wait, 2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await asyncio.to_thread(process.wait)
        if slave >= 0:
            os.close(slave)
        os.close(master)

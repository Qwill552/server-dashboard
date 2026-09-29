"""Attach a login shell to the PTY created by the WebSocket server."""

import fcntl
import os
import shutil
import termios


def main() -> None:
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    tmux = shutil.which("tmux")
    if tmux:
        os.execv(tmux, ["tmux", "new-session", "-A", "-s", "qwill-dashboard"])
    os.execv("/bin/bash", ["bash", "-l"])


if __name__ == "__main__":
    main()

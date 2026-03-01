"""
Command history management.

Records ffmpeg commands to $XDG_DATA_HOME/trackremux/history.log
(falls back to ~/.local/share/trackremux/history.log).
"""

import os
import subprocess
import datetime


def _history_dir() -> str:
    xdg = os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))
    d = os.path.join(xdg, "trackremux")
    os.makedirs(d, exist_ok=True)
    return d


def save_command(cmd: list, source_file: str, output_file: str) -> None:
    """Append a command entry to the history log."""
    try:
        log_path = os.path.join(_history_dir(), "history.log")
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cmd_str = " ".join(cmd)
        entry = f"[{timestamp}] {source_file} → {output_file}\n{cmd_str}\n\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass  # Never crash the UI over logging


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to clipboard. Returns True on success.
    Supports macOS (pbcopy) and Linux (xclip / xsel / wl-copy).
    """
    # macOS
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-8"))
        if p.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    # Wayland
    try:
        p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-8"))
        if p.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    # X11 xclip
    try:
        p = subprocess.Popen(
            ["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE
        )
        p.communicate(input=text.encode("utf-8"))
        if p.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    # X11 xsel
    try:
        p = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
        p.communicate(input=text.encode("utf-8"))
        if p.returncode == 0:
            return True
    except FileNotFoundError:
        pass

    return False

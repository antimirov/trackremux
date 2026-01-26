import argparse
import os
import sys
from importlib.metadata import metadata

from .tui.app import start_tui


def get_metadata():
    """Get package metadata from pyproject.toml via importlib.metadata."""
    try:
        return metadata("trackremux")
    except Exception:
        return None


def get_version_info() -> str:
    """Format version info for --version flag."""
    meta = get_metadata()
    if meta:
        return f"{meta['Name']} v{meta['Version']}\n{meta['Summary']}"
    return "trackremux (version unknown)"


def main():
    meta = get_metadata()
    parser = argparse.ArgumentParser(
        prog=meta["Name"] if meta else "trackremux",
        description=meta["Summary"] if meta else "TrackRemux TUI"
    )
    parser.add_argument("path", nargs="?", default=".", help="Path to a file or directory")
    parser.add_argument("--gui", action="store_true", help="Launch GUI (Future)")
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=get_version_info()
    )
    args = parser.parse_args()

    if args.gui:
        print("GUI mode is not implemented yet. Use the default TUI mode.")
        return

    path = os.path.abspath(args.path)

    if os.path.isdir(path):
        # Start TUI in explorer mode
        start_tui(path)
    elif os.path.isfile(path):
        # Start TUI in editor mode for a single file
        start_tui(path, single_file=True)
    else:
        print(f"Error: Path '{path}' not found.")
        sys.exit(1)


if __name__ == "__main__":
    main()

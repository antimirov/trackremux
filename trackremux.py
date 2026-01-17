import argparse
import os
import sys

from trackremux.tui.app import start_tui


def main():
    parser = argparse.ArgumentParser(description="TrackRemux TUI")
    parser.add_argument("path", nargs="?", default=".", help="Path to a file or directory")
    parser.add_argument("--gui", action="store_true", help="Launch GUI (Future)")
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

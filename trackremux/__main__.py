import argparse
import os
import sys
from importlib.metadata import metadata

from .tui.app import start_tui
from .tui.progress import STAGING_DIR, TRASH_DIR


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


def do_cleanup(root: str):
    """Find and remove all .trackremux_trash and empty .trackremux_staging directories."""
    import shutil

    target_dirs = []
    total_bytes = 0

    for dirpath, dirnames, _ in os.walk(root):
        for d in list(dirnames):
            if d in (TRASH_DIR, STAGING_DIR):
                full = os.path.join(dirpath, d)
                files_found = []
                size = 0
                for dp, _, files in os.walk(full):
                    for f in files:
                        f_path = os.path.join(dp, f)
                        size += os.path.getsize(f_path)
                        files_found.append(f)
                
                target_dirs.append({
                    "path": full,
                    "size": size,
                    "files": files_found
                })
                total_bytes += size
                dirnames.remove(d)  # don't recurse into it

    if not target_dirs:
        print("No leftover trackremux directories found.")
        return

    size_mb = total_bytes / 1024 / 1024
    print(f"Found {len(target_dirs)} director{'y' if len(target_dirs) == 1 else 'ies'} ({size_mb:.1f} MB). Cleaning up...")

    removed = 0
    for entry in target_dirs:
        path = entry["path"]
        sz = entry["size"]
        files = entry["files"]
        
        try:
            print(f"  Removing: {path}  ({sz / 1024 / 1024:.1f} MB)")
            if files:
                for f in files[:5]: # Show first 5 files
                    print(f"    - {f}")
                if len(files) > 5:
                    print(f"    - ... and {len(files) - 5} more files")
            
            shutil.rmtree(path)
            removed += 1
        except Exception as e:
            print(f"  Error removing {path}: {e}")

    print(f"\nDone. {removed}/{len(target_dirs)} directories removed ({size_mb:.1f} MB freed).")



def main():
    meta = get_metadata()
    parser = argparse.ArgumentParser(
        prog=meta["Name"] if meta else "trackremux",
        description=meta["Summary"] if meta else "TrackRemux TUI",
    )
    parser.add_argument("path", nargs="?", default=".", help="Path to a file or directory")
    parser.add_argument("-v", "--version", action="version", version=get_version_info())
    parser.add_argument(
        "--cleanup",
        nargs="?",
        const=".",
        metavar="PATH",
        help="Find and delete leftover .trackremux_trash and .trackremux_staging directories under PATH (default: current dir)",
    )
    args = parser.parse_args()

    if args.cleanup is not None:
        cleanup_path = os.path.abspath(args.cleanup)
        if not os.path.isdir(cleanup_path):
            print(f"Error: '{cleanup_path}' is not a directory.")
            sys.exit(1)
        do_cleanup(cleanup_path)
        return

    path = os.path.abspath(args.path)

    if os.path.isdir(path):
        start_tui(path)
    elif os.path.isfile(path):
        start_tui(path, single_file=True)
    else:
        print(f"Error: Path '{path}' not found.")
        sys.exit(1)


if __name__ == "__main__":
    main()

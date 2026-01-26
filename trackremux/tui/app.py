import curses
import os
import sys
import time
import traceback

from trackremux.core.preview import MediaPreview

from ..core.scanner import GlobalScanner
from .constants import APP_TIMEOUT_MS, KEY_CTRL_C
from .editor import TrackEditor
from .explorer import FileExplorer


class TrackRemuxApp:
    def __init__(self, stdscr, start_path, single_file=False):
        self.stdscr = stdscr
        self.start_path = start_path
        self.single_file = single_file
        self.current_view = None
        self.mouse_enabled = True

        # Initialize colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)  # Highlight

        # Initialize Global Scanner
        self.scanner = GlobalScanner()

    def run(self):
        try:
            # Enable mouse by default (or based on state)
            if self.mouse_enabled:
                curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED)
            else:
                curses.mousemask(0)

            curses.curs_set(0)  # Hide cursor

            if self.single_file:
                self.current_view = TrackEditor(self, self.start_path)
            else:
                self.current_view = FileExplorer(self, self.start_path)

            self.stdscr.timeout(APP_TIMEOUT_MS)  # Non-blocking getch
            while self.current_view:
                self.current_view.draw()
                key = self.stdscr.getch()

                # Handle Ctrl-C (3) explicitly
                if key == KEY_CTRL_C:
                    raise KeyboardInterrupt

                self.current_view.handle_input(key)
        except KeyboardInterrupt:
            # Graceful exit on Ctrl-C
            pass
        except Exception as e:
            with open("trackremux_error.log", "w") as f:
                f.write(f"Crashed at {time.ctime()}\n")
                f.write(traceback.format_exc())
            raise e
        finally:
            curses.mousemask(0)

            # Ensure audio stops when quitting
            MediaPreview.stop()
            # Stop scanner
            # Stop scanner
            if (
                self.current_view
                and hasattr(self.current_view, "app")
                and hasattr(self.current_view.app, "scanner")
            ):
                self.current_view.app.scanner.stop()
            elif hasattr(self, "scanner"):
                self.scanner.stop()

    def switch_view(self, new_view):
        self.current_view = new_view

    def toggle_mouse(self):
        self.mouse_enabled = not self.mouse_enabled
        if self.mouse_enabled:
            # Use curses built-in mouse handling only
            curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED)
        else:
            curses.mousemask(0)


def start_tui(path, single_file=False):
    # Reduce delay for ESC key
    os.environ.setdefault("ESCDELAY", "25")

    # Nuclear reset: KILL all mouse modes before curses even starts.
    # We use stderr to bypass any stdout buffering.
    sys.stderr.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l")
    sys.stderr.flush()

    curses.wrapper(lambda stdscr: TrackRemuxApp(stdscr, path, single_file).run())

import curses
import os
import sys
import time
import traceback
from dataclasses import dataclass, field

from trackremux.core.preview import MediaPreview

from ..core.config import AppConfig
from ..core.donor import DonorCache
from ..core.models import OutputMode
from ..core.scanner import GlobalScanner
from .constants import APP_TIMEOUT_MS, KEY_CTRL_C
from .editor import TrackEditor
from .explorer import FileExplorer


@dataclass
class AppSettings:
    """Mutable runtime settings shared across all views in the session."""

    output_mode: OutputMode = OutputMode.LOCAL
    convert_audio: bool = False
    # Once the user picks an output mode once, skip the dialog for subsequent files
    output_mode_chosen: bool = False
    # Suppress [A] Apply profile hint after the user dismisses it once per session
    profile_hint_dismissed: bool = False


class TrackRemuxApp:
    def __init__(self, stdscr, start_path, single_file=False):
        self.stdscr = stdscr
        self.start_path = start_path
        self.single_file = single_file
        self.current_view = None
        self.mouse_enabled = True

        # Load persistent config and runtime settings
        self.config = AppConfig.load()
        self.settings = AppSettings()
        # Seed convert_audio from saved preference
        if self.config.prefer_ac3_over_hd:
            self.settings.convert_audio = True

        # Initialize colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_RED, -1)
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)  # Highlight

        # Initialize Global Scanner
        self.scanner = GlobalScanner()

        # Initialize Donor Cache
        self.donor_cache = DonorCache()

        # Initialize Queue subsystem
        from ..core.queue import QueueManager
        from ..core.worker import QueueWorker
        self.queue_manager = QueueManager()
        self.queue_worker = QueueWorker(self.queue_manager)
        
        self.pending_refreshes = set()
        self.queue_worker.on_task_completed = self._on_task_completed

    def _on_task_completed(self, task):
        filename = os.path.basename(task.media_file_dict.get('path', ''))
        if filename:
            self.pending_refreshes.add(filename)

    def run(self):
        try:
            # Enable mouse by default (or based on state)
            if self.mouse_enabled:
                curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED)
            else:
                curses.mousemask(0)

            curses.curs_set(0)  # Hide cursor

            # Check for failed tasks on startup
            failed_tasks = self.queue_manager.get_tasks("failed")
            if failed_tasks:
                self.stdscr.erase()
                height, width = self.stdscr.getmaxyx()
                
                files_list = []
                for t in failed_tasks[:5]:
                    fn = t.media_file_dict.get('filename') or os.path.basename(t.media_file_dict.get('path', ''))
                    # Elide middle of filename if it's exceptionally long
                    if len(fn) > 60:
                        fn = fn[:30] + "..." + fn[-27:]
                    files_list.append(f"    • {fn}")
                if len(failed_tasks) > 5:
                    files_list.append(f"    • ... and {len(failed_tasks) - 5} more")

                lines = [
                    f"  There are {len(failed_tasks)} failed jobs from previous runs:",
                    "",
                ] + files_list + [
                    "",
                    "  Do you want to re-queue them as pending",
                    "  to try running them again?",
                    "",
                    "  [Y] Yes, re-queue them   [N] No, leave them failed"
                ]
                
                mw = max(56, max(len(ln) + 4 for ln in lines))
                mw = min(mw, width - 4)
                mh = len(lines) + 4
                my = (height - mh) // 2
                mx = (width - mw) // 2
                
                # Draw background box
                for r in range(mh):
                    self.stdscr.addstr(my + r, mx, " " * mw, curses.color_pair(3))
                    
                # Title
                title = "─" * (mw - 2)
                title_text = " Failed Jobs Detected "
                tp = (len(title) - len(title_text)) // 2
                title = title[:tp] + title_text + title[tp + len(title_text) :]
                self.stdscr.addstr(my, mx + 1, title[: mw - 2], curses.color_pair(3) | curses.A_BOLD)
                
                # Content
                for i, ln in enumerate(lines):
                    self.stdscr.addstr(my + 2 + i, mx, ln[:mw], curses.color_pair(3))
                    
                self.stdscr.refresh()
                
                # Block for keypress
                while True:
                    key = self.stdscr.getch()
                    if key in (ord('y'), ord('Y')):
                        # Re-queue failed tasks
                        for task in failed_tasks:
                            task.status = "pending"
                            task.error_message = None
                        self.queue_manager.save()
                        break
                    elif key in (ord('n'), ord('N'), 27):  # ESC or N
                        break
                    time.sleep(0.05)

            if self.single_file:
                self.current_view = TrackEditor(self, self.start_path)
            else:
                self.current_view = FileExplorer(self, self.start_path)

            self.stdscr.timeout(APP_TIMEOUT_MS)  # Non-blocking getch
            
            # Start worker immediately to pick up any pending or abandoned tasks
            if hasattr(self, "queue_worker") and not self.queue_worker.is_running():
                self.queue_worker.start()

            while self.current_view:
                if self.pending_refreshes:
                    if hasattr(self.current_view, "refresh_metadata"):
                        refs = list(self.pending_refreshes)
                        self.pending_refreshes.clear()
                        self.current_view.refresh_metadata(refs)
                        
                self.current_view.draw()
                key = self.stdscr.getch()

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
            
            # Stop worker
            if hasattr(self, "queue_worker"):
                try:
                    if self.queue_worker.is_running() and self.queue_worker.current_task:
                        self.stdscr.erase()
                        h, w = self.stdscr.getmaxyx()
                        msg = "Shutting down active worker thread cleanly..."
                        self.stdscr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.color_pair(3) | curses.A_BOLD)
                        self.stdscr.refresh()
                except Exception:
                    pass
                self.queue_worker.stop()
                
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

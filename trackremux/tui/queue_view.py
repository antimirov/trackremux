import curses
import os
from .constants import KEY_ESC, KEY_Q_LOWER, KEY_Q_UPPER, KEY_ENTER, FILE_LIST_Y_OFFSET
from ..core.queue import QueueManager

class QueueView:
    def __init__(self, app, back_view):
        self.app = app
        self.back_view = back_view
        self.qm = self.app.queue_manager
        self.worker = self.app.queue_worker
        self.tasks = []
        self.selected_idx = 0
        self.scroll_idx = 0
        self._refresh_tasks()

    def _refresh_tasks(self):
        # Read the latest state from disk/memory
        self.qm.load()
        self.tasks = self.qm.get_tasks()
        if self.selected_idx >= len(self.tasks) and len(self.tasks) > 0:
            self.selected_idx = len(self.tasks) - 1

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()
        self._refresh_tasks()

        # Header
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)
        self.app.stdscr.addstr(0, 1, "[Q/ESC] BACK", curses.color_pair(5))

        title = " Task Queue "
        if width > len(title) + 20:
            self.app.stdscr.addstr(0, (width - len(title)) // 2, title)
        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Worker Status
        if not self.worker.is_running():
            worker_status = "PAUSED"
        elif self.worker.current_task:
            worker_status = "PROCESSING"
        else:
            worker_status = "IDLE"
        self.app.stdscr.addstr(2, 1, f" Queue Worker: {worker_status} ", curses.A_BOLD)
        
        if self.worker.is_running() and self.worker.current_task:
            pct = self.worker.percent
            bar_width = min(40, width - 40)
            if bar_width > 10:
                filled = int(bar_width * pct / 100)
                bar = "[" + "=" * filled + " " * (bar_width - filled) + "]"
                self.app.stdscr.addstr(2, 25, f" {bar} {pct}% ", curses.color_pair(3))

        # List
        list_height = height - 6
        if list_height > 0:
            if not self.tasks:
                self.app.stdscr.addstr(4, 2, "Queue is empty.", curses.A_DIM)
            else:
                for i in range(list_height):
                    idx = self.scroll_idx + i
                    if idx < len(self.tasks):
                        task = self.tasks[idx]
                        y = 4 + i
                        
                        fname = os.path.basename(task.media_file_dict.get('path', 'Unknown'))
                        status = task.status.upper()
                        
                        owner_str = ""
                        my_pid = os.getpid()
                        if task.owner_pid and task.owner_pid != my_pid:
                            owner_str = f" [PID:{task.owner_pid}]"
                        
                        # Generate stats
                        try:
                            media_file = task.get_media_file()
                            kept_v = sum(1 for t in media_file.tracks if t.codec_type == 'video' and t.enabled)
                            kept_a = sum(1 for t in media_file.tracks if t.codec_type == 'audio' and t.enabled)
                            kept_s = sum(1 for t in media_file.tracks if t.codec_type == 'subtitle' and t.enabled)
                            
                            audio_langs = [t.display_language for t in media_file.tracks if t.codec_type == 'audio' and t.enabled and t.display_language]
                            lang_str = ",".join(audio_langs)
                            if len(lang_str) > 12:
                                lang_str = lang_str[:10] + ".."
                                
                            mode_map = {"local": "LOC", "remote": "REM", "overwrite": "OVR"}
                            mode = mode_map.get(task.output_mode, task.output_mode[:3].upper())
                            cond = "AC3" if task.convert_audio else "RAW"
                            
                            stats = f"[{mode}|{cond}] v:{kept_v} a:{kept_a}({lang_str}) s:{kept_s}"
                        except Exception:
                            stats = ""
                        
                        # Formatting
                        prefix = " > " if idx == self.selected_idx else "   "
                        attr = curses.A_NORMAL
                        if idx == self.selected_idx:
                            attr |= curses.A_REVERSE
                            
                        if status == "FAILED":
                            color = curses.color_pair(4)
                        elif status == "COMPLETED":
                            color = curses.color_pair(2)
                        elif status == "RUNNING":
                            color = curses.color_pair(3)
                        else:
                            color = curses.color_pair(1)
                            
                        # Truncate and align
                        stats_len = len(stats)
                        max_fname_len = width - stats_len - 15
                        if max_fname_len > 5 and len(fname) > max_fname_len:
                            fname = fname[:max_fname_len-3] + "..."
                            
                        line = f"{prefix}[{status[:4]}] {fname}{owner_str}"
                        padding = " " * max(1, width - len(line) - stats_len - 1)
                        line = f"{line}{padding}{stats} "
                        
                        self.app.stdscr.addstr(y, 0, line[:width].ljust(width), attr | color)
                        
                        # If selected, show error message if failed
                        if idx == self.selected_idx and task.error_message:
                            err = f" Error: {task.error_message} "
                            if len(err) > width - 2:
                                err = err[:width - 5] + "..."
                            if len(line.split(" [")[0]) + len(err) < width:  # Try to fit before stats
                                self.app.stdscr.addstr(y, width - stats_len - len(err) - 2, err, curses.color_pair(4))

        # Footer
        footer = " [SPACE] Pause/Resume Queue | [D] Delete | [C] Clear Completed | [UP/DOWN] Select | [Q/ESC] Back "
        self.app.stdscr.addstr(height - 1, 0, footer.center(width)[:width-1], curses.color_pair(3))
        self.app.stdscr.refresh()

    def handle_input(self, key):
        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
            self.app.switch_view(self.back_view)
        elif key == curses.KEY_UP:
            if self.selected_idx > 0:
                self.selected_idx -= 1
                if self.selected_idx < self.scroll_idx:
                    self.scroll_idx = self.selected_idx
        elif key == curses.KEY_DOWN:
            if self.selected_idx < len(self.tasks) - 1:
                self.selected_idx += 1
                list_height = self.app.stdscr.getmaxyx()[0] - 6
                if self.selected_idx >= self.scroll_idx + list_height:
                    self.scroll_idx += 1
        elif key == curses.KEY_PPAGE:
            list_height = self.app.stdscr.getmaxyx()[0] - 6
            self.selected_idx = max(0, self.selected_idx - list_height)
            self.scroll_idx = max(0, self.scroll_idx - list_height)
        elif key == curses.KEY_NPAGE:
            list_height = self.app.stdscr.getmaxyx()[0] - 6
            self.selected_idx = min(len(self.tasks) - 1, self.selected_idx + list_height)
            self.scroll_idx = min(max(0, len(self.tasks) - list_height), self.scroll_idx + list_height)
        elif key == ord(' '):
            if self.worker.is_running():
                self.worker.stop()
            else:
                self.worker.start()
        elif key in (ord('d'), ord('D')):
            if self.tasks:
                task = self.tasks[self.selected_idx]
                if task.status != "running":
                    self.qm.remove_task(task.id)
                    self._refresh_tasks()
        elif key in (ord('c'), ord('C')):
            self.qm.clear_completed()
            self._refresh_tasks()
            self.selected_idx = 0
            self.scroll_idx = 0

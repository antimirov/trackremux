import curses
import os
import threading
import time

from ..core.converter import MediaConverter
from .constants import KEY_ESC, KEY_Q_LOWER, KEY_Q_UPPER


class BatchProgressView:
    def __init__(self, app, batch_group, template_media, back_view):
        self.app = app
        self.batch_group = batch_group
        self.template_media = template_media
        self.back_view = back_view
        self.logs = []
        self.logs_lock = threading.Lock()

        # Batch State
        self.files_to_process = list(batch_group.files)
        self.current_idx = 0
        self.results = []  # List of status strings/results
        self.failed_files = []

        # Current File State
        self.current_file = None
        self.process = None
        self.percent = 0
        self.frame_status = ""
        self.status = "Initializing Batch..."

        self.done = False
        self.cancelled = False
        self.success = False

        # Timing
        self.start_time = time.time()
        self.end_time = None

        # Start conversion thread
        self.thread = threading.Thread(target=self._run_batch)
        self.thread.daemon = True
        self.thread.start()

    def _apply_template(self, target_file):
        """Copies track config from template to target file."""
        # Structure guaranteed by fingerprints, but index bounds are checked for safety.
        template_tracks = self.template_media.tracks

        # We need to map by index to be robust-ish
        # Or just zip? Fingerprint guarantees lengths match.
        for i, t_track in enumerate(target_file.tracks):
            if i < len(template_tracks):
                tmpl = template_tracks[i]
                t_track.enabled = tmpl.enabled
                t_track.language = tmpl.language
                # Propagate manual language override? Yes.

                # External tracks?
                # If template has external track, target might not have it attached yet?
                # fingerprint wouldn't match, so they wouldn't be in this batch.
                pass

    def _run_batch(self):
        try:
            for i, f in enumerate(self.files_to_process):
                if self.cancelled:
                    break

                self.current_idx = i
                self.current_file = f
                self.percent = 0
                self.frame_status = ""

                fname = os.path.basename(f.filename)
                self.status = f"Processing {i+1}/{len(self.files_to_process)}: {fname}"

                # prepare output names
                base_name = os.path.splitext(f.filename)[0]
                output_name = f"converted_{base_name}.mkv"
                temp_output = f"temp_{base_name}.mkv"

                # Apply config
                self._apply_template(f)

                # Estimate size?
                # self.estimated_size_mb = ...

                # Run conversion
                try:
                    self.process = MediaConverter.convert(f, temp_output)

                    # Read loop similar to ProgressView
                    for line in self.process.stdout:
                        if self.cancelled:
                            break
                        self._update_status(line, f)

                    if self.cancelled:
                        break

                    self.process.wait()

                    if self.process.returncode == 0:
                        # Success move
                        if os.path.exists(temp_output):
                            try:
                                if os.path.exists(output_name):
                                    os.remove(output_name)
                                os.rename(temp_output, output_name)
                                self.results.append(f"SUCCESS: {fname}")
                            except Exception as e:
                                self.results.append(f"ERROR moving {fname}: {e}")
                                self.failed_files.append(f)
                        else:
                            self.results.append(f"ERROR: No output for {fname}")
                            self.failed_files.append(f)
                    else:
                        self.results.append(f"FAILED: {fname} (code {self.process.returncode})")
                        self.failed_files.append(f)

                except Exception as e:
                    self.results.append(f"EXCEPTION {fname}: {e}")
                    self.failed_files.append(f)

            self.end_time = time.time()
            self.done = True

            if self.cancelled:
                self.status = "Batch Cancelled."
                self.success = False
            else:
                failure_count = len(self.failed_files)
                if failure_count == 0:
                    self.status = "Batch Completed Successfully!"
                    self.success = True
                else:
                    self.status = f"Batch Completed with {failure_count} errors."
                    self.success = False

        except Exception as e:
            self.status = f"Critical Batch Error: {e}"
            self.done = True
            self.success = False

    def cancel(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except:
                pass
        self.cancelled = True
        self.status = "Cancelling Batch..."

    def _update_status(self, line, current_file):
        # ... logic derived from ProgressView ...
        # Simplified for brevity here, reused mostly
        line = line.strip()
        if not line:
            return

        is_internal = False
        if "=" in line:
            parts = line.split("=", 1)
            if len(parts) == 2:
                key, value = [p.strip() for p in parts]
                if key == "progress" and value == "end":
                    self.percent = 100
                elif key == "out_time_ms" and current_file.duration > 0:
                    try:
                        ms = float(value)
                        self.percent = int((ms / 1000000.0 / current_file.duration) * 100)
                        self.percent = max(0, min(100, self.percent))
                    except Exception:
                        pass
                    is_internal = True

        if line.startswith("frame="):
            self.frame_status = line
        elif not is_internal:
            with self.logs_lock:
                for part in line.split("\r"):
                    part = part.strip()
                    if part and not part.startswith("frame="):
                        self.logs.append(part)
                if len(self.logs) > 200:
                    self.logs = self.logs[-200:]

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        # Header
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)
        self.app.stdscr.addstr(0, 1, "[Q/ESC] CANCEL BATCH", curses.color_pair(5))

        title = f" Batch Processing: {self.batch_group.name} "
        if width > len(title) + 20:
            self.app.stdscr.addstr(0, (width - len(title)) // 2, title)
        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Main Status
        y = 2
        progress_str = f" File {self.current_idx + 1} of {len(self.files_to_process)} "
        self.app.stdscr.addstr(y, 1, progress_str, curses.A_BOLD)

        if self.current_file:
            fname = os.path.basename(self.current_file.filename)
            self.app.stdscr.addstr(y + 1, 1, f" Current: {fname} ", curses.color_pair(2))

        # Bar
        bar_width = min(60, width - 15)
        filled = int(bar_width * self.percent / 100)
        bar = "[" + "=" * filled + " " * (bar_width - filled) + "]"
        self.app.stdscr.addstr(
            y + 3, 1, f" {bar} {self.percent}% ".center(width), curses.color_pair(3)
        )

        self.app.stdscr.addstr(y + 5, 1, self.status.center(width), curses.color_pair(3))

        if self.frame_status:
            self.app.stdscr.addstr(y + 6, 1, self.frame_status.center(width), curses.A_DIM)

        # History/Results
        res_y = y + 8
        max_res = height - res_y - 2
        if max_res > 0:
            self.app.stdscr.addstr(res_y - 1, 1, " Completed: ", curses.A_UNDERLINE)
            # Show last few results
            visible_res = self.results[-max_res:]
            for i, res in enumerate(visible_res):
                self.app.stdscr.addstr(res_y + i, 2, res[: width - 4])

        # Footer
        if self.done:
            footer = " [ANY KEY] Return to Explorer "
            # Pass return logic? The user might want to go back to file list.
        else:
            footer = " [Q/ESC] Cancel Batch "

        self.app.stdscr.addstr(
            height - 1, 0, footer.center(width)[: width - 1], curses.color_pair(3)
        )
        self.app.stdscr.refresh()

    def handle_input(self, key):
        if self.done:
            # Navigate back to the FileExplorer, skipping intermediate views if possible.
            if hasattr(self.back_view, "back_view") and self.back_view.back_view:
                target = self.back_view.back_view
                # If target is BatchSelector, go one more up
                if target.__class__.__name__ == "BatchSelectorView":
                    target = target.back_view

                self.app.switch_view(target)
            else:
                self.app.switch_view(None)
            return

        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
            self.cancel()

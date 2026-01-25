import curses
import os
import threading
import time

from ..core.converter import MediaConverter
from .constants import KEY_ESC, KEY_Q_LOWER, KEY_Q_UPPER
from .formatters import format_duration, format_size


class ProgressView:
    def __init__(self, app, media_file, back_view):
        self.app = app
        self.media_file = media_file
        self.back_view = back_view
        self.logs = []
        self.logs_lock = threading.Lock()
        self.done = False
        self.cancelled = False
        self.success = False
        self.percent = 0
        self.status = "Starting conversion..."
        self.frame_status = ""
        self.process = None

        # Timing
        self.start_time = time.time()
        self.end_time = None

        # Build command and estimate size
        base_name = os.path.splitext(self.media_file.filename)[0]
        self.output_name = f"converted_{base_name}.mkv"
        self.temp_output = f"temp_{base_name}.mkv"
        self.ffmpeg_cmd = MediaConverter.build_ffmpeg_command(self.media_file, self.temp_output)
        self.estimated_size_mb = MediaConverter.estimate_output_size(self.media_file) / 1024 / 1024
        self.actual_size_mb = 0.0

        # Get total frames for progress tracking
        self.total_frames = 0
        for t in self.media_file.tracks:
            if t.codec_type == "video" and t.nb_frames:
                self.total_frames = max(self.total_frames, t.nb_frames)

        # Start conversion in a separate thread
        self.thread = threading.Thread(target=self._run_conversion)
        self.thread.daemon = True
        self.thread.start()

    def _run_conversion(self):
        try:
            self.process = MediaConverter.convert(self.media_file, self.temp_output)

            # Read output in real-time
            for line in self.process.stdout:
                if self.cancelled:
                    break
                self._update_status(line)

            if not self.cancelled:
                self.process.wait()
                self.end_time = time.time()
                self.success = self.process.returncode == 0

                duration_str = format_duration(self.end_time - self.start_time)

                if self.success:
                    if os.path.exists(self.temp_output):
                        final_size_mb = os.path.getsize(self.temp_output) / 1024 / 1024
                        self.status = f"Success! Final size: {format_size(final_size_mb)}"
                        try:
                            if os.path.exists(self.output_name):
                                os.remove(self.output_name)
                            os.rename(self.temp_output, self.output_name)
                        except Exception as e:
                            self.status = f"Error moving file: {e}"
                    else:
                        self.status = "Success! (File moved/renamed)"
                else:
                    self.status = f"Conversion failed (code {self.process.returncode})."
            else:
                self.end_time = time.time()
                self.status = "Conversion cancelled."

        except Exception as e:
            self.success = False
            self.end_time = time.time()
            self.status = f"Error: {e}"
        finally:
            self.done = True

    def cancel(self):
        if self.process and self.process.poll() is None:
            self.cancelled = True
            try:
                self.process.terminate()
            except:
                pass
            self.status = "Cancelling..."

    def _update_status(self, line):
        line = line.strip()
        if not line:
            return

        is_progress_internal = False
        if "=" in line:
            parts = line.split("=", 1)
            if len(parts) == 2:
                key, value = [p.strip() for p in parts]

                progress_keys = (
                    "frame",
                    "fps",
                    "bitrate",
                    "total_size",
                    "out_time_ms",
                    "out_time_us",
                    "out_time",
                    "dup_frames",
                    "drop_frames",
                    "speed",
                    "progress",
                )

                if key in progress_keys or key.startswith("stream_"):
                    is_progress_internal = True
                    if key == "frame" and value.isdigit():
                        current_frame = int(value)
                        if self.total_frames > 0:
                            self.percent = int((current_frame / self.total_frames) * 100)
                    elif key in ("out_time_ms", "out_time_us") and self.percent == 0:
                        try:
                            divisor = 1000000.0 if key == "out_time_us" else 1000.0
                            current_seconds = float(value) / divisor
                            if self.media_file.duration > 0:
                                self.percent = int(
                                    (current_seconds / self.media_file.duration) * 100
                                )
                        except:
                            pass
                    elif key == "total_size" and value.isdigit():
                        self.actual_size_mb = int(value) / 1024 / 1024
                    elif key == "progress" and value == "end":
                        self.percent = 100

                    self.percent = max(0, min(100, self.percent))

        if line.startswith("frame="):
            self.frame_status = line
        elif not is_progress_internal:
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
        self.app.stdscr.addstr(0, 1, "[Q/ESC] CANCEL", curses.color_pair(5))
        if width > 10:
            self.app.stdscr.addstr(0, width - 4, "[X]", curses.color_pair(5))

        label = " Converting: "
        fname = f"{self.media_file.filename} "
        full_header_len = len(label) + len(fname)

        if full_header_len < width - 20:
            start_x = (width - full_header_len) // 2
            self.app.stdscr.addstr(0, start_x, label, curses.color_pair(1) | curses.A_BOLD)
            self.app.stdscr.addstr(0, start_x + len(label), fname, curses.A_DIM)

        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Output Info
        target_info = f" Converting to: {self.output_name} "
        self.app.stdscr.addstr(1, 0, target_info.center(width), curses.A_BOLD)

        # Command (Wrapped)
        self.app.stdscr.addstr(3, 0, " Command: ", curses.color_pair(1) | curses.A_BOLD)
        cmd_str = " ".join(self.ffmpeg_cmd)

        y_cmd = 4
        max_cmd_lines = 3
        curr_cmd = cmd_str
        for _ in range(max_cmd_lines):
            if not curr_cmd or y_cmd >= height - 10:
                break
            line_part = curr_cmd[: width - 4]
            self.app.stdscr.addstr(y_cmd, 2, line_part, curses.A_DIM | curses.A_ITALIC)
            curr_cmd = curr_cmd[width - 4 :]
            y_cmd += 1

        y_offset = y_cmd + 1

        # Status & Size
        size_info = f" Est. file size: {format_size(self.estimated_size_mb)} | Current: {format_size(self.actual_size_mb)} "
        self.app.stdscr.addstr(y_offset, 0, size_info.center(width), curses.color_pair(2))

        status_color = (
            curses.color_pair(2)
            if self.success
            else (curses.color_pair(4) if self.done and not self.success else curses.color_pair(3))
        )
        self.app.stdscr.addstr(y_offset + 1, 0, self.status.center(width), status_color)

        # Progress Bar
        bar_width = min(60, width - 15)
        filled = int(bar_width * self.percent / 100)
        bar = "[" + "=" * filled + " " * (bar_width - filled) + "]"
        self.app.stdscr.addstr(
            y_offset + 3, 0, f" {bar} {self.percent}% ".center(width), curses.color_pair(3)
        )

        # Frame Status & Elapsed Time
        elapsed = time.time() - self.start_time
        if self.done and self.end_time:
            elapsed = self.end_time - self.start_time

        time_status = f" Total Time: {format_duration(elapsed)} "
        attr = curses.color_pair(2) | curses.A_BOLD if self.done else curses.A_DIM
        self.app.stdscr.addstr(y_offset + 4, 0, time_status.center(width), attr)

        if self.frame_status:
            self.app.stdscr.addstr(
                y_offset + 5, 0, self.frame_status.center(width)[: width - 1], curses.A_DIM
            )

        # Logs
        log_y_start = y_offset + 7
        if log_y_start < height - 2:
            self.app.stdscr.addstr(
                log_y_start - 1, 1, " FFmpeg Output: ", curses.A_BOLD | curses.A_UNDERLINE
            )
            y = log_y_start
            with self.logs_lock:
                max_visible = height - log_y_start - 2
                visible_logs = self.logs[-max_visible:] if max_visible > 0 else []
                for log in visible_logs:
                    if y < height - 2:
                        self.app.stdscr.addstr(y, 2, log[: width - 4], curses.A_DIM)
                        y += 1

        # Footer
        if self.done:
            footer = " [ANY KEY] Return to Editor "
        else:
            footer = " [Q/ESC] Cancel Conversion "
        self.app.stdscr.addstr(
            height - 1, 0, footer.center(width)[: width - 1], curses.color_pair(3)
        )

        self.app.stdscr.refresh()

    def handle_input(self, key):
        height, width = self.app.stdscr.getmaxyx()

        if self.done:
            # Pass success status back to TrackEditor
            self.back_view.status_message = self.status
            self.app.switch_view(self.back_view)
            return  # Exit after handling done state

        # Handle cancellation if not done
        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
            self.cancel()
        elif key == curses.KEY_MOUSE and self.app.mouse_enabled:
            try:
                _, mx, my, _, _ = curses.getmouse()
                if my == 0:  # Click in the header row
                    # [Q] CANCEL at left (1-10) or [X] at right (width-4 to width-1)
                    if (1 <= mx <= 10) or (mx >= width - 4 and mx < width):
                        self.cancel()
            except:
                pass

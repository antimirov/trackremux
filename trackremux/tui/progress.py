import curses
import os
import shutil
import threading
import time

from ..core.converter import MediaConverter
from ..core.models import OutputMode
from .constants import KEY_ESC, KEY_Q_LOWER, KEY_Q_UPPER
from .formatters import format_duration, format_size

# Hidden directory names used for staging and trash
STAGING_DIR = ".trackremux_staging"
TRASH_DIR = ".trackremux_trash"


def resolve_output_path(media_file, output_mode: OutputMode) -> str:
    """
    Determine the final destination path for the converted file,
    based on the chosen output mode.

    LOCAL     → <cwd>/converted_<name>.mkv
    REMOTE    → <source_dir>/converted_<name>.mkv
    OVERWRITE → <source_dir>/<original_name>  (same path, same name)
    """
    base_name = os.path.splitext(media_file.filename)[0]
    source_dir = os.path.dirname(os.path.abspath(media_file.path))

    if output_mode == OutputMode.LOCAL:
        return os.path.join(os.getcwd(), f"converted_{base_name}.mkv")
    elif output_mode == OutputMode.REMOTE:
        return os.path.join(source_dir, f"converted_{base_name}.mkv")
    elif output_mode == OutputMode.OVERWRITE:
        return media_file.path  # Will be replaced atomically
    return os.path.join(os.getcwd(), f"converted_{base_name}.mkv")


def resolve_batch_output_path(media_file, output_mode: OutputMode, batch_source_dir: str) -> str:
    """
    Determine the output path for a file in a batch conversion.

    Instead of prefixing each file with converted_, batch operations create
    a converted_<dir_name>/ directory and keep original filenames inside.

    LOCAL     → <cwd>/converted_<dir_name>/<original_name>.mkv
    REMOTE    → <source_parent>/converted_<dir_name>/<original_name>.mkv
    OVERWRITE → <source_dir>/<original_name>  (same path, same name)
    """
    if output_mode == OutputMode.OVERWRITE:
        return media_file.path

    dir_name = os.path.basename(os.path.normpath(batch_source_dir))
    base_name = os.path.splitext(media_file.filename)[0]
    out_filename = f"{base_name}.mkv"

    if output_mode == OutputMode.LOCAL:
        out_dir = os.path.join(os.getcwd(), f"converted_{dir_name}")
    else:  # REMOTE
        parent_dir = os.path.dirname(os.path.normpath(batch_source_dir))
        out_dir = os.path.join(parent_dir, f"converted_{dir_name}")

    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, out_filename)


def resolve_staging_path(output_path: str) -> str:
    """Return a path inside the hidden staging dir next to the output file."""
    output_dir = os.path.dirname(os.path.abspath(output_path))
    staging_dir = os.path.join(output_dir, STAGING_DIR)
    os.makedirs(staging_dir, exist_ok=True)
    return os.path.join(staging_dir, os.path.basename(output_path))


def atomic_finalize(staging_path: str, final_path: str, output_mode: OutputMode) -> None:
    """
    Move the staged file to its final destination atomically.

    OVERWRITE mode: move original to .trackremux_trash/, then rename staged.
    Other modes: simply rename staged → final.

    Falls back to shutil.move if os.rename fails (cross-volume).
    """
    if output_mode == OutputMode.OVERWRITE and os.path.exists(final_path):
        # Move original to trash (same volume → instant)
        trash_dir = os.path.join(os.path.dirname(final_path), TRASH_DIR)
        os.makedirs(trash_dir, exist_ok=True)
        trash_path = os.path.join(trash_dir, os.path.basename(final_path))
        try:
            os.rename(final_path, trash_path)
        except OSError:
            shutil.move(final_path, trash_path)

    try:
        os.rename(staging_path, final_path)
    except OSError:
        shutil.move(staging_path, final_path)

    # Clean up empty staging directory
    staging_dir = os.path.dirname(staging_path)
    try:
        if os.path.isdir(staging_dir) and not os.listdir(staging_dir):
            os.rmdir(staging_dir)
    except OSError:
        pass


class ProgressView:
    def __init__(
        self,
        app,
        media_file,
        back_view,
        output_mode: OutputMode = OutputMode.LOCAL,
        convert_audio: bool = False,
    ):
        self.app = app
        self.media_file = media_file
        self.back_view = back_view
        self.output_mode = output_mode
        self.convert_audio = convert_audio
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

        # Resolve paths
        self.output_path = resolve_output_path(media_file, output_mode)
        self.staging_path = resolve_staging_path(self.output_path)
        self.output_name = os.path.basename(self.output_path)

        self.ffmpeg_cmd = MediaConverter.build_ffmpeg_command(
            media_file, self.staging_path, convert_audio=convert_audio
        )
        self.estimated_size_mb = MediaConverter.estimate_output_size(media_file) / 1024 / 1024
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
            self.process = MediaConverter.convert(
                self.media_file, self.staging_path, convert_audio=self.convert_audio
            )

            # Read output in real-time
            for line in self.process.stdout:
                if self.cancelled:
                    break
                self._update_status(line)

            if not self.cancelled:
                self.process.wait()
                self.end_time = time.time()
                self.success = self.process.returncode == 0

                if self.success:
                    if os.path.exists(self.staging_path):
                        final_size_mb = os.path.getsize(self.staging_path) / 1024 / 1024
                        try:
                            atomic_finalize(self.staging_path, self.output_path, self.output_mode)
                            self.status = f"Success! Final size: {format_size(final_size_mb)}"
                        except Exception as e:
                            self.status = f"Error finalizing file: {e}"
                    else:
                        self.status = "Success! (File moved/renamed)"
                else:
                    # Clean up partial staging file on failure
                    if os.path.exists(self.staging_path):
                        try:
                            os.remove(self.staging_path)
                        except Exception:
                            pass
                    self.status = f"Conversion failed (code {self.process.returncode})."
            else:
                self.end_time = time.time()
                # Clean up partial staging file on cancel
                if os.path.exists(self.staging_path):
                    try:
                        os.remove(self.staging_path)
                    except Exception:
                        pass
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
            except Exception:
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
                    elif key in ("out_time_ms", "out_time_us"):
                        try:
                            divisor = 1000000.0 if key == "out_time_us" else 1000.0
                            current_seconds = float(value) / divisor
                            if self.media_file.duration > 0:
                                time_pct = int((current_seconds / self.media_file.duration) * 100)
                                if time_pct > self.percent:
                                    self.percent = time_pct
                        except Exception:
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
        mode_label = self.output_mode.value.upper()
        audio_label = " | Audio: AC3 640k" if self.convert_audio else ""
        target_info = f" [{mode_label}] → {self.output_name}{audio_label} "
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
        if self.done:
            # Pass success status back to TrackEditor
            self.back_view.status_message = self.status
            self.app.switch_view(self.back_view)
            return

        # Handle cancellation if not done
        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
            self.cancel()
        elif key == curses.KEY_MOUSE and self.app.mouse_enabled:
            try:
                _, mx, my, _, _ = curses.getmouse()
                height, width = self.app.stdscr.getmaxyx()
                if my == 0:  # Click in the header row
                    if (1 <= mx <= 10) or (mx >= width - 4 and mx < width):
                        self.cancel()
            except Exception:
                pass

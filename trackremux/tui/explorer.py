import curses
import os
import threading
import time
import unicodedata

from ..core.probe import MediaProbe
from .constants import (
    FILE_LIST_Y_OFFSET,
    KEY_A_LOWER,
    KEY_A_UPPER,
    KEY_ENTER,
    KEY_M_LOWER,
    KEY_M_UPPER,
    KEY_N_LOWER,
    KEY_N_UPPER,
    KEY_Q_LOWER,
    KEY_Q_UPPER,
    KEY_S_LOWER,
    KEY_S_UPPER,
    KEY_T_LOWER,
    KEY_T_UPPER,
    MARGIN,
)
from .formatters import format_size


def get_display_name(name, width):
    """Normalize and truncate name to fit visual width."""
    normalized = unicodedata.normalize("NFC", name)
    if len(normalized) <= width:
        return normalized.ljust(width)
    return normalized[: width - 3] + "..."


class FileExplorer:
    def __init__(self, app, path):
        self.app = app
        self.path = os.path.abspath(path)
        self.filenames = self._get_video_files()

        # Metadata storage: {filename: media_file_object}
        self.metadata = {}
        self.metadata_lock = threading.Lock()

        self.selected_idx = 0
        self.scroll_idx = 0
        self.sort_mode = "name"  # 'name', 'size', 'tracks', 'audio_size'
        self.sort_reverse = False
        self.probed_count = 0
        self.total_count = len(self.filenames)

        # Start background prober
        self.stopped = False
        self.prober_thread = threading.Thread(target=self._background_probe)
        self.prober_thread.daemon = True
        self.prober_thread.start()

    def _get_video_files(self):
        extensions = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
        try:
            files = [
                f
                for f in os.listdir(self.path)
                if f.lower().endswith(extensions)
                and not f.startswith("converted_")
                and not f.startswith("temp_")
            ]
            return sorted(files)
        except Exception:
            return []

    def _background_probe(self):
        # First pass: get sizes (instant)
        for f in self.filenames:
            if self.stopped:
                return
            try:
                size = os.path.getsize(os.path.join(self.path, f))
                with self.metadata_lock:
                    if f not in self.metadata:
                        self.metadata[f] = type(
                            "obj",
                            (object,),
                            {"size_bytes": size, "probed": False, "tracks": [], "filename": f},
                        )
            except:
                pass

        # Second pass: deep probe (slow)
        for f in self.filenames:
            if self.stopped:
                return
            try:
                full_path = os.path.join(self.path, f)
                media = MediaProbe.probe(full_path)
                with self.metadata_lock:
                    self.metadata[f] = media
                    media.probed = True
            except:
                pass
            with self.metadata_lock:
                self.probed_count += 1
            time.sleep(0.01)

    def _get_sorted_files(self):
        with self.metadata_lock:
            rev = self.sort_reverse
            if self.sort_mode == "name":
                return sorted(self.filenames, reverse=rev)
            elif self.sort_mode == "size":
                return sorted(
                    self.filenames,
                    key=lambda f: self.metadata.get(f).size_bytes if f in self.metadata else 0,
                    reverse=rev,
                )
            elif self.sort_mode == "tracks":
                return sorted(
                    self.filenames,
                    key=lambda f: (
                        len([t for t in self.metadata.get(f).tracks if t.codec_type == "audio"])
                        if f in self.metadata and hasattr(self.metadata[f], "tracks")
                        else 0
                    ),
                    reverse=rev,
                )
            elif self.sort_mode == "audio_size":
                return sorted(
                    self.filenames,
                    key=lambda f: (
                        sum(
                            (t.bit_rate * getattr(self.metadata[f], "duration", 0)) / 8
                            for t in self.metadata.get(f).tracks
                            if t.codec_type == "audio" and t.bit_rate
                        )
                        if f in self.metadata and hasattr(self.metadata[f], "tracks")
                        else 0
                    ),
                    reverse=rev,
                )
        return self.filenames

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        sorted_files = self._get_sorted_files()

        # Header
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)  # Clear the line

        # [Q] QUIT at the left
        self.app.stdscr.addstr(0, 1, "[Q] QUIT", curses.color_pair(5))

        # [X] at the right
        if width > 10:
            self.app.stdscr.addstr(0, width - 4, "[X]", curses.color_pair(5))

        label = " Media Browser: "
        path_str = f"{self.path} "
        full_header_len = len(label) + len(path_str)

        if full_header_len < width - 20:
            # Shift left bit (formerly centered) to allow more room for progress
            start_x = 12
            self.app.stdscr.addstr(0, start_x, label, curses.color_pair(1) | curses.A_BOLD)
            self.app.stdscr.addstr(0, start_x + len(label), path_str, curses.A_DIM)
            header_end = start_x + full_header_len
        else:
            header_end = 10  # Fallback if way too small

        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Probing Progress
        with self.metadata_lock:
            p_count = self.probed_count
            t_count = self.total_count

        if t_count > 0:
            if p_count < t_count:
                # Progress bar (10 chars wide)
                bar_len = 10
                filled = int(p_count / t_count * bar_len)
                bar = "#" * filled + "-" * (bar_len - filled)
                progress_text = f" Scanning: [{bar}] {p_count}/{t_count} "
                # Position after the Media Browser info
                start_col = header_end + 2
                if width > start_col + len(progress_text):
                    self.app.stdscr.addstr(0, start_col, progress_text, curses.color_pair(2))
            else:
                # Brief completion message
                complete_text = " Scan Complete "
                start_col = header_end + 2
                if width > start_col + len(complete_text):
                    self.app.stdscr.addstr(
                        0, start_col, complete_text, curses.color_pair(2) | curses.A_BOLD
                    )

        # Sorted By Label
        sort_label = self.sort_mode.replace("_", " ").title()
        dir_arrow = "↓" if self.sort_reverse else "↑"
        sort_text = f" [ Sorted by: {sort_label} {dir_arrow} ] "
        if width > len(sort_text):  # Ensure it fits on the right
            self.app.stdscr.addstr(
                0, width - len(sort_text), sort_text, curses.color_pair(3) | curses.A_BOLD
            )

        # Column Headers
        # track_info (19) + space (1) + name + space (1) + lang (17) + size (10)
        fixed_width = 51 + MARGIN  # 19 + 1 + 17 + 2 + 10 + 2
        name_col_width = max(20, width - fixed_width)

        headers = f" {'TRACKS / AUDIO SIZE':<19} {'FILENAME':<{name_col_width}} {'LANGUAGES':<17}  {'SIZE':>10}"
        self.app.stdscr.addstr(
            1, 0, headers[: width - 1].ljust(width - 1), curses.A_BOLD | curses.A_UNDERLINE
        )

        # File List
        list_height = height - 5
        if self.selected_idx >= len(sorted_files):
            self.selected_idx = max(0, len(sorted_files) - 1)

        if self.selected_idx < self.scroll_idx:
            self.scroll_idx = self.selected_idx
        elif self.selected_idx >= self.scroll_idx + list_height:
            self.scroll_idx = self.selected_idx - list_height + 1

        visible_files = sorted_files[self.scroll_idx : self.scroll_idx + list_height]

        for i, filename in enumerate(visible_files):
            idx = i + self.scroll_idx
            attr = curses.A_NORMAL
            if idx == self.selected_idx:
                attr = curses.color_pair(5)

            with self.metadata_lock:
                media = self.metadata.get(filename)

            if media and getattr(media, "probed", False):
                audio_tracks = [t for t in media.tracks if t.codec_type == "audio"]
                audio_size_mb = sum(
                    (t.bit_rate * media.duration) / 8 / 1024 / 1024
                    for t in audio_tracks
                    if t.bit_rate
                )
                langs = ",".join(set(t.language for t in audio_tracks if t.language)) or "und"
                size_mb = media.size_bytes / 1024 / 1024

                size_str = format_size(size_mb, precision=1)
                a_size_str = format_size(audio_size_mb, precision=1).replace(" ", "")

                track_info = f"[{len(audio_tracks):>2} aud: {a_size_str:>8} ]"
                display_filename = get_display_name(filename, name_col_width)
                line = f" {track_info} {display_filename} ({langs[:15]:<15})  {size_str:>10}"

                # Check for converted counterpart or temp status
                is_converted = filename.startswith("converted_")
                is_temp = filename.startswith("temp_")
                has_converted = os.path.exists(os.path.join(self.path, "converted_" + filename))

                self.app.stdscr.addstr(
                    i + FILE_LIST_Y_OFFSET, 0, line[: width - 1].ljust(width - 1), attr
                )

                # Overwrite size with color if interesting
                if idx != self.selected_idx:
                    size_x = len(line) - 10
                    if is_converted:
                        self.app.stdscr.addstr(
                            i + FILE_LIST_Y_OFFSET,
                            size_x,
                            f"{size_str:>10}",
                            curses.color_pair(2) | curses.A_BOLD,
                        )
                    elif is_temp:
                        self.app.stdscr.addstr(
                            i + FILE_LIST_Y_OFFSET,
                            size_x,
                            f"{size_str:>10}",
                            curses.color_pair(3) | curses.A_DIM,
                        )
                    elif has_converted:
                        self.app.stdscr.addstr(
                            i + FILE_LIST_Y_OFFSET, size_x, f"{size_str:>10}", curses.color_pair(1)
                        )
                continue  # Skip the default addstr below
            elif media:
                size_mb = media.size_bytes / 1024 / 1024
                size_str = format_size(size_mb, precision=1)
                display_filename = get_display_name(filename, name_col_width)
                line = f" [ .. probing ..   ] {display_filename} {' ':17}  {size_str:>10}"
                if not attr & curses.color_pair(5):
                    attr |= curses.A_DIM
            else:
                line = f" [ ?? probing ??   ] {get_display_name(filename, name_col_width)}"
                if not attr & curses.color_pair(5):
                    attr |= curses.A_DIM

            self.app.stdscr.addstr(
                i + FILE_LIST_Y_OFFSET, 0, line[: width - 1].ljust(width - 1), attr
            )

        # Footer
        mouse_status = "APP" if self.app.mouse_enabled else "TERM"
        sort_footer = " Sort: [N]ame, [S]ize, [T]racks, [A]ud Size "
        mouse_footer = f" [M] Mouse Select: {mouse_status} "
        action_footer = " [ENTER] Open, [Q] Quit "
        full_footer = f"{sort_footer} | {mouse_footer} | {action_footer}"
        self.app.stdscr.addstr(
            height - 1, 0, full_footer.center(width)[: width - 1], curses.color_pair(3)
        )

        self.app.stdscr.refresh()

    def handle_input(self, key):
        height, width = self.app.stdscr.getmaxyx()
        sorted_files = self._get_sorted_files()
        list_height = height - 5

        if key in (KEY_Q_LOWER, KEY_Q_UPPER):
            if self.app.mouse_enabled:
                self.app.toggle_mouse()
            self.stopped = True
            self.app.switch_view(None)
        elif key in (KEY_M_LOWER, KEY_M_UPPER):
            self.app.toggle_mouse()
        elif key in (KEY_N_LOWER, KEY_N_UPPER):
            if self.sort_mode == "name":
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_mode = "name"
                self.sort_reverse = False
        elif key in (KEY_S_LOWER, KEY_S_UPPER):
            if self.sort_mode == "size":
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_mode = "size"
                self.sort_reverse = True  # Default descending for size
        elif key in (KEY_T_LOWER, KEY_T_UPPER):
            if self.sort_mode == "tracks":
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_mode = "tracks"
                self.sort_reverse = True
        elif key in (KEY_A_LOWER, KEY_A_UPPER):
            if self.sort_mode == "audio_size":
                self.sort_reverse = not self.sort_reverse
            else:
                self.sort_mode = "audio_size"
                self.sort_reverse = True
        elif key == curses.KEY_UP:
            if self.selected_idx > 0:
                self.selected_idx -= 1
        elif key == curses.KEY_DOWN:
            if self.selected_idx < len(sorted_files) - 1:
                self.selected_idx += 1
        elif key == curses.KEY_PPAGE:  # Page Up
            self.selected_idx = max(0, self.selected_idx - list_height)
        elif key == curses.KEY_NPAGE:  # Page Down
            self.selected_idx = min(len(sorted_files) - 1, self.selected_idx + list_height)
        elif key == curses.KEY_HOME:
            self.selected_idx = 0
        elif key == curses.KEY_END:
            self.selected_idx = len(sorted_files) - 1
        elif key == curses.KEY_MOUSE:
            if not self.app.mouse_enabled:
                return
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if bstate & curses.BUTTON_SHIFT:
                    return  # Ignore if shift is held to allow terminal selection

                # Header [Q] QUIT button or [X] button
                is_quit = my == 0 and 1 <= mx <= 8
                is_x = my == 0 and mx >= width - 4

                if is_quit or is_x:
                    if self.app.mouse_enabled:
                        self.app.toggle_mouse()
                    self.stopped = True
                    self.app.switch_view(None)
                    return

                # List starts at row FILE_LIST_Y_OFFSET.
                row_in_list = my - FILE_LIST_Y_OFFSET
                if 0 <= row_in_list < list_height:
                    target_idx = self.scroll_idx + row_in_list
                    if target_idx < len(sorted_files):
                        if target_idx == self.selected_idx and (
                            bstate & curses.BUTTON1_DOUBLE_CLICKED
                        ):
                            # Open file on double click
                            filename = sorted_files[self.selected_idx]
                            file_path = os.path.join(self.path, filename)
                            media = self.metadata.get(file_path)
                            from .editor import TrackEditor

                            self.app.switch_view(
                                TrackEditor(self.app, media or file_path, back_view=self)
                            )
                        else:
                            self.selected_idx = target_idx
            except:
                pass
        elif key in (KEY_ENTER, curses.KEY_RIGHT):  # Enter or Right Arrow
            if sorted_files:
                filename = sorted_files[self.selected_idx]
                file_path = os.path.join(self.path, filename)
                media = self.metadata.get(file_path)
                from .editor import TrackEditor

                self.app.switch_view(TrackEditor(self.app, media or file_path, back_view=self))

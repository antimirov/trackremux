import curses
import os
import threading
import time
import unicodedata

from ..core.batch import BatchDetector
from .batch_selector import BatchSelectorView
from .constants import (
    FILE_LIST_Y_OFFSET,
    KEY_A_LOWER,
    KEY_A_UPPER,
    KEY_B_LOWER,
    KEY_B_UPPER,
    KEY_ENTER,
    KEY_ESC,
    KEY_M_LOWER,
    KEY_M_UPPER,
    KEY_N_LOWER,
    KEY_N_UPPER,
    KEY_Q_LOWER,
    KEY_Q_UPPER,
    KEY_R_LOWER,
    KEY_R_UPPER,
    KEY_S_LOWER,
    KEY_S_UPPER,
    KEY_T_LOWER,
    KEY_T_UPPER,
    MARGIN,
)
from .editor import TrackEditor
from .formatters import format_size


def get_display_name(name, width):
    """Normalize and truncate name to fit visual width."""
    normalized = unicodedata.normalize("NFC", name)
    if len(normalized) <= width:
        return normalized.ljust(width)
    return normalized[: width - 3] + "..."


class FileExplorer:
    def __init__(self, app, path, back_view=None):
        self.app = app
        self.path = os.path.abspath(path)
        self.back_view = back_view
        self.back_view = back_view

        # Initialize empty lists for async loading
        self.dirs = []
        self.files = []
        self.filenames = []
        self.loading = True

        # Metadata storage: {filename: media_file_object}
        self.metadata = {}
        self.metadata_lock = threading.Lock()

        self.selected_idx = 0
        self.scroll_idx = 0
        self.sort_mode = "name"  # 'name', 'size', 'tracks', 'audio_size'
        self.sort_reverse = False
        self.probed_count = 0
        self.total_count = 0
        self.batches = []  # Detected BatchGroup objects

        # Track priority requests to avoid spamming the scanner queue
        self.priority_requested = set()

        # Start async loading
        self.load_start_time = time.time()
        threading.Thread(target=self._async_load, daemon=True).start()

    def _shorten_path(self, path, max_len):
        """
        Shortens path using Unix-shell style (e.g. /Volumes/Media -> /V/M).
        """
        if len(path) <= max_len:
            return path
        
        parts = path.split(os.sep)
        # Handle root slash for absolute paths
        if path.startswith(os.sep):
            parts = [p for p in parts if p] # remove empty strings
            prefix = os.sep
        else:
            prefix = ""
            
        if not parts:
             return path
             
        # Always keep the last part full (current dir)
        last = parts[-1]
        
        # Iteratively shorten leading parts
        shortened_parts = []
        # We need to preserve space for the last part
        # If last part alone is too big, we just truncate the whole thing later
        
        current_len = len(prefix) + len(last) + len(parts) - 1 # separators
        
        for i, part in enumerate(parts[:-1]):
            # Try to shorten this part to 1 char
            shortened_parts.append(part[0] if part else "")
            
        # Reconstruct
        # This is a naive 'shorten all' approach. 
        # Better: Shorten from left until it fits.
        
        # Attempt to fit smartly by shrinking parts.
        candidates = list(parts[:-1]) # copy
        
        # Calculate current full length
        # len(prefix) + sum(len(p) for p in candidates) + len(last) + len(candidates) (separators)
        
        def get_len(cands):
            return len(prefix) + sum(len(c) for c in cands) + len(last) + len(cands)
            
        # Loop and shorten from left
        for i in range(len(candidates)):
             if get_len(candidates) <= max_len:
                 break
             # Shorten candidates[i]
             if candidates[i]:
                 candidates[i] = candidates[i][0]
        
        result = prefix + os.sep.join(candidates + [last])
        
        # If still too long, truncate the middle of the result? or just the end?
        if len(result) > max_len:
            # Truncate end of last part if possible, or ellipsify
             if len(result) > max_len:
                 return result[:max_len-3] + "..."
        
        return result

    def _async_load(self):
        """Load directory contents in background to allow immediate UI render."""
        try:
            self.dirs, self.files = self._get_items_separated()
            self.filenames = self.dirs + self.files
            self.total_count = len(self.files)

            # Quick size check immediately
            self._quick_size_check()

            # Submit probing tasks to global scanner (Background default for everything)
            self._submit_scan_tasks()
        except:
            pass
        finally:
            self.loading = False
            # Force refresh if possible?
            # The app loop handles it via timeout, so it will appear on next tick.

    def _quick_size_check(self):
        """Fast pass to get file sizes before probing."""
        for f in self.files:
            try:
                full_path = os.path.join(self.path, f)
                # No need to check isdir here, self.files only contains files
                size = os.path.getsize(full_path)
                with self.metadata_lock:
                    if f not in self.metadata:
                        self.metadata[f] = type(
                            "obj",
                            (object,),
                            {"size_bytes": size, "probed": False, "tracks": [], "filename": f},
                        )
            except:
                pass

    def _submit_scan_tasks(self, force=False):
        """Submit files to the global scanner background queue."""
        tasks = []
        for f in self.files:
            full_path = os.path.join(self.path, f)
            # No isdir check needed

            # We pass the filename as context to the callback so we know which entry to update
            tasks.append((full_path, lambda p, m, fname=f: self._on_probe_complete(fname, m)))

        self.app.scanner.add_background_items(tasks, force=force)

    def _detect_batches(self):
        """Run batch detection on the current set of probed files."""
        # This could be expensive, so we might want to debounce or limit it
        # But for typical folder sizes (100-200), the regex/grouping is fast.
        with self.metadata_lock:
            # Filter only fully probed MediaFile objects (not placeholders)
            probed_files = [
                m
                for m in self.metadata.values()
                if getattr(m, "probed", False) and hasattr(m, "tracks")
            ]

        # Don't run if we have very strictly few files?
        if len(probed_files) < 2:
            return

        new_batches = BatchDetector.detect_groups(probed_files)
        # Update self.batches safely
        # We don't need a lock for UI read unless we want to be super safe
        self.batches = new_batches

    def _on_probe_complete(self, filename, media):
        """Callback from global scanner when probing is done."""
        with self.metadata_lock:
            self.metadata[filename] = media
            media.probed = True
            # Update counts?
            # We don't strictly track probed_count vs total_count reliably for "Scanner"
            # because the scanner is global. But we can just count how many in our metadata have probed=True.
            self.probed_count = sum(
                1 for m in self.metadata.values() if getattr(m, "probed", False)
            )

        # Run detection occasionally?
        # Every 5 files or if done?
        if self.probed_count % 5 == 0 or self.probed_count == self.total_count:
            self._detect_batches()

        # Trigger redraw if this is the active view?
        # The main loop redraws constantly on input, but if idle, we rely on timeout.
        # APP_TIMEOUT_MS handles the refresh rate.

    def _get_items_separated(self):
        extensions = (".mkv", ".mp4", ".avi", ".mov", ".m4v")
        try:
            items = []
            for f in os.listdir(self.path):
                full = os.path.join(self.path, f)
                if os.path.isdir(full) and not f.startswith("."):
                    items.append(f)
                elif f.lower().endswith(extensions):
                    if not f.startswith("converted_") and not f.startswith("temp_"):
                        items.append(f)

            # Sort: Directories first, then files
            dims, files = [], []
            for i in items:
                if os.path.isdir(os.path.join(self.path, i)):
                    dims.append(i)
                else:
                    files.append(i)

            return sorted(dims), sorted(files)
        except Exception:
            return [], []

    def _prioritize_visible(self, force=False):
        """Re-submit visible unprobed files to the front of the scanner queue."""
        height, width = self.app.stdscr.getmaxyx()
        list_height = height - 5
        sorted_files = self._get_sorted_files()

        # Calculate visible range
        start = self.scroll_idx
        end = min(len(sorted_files), self.scroll_idx + list_height)
        visible_files = sorted_files[start:end]

        tasks_to_prioritize = []
        for filename in visible_files:
            # Skip directories
            if filename in self.dirs:
                continue

            # Check if needs probing, UNLESS forced
            needs_probing = True
            if not force:
                with self.metadata_lock:
                    if filename in self.metadata and getattr(
                        self.metadata[filename], "probed", False
                    ):
                        needs_probing = False

            if needs_probing:
                full_path = os.path.join(self.path, filename)
                tasks_to_prioritize.append(
                    (full_path, lambda p, m, fname=filename: self._on_probe_complete(fname, m))
                )

        if tasks_to_prioritize:
            # Clear previous priority items to focus on this view
            self.app.scanner.add_priority_items(
                tasks_to_prioritize, clear_priority=True, force=force
            )

    def _get_sorted_files(self):
        # Use cached dirs and files list to avoid repeated os.path.isdir calls
        dirs = self.dirs
        files = list(self.files)  # Copy to avoid mutating original

        with self.metadata_lock:
            rev = self.sort_reverse
            if self.sort_mode == "name":
                files = sorted(files, reverse=rev)
            elif self.sort_mode == "size":
                files = sorted(
                    files,
                    key=lambda f: self.metadata.get(f).size_bytes if f in self.metadata else 0,
                    reverse=rev,
                )
            elif self.sort_mode == "tracks":
                files = sorted(
                    files,
                    key=lambda f: (
                        len([t for t in self.metadata.get(f).tracks if t.codec_type == "audio"])
                        if f in self.metadata and hasattr(self.metadata[f], "tracks")
                        else 0
                    ),
                    reverse=rev,
                )
            elif self.sort_mode == "audio_size":
                files = sorted(
                    files,
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
        return dirs + files

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        sorted_files = self._get_sorted_files()

        # Header
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)  # Clear the line



        label = "Media Browser: "
        
        # Calculate available width for path
        # Width - Label - Right Area (Sort + Batch + Padding + Scanning Progress estimate)
        # Scan progress is roughly 35 chars: " Scanning: [##########] 9999/9999 "
        # Sort block is roughly 30 chars.
        # Header [X] is 4 chars.
        # Batch is variable but usually ~20 chars.
        
        # Maximize path width, but stop before overlapping.
        
        # Re-calculate right-side content first to know space?
        # Sort area x
        sort_label = self.sort_mode.replace("_", " ").title()
        dir_arrow = "↓" if self.sort_reverse else "↑"
        sort_text = f" [ Sorted by: {sort_label} {dir_arrow} ] "
        sort_x = width - len(sort_text)
        
        left_limit = sort_x
        
        if self.batches:
            batch_text = f" [B]ATCH: {len(self.batches)} groups "
            batch_x = sort_x - len(batch_text) - 2
            left_limit = batch_x
            
        # Also account for "Scanning..." text which comes AFTER the path.
        # If we render path, we implicitly push scanning text to the right.
        # But we want scanning text to be visible.
        # So: Path + Scanning should <= Left Limit.
        
        scanning_width = 35 # Reserve space for scanning status
        
        max_path_width = max(10, left_limit - len(label) - scanning_width - 2)
        
        # Shorten path
        path_str = self._shorten_path(self.path, max_path_width) + " "
        
        start_x = 0
        self.app.stdscr.addstr(0, start_x, label, curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, start_x + len(label), path_str, curses.A_DIM)
        header_end = start_x + len(label) + len(path_str)

        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Probing Progress
        with self.metadata_lock:
            p_count = self.probed_count
            t_count = self.total_count

        # Batch Indicator in Header

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

        # Sorted By Label (right-aligned)
        sort_label = self.sort_mode.replace("_", " ").title()
        dir_arrow = "↓" if self.sort_reverse else "↑"
        sort_text = f" [ Sorted by: {sort_label} {dir_arrow} ] "
        sort_x = width - len(sort_text)
        if width > len(sort_text):  # Ensure it fits
            self.app.stdscr.addstr(
                0, sort_x, sort_text, curses.color_pair(3) | curses.A_BOLD
            )

        # Batch Indicator in Header (Positioned left of Sort)
        if self.batches:
            batch_text = f" [B]ATCH: {len(self.batches)} groups "
            batch_len = len(batch_text)
            # Position it left of sort_text with some padding
            batch_x = sort_x - batch_len - 2
            
            # Ensure it doesn't overlap with left-side content (approx 40-50 chars usually)
            # But header_end tracks title + scan progress
            # scanning progress ends around header_end + 30?
            # Safe check: width > 80?
            if batch_x > 20: 
                self.app.stdscr.addstr(
                    0, batch_x, batch_text, curses.color_pair(5) | curses.A_BOLD
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

        if self.loading:
            # Debounce: Only show loading if it takes longer than 200ms
            if time.time() - self.load_start_time < 0.2:
                self._draw_footer(height, width)
                self.app.stdscr.refresh()
                return

            # Show Loading State
            msg = " Loading directory contents... "
            y = height // 2
            x = max(0, (width - len(msg)) // 2)
            self.app.stdscr.addstr(y, x, msg, curses.color_pair(5) | curses.A_BOLD)

            # Simple Spinner?
            spinner = "|/-\\"
            cycle = int(time.time() * 10) % 4
            self.app.stdscr.addstr(y + 1, width // 2, spinner[cycle], curses.color_pair(3))

            # Draw footer and return
            self._draw_footer(height, width)
            self.app.stdscr.refresh()
            return

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
                # Directory handling
                # Optimization: Check if filename is in self.dirs set/list instead of os.path.isdir?
                # We know sorted_files is [dirs] + [files].
                # But simple check is fast enough if we don't stat.
                # Since we constructed it, we know the first len(self.dirs) are dirs IF we didn't mix them.
                # But safer to just check existence in self.dirs
                if filename in self.dirs:
                    display_filename = get_display_name(filename + "/", name_col_width)
                    # " [ DIR             ] " is 19 chars to match track info width
                    # track info is 19: "[xx aud: xxxxx.x ]"
                    dir_tag = " [ DIR             ]"
                    line = f"{dir_tag} {display_filename}"
                    self.app.stdscr.addstr(
                        i + FILE_LIST_Y_OFFSET,
                        0,
                        line[: width - 1].ljust(width - 1),
                        attr | curses.A_BOLD,
                    )
                    continue

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

        self._draw_footer(height, width)

        self.app.stdscr.refresh()

        # Trigger prioritization for current view
        self._prioritize_visible()

    def _draw_footer(self, height, width):
        # Footer - split into left and right sections
        mouse_status = "APP" if self.app.mouse_enabled else "TERM"
        sort_footer = " Sort: [N]ame, [S]ize, [T]racks, [A]ud Size "

        quit_label = "Back" if self.back_view else "Quit"
        mouse_footer = f"[M] Mouse: {mouse_status}"
        batch_opt = "[B]atch | " if self.batches else ""
        action_footer = f"[ENTER] Open | {batch_opt}[R]escan | [Q/ESC] {quit_label} "

        # Draw left-aligned sort section
        left_text = sort_footer[:width - 1]
        self.app.stdscr.addstr(
            height - 1, 0, left_text, curses.color_pair(3)
        )
        
        # Draw right-aligned action section
        right_text = f" {mouse_footer} | {action_footer}"
        # Ensure we don't exceed screen width and leave room for last column
        x_pos = max(len(left_text) + 2, width - len(right_text) - 1)
        if x_pos > 0 and x_pos < width - 1:
            # Truncate text to fit within bounds
            max_len = width - x_pos - 1
            if max_len > 0:
                display_text = right_text[:max_len]
                self.app.stdscr.addstr(
                    height - 1, x_pos, display_text, curses.color_pair(3)
                )

        self.app.stdscr.refresh()

        # Trigger prioritization for current view
        self._prioritize_visible()

    def handle_input(self, key):
        height, width = self.app.stdscr.getmaxyx()
        sorted_files = self._get_sorted_files()
        list_height = height - 5

        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
            if self.back_view:
                self.app.switch_view(self.back_view)
            else:
                if self.app.mouse_enabled:
                    self.app.toggle_mouse()
                self.app.switch_view(None)
        elif key in (KEY_M_LOWER, KEY_M_UPPER):
            self.app.toggle_mouse()
        elif key in (KEY_R_LOWER, KEY_R_UPPER):
            # Re-scan current directory
            with self.metadata_lock:
                # Reset metadata to unprobed state so UI shows update
                for f in self.files:
                    if f in self.metadata:
                        # Keep the object but set probed=False to avoid flicker
                        # but we want scanning text to appear.
                        self.metadata[f].probed = False
                self.probed_count = 0

            self._submit_scan_tasks(force=True)
            # Also prioritize visible immediately
            self._submit_scan_tasks(force=True)
            # Also prioritize visible immediately
            self._prioritize_visible(force=True)
        elif key in (KEY_B_LOWER, KEY_B_UPPER):
            # Enter Batch Mode
            if self.batches:
                self.app.switch_view(BatchSelectorView(self.app, self.batches, back_view=self))
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



                # List starts at row FILE_LIST_Y_OFFSET.
                row_in_list = my - FILE_LIST_Y_OFFSET
                if 0 <= row_in_list < list_height:
                    target_idx = self.scroll_idx + row_in_list
                    if target_idx < len(sorted_files):
                        # Check for double-click first
                        if bstate & curses.BUTTON1_DOUBLE_CLICKED:
                            # Open file/directory on double click
                            filename = sorted_files[target_idx]
                            file_path = os.path.join(self.path, filename)
                            
                            if os.path.isdir(file_path):
                                # Enter directory
                                self.app.switch_view(FileExplorer(self.app, file_path, back_view=self))
                            else:
                                # Open file in editor
                                media = self.metadata.get(filename)
                                self.app.switch_view(
                                    TrackEditor(self.app, media or file_path, back_view=self)
                                )
                        else:
                            # Single click - just select
                            self.selected_idx = target_idx
                
                # Footer buttons (row is height - 1)
                if my == height - 1:
                    # Build footer to find click zones (now split into left and right sections)
                    mouse_status = "APP" if self.app.mouse_enabled else "TERM"
                    sort_footer = " Sort: [N]ame, [S]ize, [T]racks, [A]ud Size "
                    quit_label = "Back" if self.back_view else "Quit"
                    mouse_footer = f"[M] Mouse: {mouse_status}"
                    batch_opt = "[B]atch | " if self.batches else ""
                    action_footer = f"[ENTER] Open | {batch_opt}[R]escan | [Q/ESC] {quit_label} "
                    right_text = f" {mouse_footer} | {action_footer}"
                    
                    # Use dynamic position detection for all buttons
                    def find_button(text, search_string):
                        idx = search_string.find(text)
                        if idx != -1:
                            return idx, idx + len(text)
                        return None, None
                    
                    # Check left section (sort) buttons - starts at position 0
                    left_start = 0
                    buttons_left = [
                        ("[N]ame", KEY_N_LOWER),
                        ("[S]ize", KEY_S_LOWER),
                        ("[T]racks", KEY_T_LOWER),
                        ("[A]ud Size", KEY_A_LOWER),
                    ]
                    
                    for button_text, key_code in buttons_left:
                        start, end = find_button(button_text, sort_footer)
                        if start is not None:
                            abs_start = left_start + start
                            abs_end = left_start + end
                            if abs_start <= mx <= abs_end:
                                self.handle_input(key_code)
                                return
                    
                    # Check right section buttons
                    right_start = max(len(sort_footer) + 2, width - len(right_text))
                    buttons_right = [
                        ("[M]", KEY_M_LOWER),
                        ("[B]atch", KEY_B_LOWER),
                        ("[ENTER]", KEY_ENTER),
                        ("[R]escan", KEY_R_LOWER),
                        ("[Q/ESC]", KEY_Q_LOWER),
                    ]
                    
                    for button_text, key_code in buttons_right:
                        start, end = find_button(button_text, right_text)
                        if start is not None:
                            abs_start = right_start + start
                            abs_end = right_start + end
                            if abs_start <= mx <= abs_end:
                                self.handle_input(key_code)
                                return

            except:
                pass
        elif key == KEY_ENTER:  # Enter
            if sorted_files:
                filename = sorted_files[self.selected_idx]
                file_path = os.path.join(self.path, filename)
                if os.path.isdir(file_path):
                    # Enter directory
                    self.app.switch_view(FileExplorer(self.app, file_path, back_view=self))
                else:
                    media = self.metadata.get(file_path)

                    self.app.switch_view(TrackEditor(self.app, media or file_path, back_view=self))

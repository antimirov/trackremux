import curses
import os

from ..core.converter import MediaConverter
from ..core.preview import MediaPreview
from ..core.probe import MediaProbe
from .constants import (
    KEY_ENTER,
    KEY_ESC,
    KEY_M_LOWER,
    KEY_M_UPPER,
    KEY_Q_LOWER,
    KEY_Q_UPPER,
    KEY_S_LOWER,
    KEY_S_UPPER,
    KEY_SPACE,
    PREVIEW_DURATION_SECONDS,
    SEEK_STEP_SECONDS,
    TRACK_EDITOR_INFO_HEIGHT,
    TRACK_LIST_Y_OFFSET,
)
from .formatters import format_duration, format_size


class TrackEditor:
    def __init__(self, app, file_path_or_media, back_view=None):
        self.app = app
        if hasattr(file_path_or_media, "path"):  # It's a MediaFile
            self.media_file = file_path_or_media
            self.file_path = file_path_or_media.path
        else:
            self.file_path = file_path_or_media
            self.media_file = MediaProbe.probe(file_path_or_media)
        self.back_view = back_view
        self.selected_idx = 0
        self.scroll_idx = 0
        self.status_message = ""
        self.confirming_exit = False
        self.current_preview_time = 0.0

        # Track if we are viewing an already converted state
        self.output_name = "converted_" + self.media_file.filename
        self._recognize_existing_output()

        # Store initial state for change detection
        self.initial_enabled = [t.enabled for t in self.media_file.tracks]

    def _recognize_existing_output(self):
        if not os.path.exists(self.output_name):
            return

        try:
            existing_media = MediaProbe.probe(self.output_name)
            # Match streams greedily by type and language
            # We assume order is preserved (source stream #1 comes before #2)
            matched_indices = []

            # Reset all tracks to disabled first if an existing file exists
            # so we only enable what's in it. EXCEPT VIDEO which is always enabled.
            for track in self.media_file.tracks:
                if track.codec_type != "video":
                    track.enabled = False

            # For each stream in existing output, find the best match in source
            source_tracks = list(self.media_file.tracks)

            for ex in existing_media.tracks:
                for src in source_tracks:
                    if src.index in matched_indices:
                        continue

                    # Basic matching: type, language, codec
                    if (
                        src.codec_type == ex.codec_type
                        and src.language == ex.language
                        and src.codec_name == ex.codec_name
                    ):

                        src.enabled = True
                        matched_indices.append(src.index)
                        break

            size_str = format_size(os.path.getsize(self.output_name) / 1024 / 1024)
            self.status_message = f" Found existing output ({size_str}). Auto-restored selection. "
        except Exception as e:
            self.status_message = f" Error probing existing output: {e} "

    def _has_changes(self):
        current = [t.enabled for t in self.media_file.tracks]
        return current != self.initial_enabled

    def commit_changes(self):
        """Syncs the initial state with the current state and clears confirmation flags."""
        self.initial_enabled = [t.enabled for t in self.media_file.tracks]
        self.confirming_exit = False

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        # Header
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)  # Clear the line

        # [Q] BACK at the left
        self.app.stdscr.addstr(0, 1, "[Q] BACK", curses.color_pair(5))

        # [X] at the right
        if width > 10:
            self.app.stdscr.addstr(0, width - 4, "[X]", curses.color_pair(5))

        label = " Editing: "
        fname = f"{self.media_file.filename} "
        full_header_len = len(label) + len(fname)

        if full_header_len < width - 20:
            start_x = (width - full_header_len) // 2
            self.app.stdscr.addstr(0, start_x, label, curses.color_pair(1) | curses.A_BOLD)
            self.app.stdscr.addstr(0, start_x + len(label), fname, curses.A_DIM)

        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # File Info & Output Info
        output_name = "converted_" + self.media_file.filename
        existing_exists = os.path.exists(output_name)

        est_size_mb = MediaConverter.estimate_output_size(self.media_file) / 1024 / 1024
        target_info = f" Output: {output_name} | Est. file size: {format_size(est_size_mb)}"

        if existing_exists:
            actual_size_mb = os.path.getsize(output_name) / 1024 / 1024
            target_info += f" (Actual: {format_size(actual_size_mb)})"

        dur_str = format_duration(self.media_file.duration)
        size_str = format_size(self.media_file.size_bytes / 1024 / 1024)
        info = f" Duration: {dur_str} | Size: {size_str} "
        self.app.stdscr.addstr(1, 0, info.center(width), curses.color_pair(2))

        self.app.stdscr.addstr(
            2, 0, target_info.center(width), curses.color_pair(3) | curses.A_BOLD
        )

        # Status Message
        if self.status_message:
            self.app.stdscr.addstr(3, 0, self.status_message.center(width), curses.color_pair(3))

        # Tracks List
        list_height = height - TRACK_EDITOR_INFO_HEIGHT
        tracks = self.media_file.tracks

        if self.selected_idx >= len(tracks):
            self.selected_idx = max(0, len(tracks) - 1)

        if self.selected_idx < self.scroll_idx:
            self.scroll_idx = self.selected_idx
        elif self.selected_idx >= self.scroll_idx + list_height:
            self.scroll_idx = self.selected_idx - list_height + 1

        visible_tracks = tracks[self.scroll_idx : self.scroll_idx + list_height]

        for i, track in enumerate(visible_tracks):
            idx = i + self.scroll_idx
            attr = curses.A_NORMAL

            check = "[X]" if track.enabled else "[ ]"
            prefix = "> " if idx == self.selected_idx else "  "

            # Per-track size estimation
            track_size_str = ""
            if track.bit_rate:
                size_mb = (track.bit_rate * self.media_file.duration) / 8 / 1024 / 1024
                track_size_str = f"[{format_size(size_mb, precision=1)}]"

            line = f"{prefix}{check} Stream #{track.index}: {track.codec_type.upper():<10} {track_size_str:>11} | {track.display_info}"

            if idx == self.selected_idx:
                attr = curses.color_pair(5)
            elif track.codec_type == "video":
                attr = curses.color_pair(1)  # Highlight video tracks in Cyan
            elif not track.enabled:
                attr = curses.A_DIM  # Dim disabled tracks

            self.app.stdscr.addstr(i + TRACK_LIST_Y_OFFSET, 0, line[:width].ljust(width), attr)

        # Footer
        mouse_status = "APP SELECT" if self.app.mouse_enabled else "TERM SELECT"
        footer = f" [SPACE] Toggle | [ENTER] Play | [L/R] Seek | [S] Start | [M] Mouse: {mouse_status} | [ESC] Back "
        self.app.stdscr.addstr(
            height - 1, 0, footer.center(width)[: width - 1], curses.color_pair(3)
        )

        # Confirmation Overlay
        if self.confirming_exit:
            mw = 50
            mh = 7
            my = (height - mh) // 2
            mx = (width - mw) // 2
            for r in range(mh):
                self.app.stdscr.addstr(my + r, mx, " " * mw, curses.color_pair(3))

            msg = " UNSAVED CHANGES DETECTED "
            self.app.stdscr.addstr(
                my + 1, mx + (mw - len(msg)) // 2, msg, curses.color_pair(3) | curses.A_BOLD
            )

            opts = " [S]ave & Start   [Y] Save & Back   [N] Discard "
            self.app.stdscr.addstr(my + 4, mx + (mw - len(opts)) // 2, opts, curses.color_pair(5))

        self.app.stdscr.refresh()

    def handle_input(self, key):
        height, width = self.app.stdscr.getmaxyx()

        if self.confirming_exit:
            if key in (ord("s"), ord("S")):
                # Start conversion immediately
                self.commit_changes()
                from .progress import ProgressView

                self.app.switch_view(ProgressView(self.app, self.media_file, self))
            elif key in (ord("y"), ord("Y"), KEY_ENTER):
                # Just save and go back
                self.commit_changes()
                self.app.switch_view(self.back_view)
            elif key in (ord("n"), ord("N")):
                # Restore initial state and go back
                for i, enabled in enumerate(self.initial_enabled):
                    self.media_file.tracks[i].enabled = enabled
                self.confirming_exit = False
                self.app.switch_view(self.back_view)
            elif key in (ord("c"), ord("C"), KEY_ESC):
                self.confirming_exit = False

            # Handle mouse in confirmation dialog
            if key == curses.KEY_MOUSE and self.app.mouse_enabled:
                try:
                    _, mx, my, _, _ = curses.getmouse()
                    mw, mh = 50, 7
                    y_box = (height - mh) // 2
                    x_box = (width - mw) // 2

                    dialog_opts = " [S]ave & Start   [Y] Save & Back   [N] Discard "
                    if my == y_box + 4:  # Options row
                        opt_start = x_box + (mw - len(dialog_opts)) // 2
                        rel_x = mx - opt_start

                        if 1 <= rel_x <= 15:  # [S]ave & Start
                            self.status_message = " Commencing conversion... "
                            self.commit_changes()
                            from .progress import ProgressView

                            self.app.switch_view(ProgressView(self.app, self.media_file, self))
                        elif 18 <= rel_x <= 32:  # [Y] Save & Back
                            self.status_message = " Saving selection... "
                            self.commit_changes()
                            self.app.switch_view(self.back_view)
                        elif 35 <= rel_x <= 45:  # [N] Discard
                            self.status_message = " Discarding changes... "
                            for i, enabled in enumerate(self.initial_enabled):
                                self.media_file.tracks[i].enabled = enabled
                            self.confirming_exit = False
                            self.app.switch_view(self.back_view)
                except Exception:
                    pass
            return

        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC, curses.KEY_LEFT):
            if self._has_changes():
                self.confirming_exit = True
            else:
                if self.app.mouse_enabled:
                    # Logic should be in toggle_mouse but we want it off on exit
                    pass
                if self.back_view:
                    self.app.switch_view(self.back_view)
                else:
                    self.app.switch_view(None)
        elif key in (KEY_M_LOWER, KEY_M_UPPER):
            self.app.toggle_mouse()
        elif key == curses.KEY_MOUSE:
            if not self.app.mouse_enabled:
                return
            try:
                _, mx, my, _, _ = curses.getmouse()

                # Header [Q] BACK button or [X] button
                is_back = my == 0 and 1 <= mx <= 8
                is_x = my == 0 and mx >= width - 4

                if is_back or is_x:
                    if self._has_changes():
                        self.confirming_exit = True
                    elif self.back_view:
                        self.app.switch_view(self.back_view)
                    else:
                        self.app.switch_view(None)
                    return

                row_in_list = my - TRACK_LIST_Y_OFFSET
                list_height = height - TRACK_EDITOR_INFO_HEIGHT
                if 0 <= row_in_list < list_height:
                    target_idx = self.scroll_idx + row_in_list
                    if target_idx < len(self.media_file.tracks):
                        # Detect click on [X] or [ ] checkbox
                        # Line format: "> [X] Stream..." (2 chars prefix + 3 chars check)
                        # columns are 2, 3, 4 (0-indexed)
                        if 2 <= mx <= 4:
                            track = self.media_file.tracks[target_idx]
                            if track.codec_type != "video":
                                track.enabled = not track.enabled
                            else:
                                self.status_message = " Video tracks cannot be disabled. "
                        else:
                            self.selected_idx = target_idx
            except:
                pass
        elif key == curses.KEY_UP:
            MediaPreview.stop()
            self.status_message = ""
            if self.selected_idx > 0:
                self.selected_idx -= 1
        elif key == curses.KEY_DOWN:
            MediaPreview.stop()
            self.status_message = ""
            if self.selected_idx < len(self.media_file.tracks) - 1:
                self.selected_idx += 1
        elif key == curses.KEY_PPAGE:  # Page Up
            self.selected_idx = max(0, self.selected_idx - (height - TRACK_EDITOR_INFO_HEIGHT))
        elif key == curses.KEY_NPAGE:  # Page Down
            self.selected_idx = min(
                len(self.media_file.tracks) - 1,
                self.selected_idx + (height - TRACK_EDITOR_INFO_HEIGHT),
            )
        elif key == curses.KEY_HOME:
            self.selected_idx = 0
        elif key == curses.KEY_END:
            self.selected_idx = len(self.media_file.tracks) - 1
        elif key == KEY_SPACE:  # Space
            track = self.media_file.tracks[self.selected_idx]
            if track.codec_type != "video":
                track.enabled = not track.enabled
            else:
                self.status_message = " Video tracks cannot be disabled. "
        elif key == KEY_ENTER:  # Enter
            self.current_preview_time = 0.0  # Reset seek on new track play
            self._play_current_track()
        # Seeking logic removed for consistency with 'Left to go back'
        # unless we want to keep it? User asked for Left to exit.
        elif key == curses.KEY_RIGHT:
            if self.current_preview_time + SEEK_STEP_SECONDS < self.media_file.duration:
                self.current_preview_time += SEEK_STEP_SECONDS
            self._play_current_track()
        elif key in (KEY_S_LOWER, KEY_S_UPPER):
            self.commit_changes()
            from .progress import ProgressView

            self.app.switch_view(ProgressView(self.app, self.media_file, self))

    def _play_current_track(self):
        height, width = self.app.stdscr.getmaxyx()
        track = self.media_file.tracks[self.selected_idx]
        if track.codec_type != "audio":
            return

        # Visual feedback
        time_str = (
            f"{int(self.current_preview_time // 60):02d}:{int(self.current_preview_time % 60):02d}"
        )
        self.status_message = f" Extracting snippet for track #{track.index} at {time_str}... "
        self.draw()  # Force redraw to show status

        type_idx = 0
        for t in self.media_file.tracks:
            if t == track:
                break
            if t.codec_type == track.codec_type:
                type_idx += 1

        wav_path = MediaPreview.extract_snippet(
            self.file_path, "audio", type_idx, start_time=self.current_preview_time
        )
        if wav_path:
            MediaPreview.play_snippet(wav_path)
            self.status_message = f" Playing Track #{track.index} at {time_str} ({PREVIEW_DURATION_SECONDS}s snippet) "
        else:
            self.status_message = " Extraction failed! "

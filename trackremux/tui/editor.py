import curses
import os

from ..core.converter import MediaConverter
from ..core.languages import LANGUAGE_MAP
from ..core.preview import MediaPreview
from ..core.probe import MediaProbe
from .constants import (
    APP_TIMEOUT_MS,
    KEY_ENTER,
    KEY_ESC,
    KEY_L_LOWER,
    KEY_L_UPPER,
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
        base_name = os.path.splitext(self.media_file.filename)[0]
        self.output_name = f"converted_{base_name}.mkv"
        self._scan_external_tracks()
        self._recognize_existing_output()

        # Store initial state for change detection
        # We store tuples of (index, enabled) to detect both enabling changes AND reordering
        self.initial_state = [(t.index, t.enabled) for t in self.media_file.tracks]

    def _guess_language(self, path):
        """Attempts to guess language from filename parts or directory names."""
        # Normalize path separators
        path = path.lower().replace("\\", "/")

        # Split into components (dirs + filename)
        # We process the whole path from the scan root down
        parts = path.replace("-", ".").replace("_", ".").split(".")

        # Also split by slash to get directory names as separate tokens
        # e.g. "Subs/Ukr/file.srt" -> "Subs", "Ukr", "file", "srt"
        path_tokens = []
        for p in path.split("/"):
            path_tokens.extend(p.replace("-", ".").replace("_", ".").split("."))

        # Merge parts and path_tokens
        all_tokens = set(parts + path_tokens)

        # Merge parts and path_tokens
        all_tokens = set(parts + path_tokens)

        # Prioritize tokens that perform exact matches
        for token in all_tokens:
            if token in LANGUAGE_MAP:
                return LANGUAGE_MAP[token]
        return None

    def _get_short_source_name(self, external_path):
        """
        Returns a shortened display name for the external file.
        Removes common prefix with main file and truncates if necessary.
        """
        if not external_path:
            return ""

        fname = os.path.basename(external_path)
        main_base = os.path.splitext(self.media_file.filename)[0]

        # Check if external file starts with main file's name (case-insensitive)
        if fname.lower().startswith(main_base.lower()):
            # Strip the prefix
            shortened = fname[len(main_base) :]
            # If it starts with a separator, strip that too
            if shortened and shortened[0] in (".", "_", "-"):
                shortened = shortened[1:]

            # If we stripped it down to just extension or empty, keep original or ensure visibility
            if not shortened or shortened.startswith("."):
                # This might happen if file is "Movie.mkv" and ext is "Movie.srt" -> "srt"
                # Better to show the extension clearly?
                pass

            display = shortened
        else:
            display = fname

        # Truncate if still too long
        max_len = 30
        if len(display) > max_len:
            display = display[: max_len - 3] + "..."

        return display

    def _scan_external_tracks(self):
        """Scans the directory RECURSIVELY for sibling audio and subtitle files and adds them."""
        # Common external extensions
        audio_exts = (".ac3", ".mka", ".dts", ".eac3", ".wav", ".flac", ".mp3", ".aac")
        sub_exts = (".srt", ".ass", ".sub", ".txt", ".vtt")

        directory = os.path.dirname(self.file_path)
        base_name = os.path.splitext(self.media_file.filename)[0]

        try:
            # Walk top-down
            # Limit depth? Walk is depth-first but we can limit logic.
            # Actually standard os.walk visits everything.
            # We probably only want 1 or 2 levels deep to avoid scanning entire volumes if user opened root.
            # Let's assume user opens a movie folder which contains the structure.
            # Safety: limit complexity by counting.

            scanned_files = []

            # Use os.walk with depth limit logic manually
            root_depth = directory.rstrip(os.sep).count(os.sep)

            for root, dirs, files in os.walk(directory):
                # Calculate current depth
                current_depth = root.rstrip(os.sep).count(os.sep)
                if current_depth - root_depth > 2:  # Limit to 2 levels deep
                    dirs[:] = []  # Stop descending
                    continue

                for f in files:
                    full = os.path.join(root, f)
                    if full == self.file_path:
                        continue
                    if f.startswith("converted_") or f.startswith("temp_"):
                        continue

                    scanned_files.append(full)

            # Sort files to ensure stable order
            for full in sorted(scanned_files):
                f = os.path.basename(full)
                is_audio = f.lower().endswith(audio_exts)
                is_sub = f.lower().endswith(sub_exts)

                if is_audio or is_sub:
                    try:
                        # Probe it
                        ext_media = MediaProbe.probe(full)

                        # Determine language from RELATIVE path (to include folder names)
                        rel_path = os.path.relpath(full, directory)
                        guessed_lang = self._guess_language(rel_path)

                        # Add its tracks
                        for t in ext_media.tracks:
                            # Only add relevant tracks (audio from aduio files, subs from sub files)
                            if (is_audio and t.codec_type == "audio") or (
                                is_sub and t.codec_type == "subtitle"
                            ):
                                t.source_path = full
                                t.enabled = False  # Default to disabled for external tracks

                                # Apply guessed language if track doesn't have one or if we want to override?
                                # Usually external files don't have metadata lang, so filename is king.
                                if guessed_lang:
                                    t.language = guessed_lang

                                self.media_file.tracks.append(t)
                    except:
                        pass
        except:
            pass

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
        current = [(t.index, t.enabled) for t in self.media_file.tracks]
        return current != self.initial_state

    def commit_changes(self):
        """Syncs the initial state with the current state and clears confirmation flags."""
        self.initial_state = [(t.index, t.enabled) for t in self.media_file.tracks]
        self.confirming_exit = False

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        # Header
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)  # Clear the line

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
        base_name = os.path.splitext(self.media_file.filename)[0]
        output_name = f"converted_{base_name}.mkv"
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

            source_tag = ""
            if track.source_path:
                short_name = self._get_short_source_name(track.source_path)
                source_tag = f" [EXT: {short_name}]"

            # Truncate source tag if too long?
            # Max width logic?
            # For now, let it be.

            line = f"{prefix}{check} Stream #{track.index}: {track.codec_type.upper():<10} {track_size_str:>11}{source_tag} | {track.display_info}"

            if idx == self.selected_idx:
                attr = curses.color_pair(5)
            elif track.codec_type == "video":
                attr = curses.color_pair(1)  # Highlight video tracks in Cyan
            elif not track.enabled:
                attr = curses.A_DIM  # Dim disabled tracks

            self.app.stdscr.addstr(i + TRACK_LIST_Y_OFFSET, 0, line[:width].ljust(width), attr)

        # Footer
        mouse_status = "APP SELECT" if self.app.mouse_enabled else "TERM SELECT"
        footer = f" [SPACE] Toggle | [ENTER] Play | [L] Lang | [Shift+↑/↓] Reorder | [←/→] Seek | [S] Start | [M] Mouse: {mouse_status} | [Q/ESC] Back "
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
                # Reconstruct track list based on initial state
                restored_tracks = []
                # Map current tracks by index for easy lookup
                track_map = {t.index: t for t in self.media_file.tracks}

                for idx, enabled in self.initial_state:
                    t = track_map[idx]
                    t.enabled = enabled
                    restored_tracks.append(t)

                self.media_file.tracks = restored_tracks
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
                            # Restore logic duplicated from key handler
                            restored_tracks = []
                            track_map = {t.index: t for t in self.media_file.tracks}
                            for idx, enabled in self.initial_state:
                                t = track_map[idx]
                                t.enabled = enabled
                                restored_tracks.append(t)
                            self.media_file.tracks = restored_tracks

                            self.confirming_exit = False
                            self.app.switch_view(self.back_view)
                except Exception:
                    pass
            return

        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
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

                # Header [X] button
                is_back = False  # Removed
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
        elif key in (KEY_L_LOWER, KEY_L_UPPER):
            self._edit_language()
        elif key == curses.KEY_SR:  # Shift+Up - Move Up
            if self.selected_idx > 0:
                tracks = self.media_file.tracks
                tracks[self.selected_idx], tracks[self.selected_idx - 1] = (
                    tracks[self.selected_idx - 1],
                    tracks[self.selected_idx],
                )
                self.selected_idx -= 1
        elif key == curses.KEY_SF:  # Shift+Down - Move Down
            tracks = self.media_file.tracks
            if self.selected_idx < len(tracks) - 1:
                tracks[self.selected_idx], tracks[self.selected_idx + 1] = (
                    tracks[self.selected_idx + 1],
                    tracks[self.selected_idx],
                )
                self.selected_idx += 1

    def _edit_language(self):
        """Opens a simple prompt to edit the language of the selected track."""
        track = self.media_file.tracks[self.selected_idx]
        if track.codec_type == "video":
            self.status_message = " Cannot edit language for video tracks. "
            return

        height, width = self.app.stdscr.getmaxyx()

        # Simple input loop
        curses.echo()
        curses.curs_set(1)
        self.app.stdscr.timeout(-1)  # Blocking input
        curses.flushinp()  # Clear buffer of any previous keys

        prompt = " Enter 3-letter language code (e.g. eng, ukr): "
        self.app.stdscr.addstr(
            height - 2, 0, prompt.ljust(width), curses.color_pair(3) | curses.A_BOLD
        )
        self.app.stdscr.refresh()

        try:
            # Get string at cursor
            user_input = self.app.stdscr.getstr(height - 2, len(prompt), 3).decode("utf-8")
        except:
            user_input = ""

        curses.noecho()
        curses.curs_set(0)
        self.app.stdscr.timeout(APP_TIMEOUT_MS)  # Restore application timeout

        if user_input and len(user_input.strip()) == 3:
            track.language = user_input.strip().lower()
            self.status_message = f" Language set to '{track.language}' for track #{track.index} "
        else:
            self.status_message = " Invalid language code or cancelled. "

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
            if t == track:
                break
            # We must only count 'sibling' tracks of same type WITHIN THE SAME SOURCE FILE
            # IF using relative index. ffmpeg -map 0:a:0 etc.
            # BUT wait, MediaPreview uses ffplay or ffmpeg -ss ...
            # Implementation of extract_snippet:
            # cmd = ["ffmpeg", "-ss", ..., "-i", source_path, "-map", f"0:{codec_type}:{track_index}"]
            # So we need the index relative to that file's specific codec stream list? or absolute?
            # MediaProbe returns absolute index "index".
            # Let's check MediaPreview.
            # If we pass absolute stream index "0:2", we don't need type_idx logic?
            # Current MediaPreview implementation takes "track_index" which is 0-based index of THAT TYPE.

            # So if track.source_path is set, we need its index relative to THAT file.
            # track.index from MediaProbe is absolute index in that file.
            # check MediaPreview usage...

            if t.source_path == track.source_path and t.codec_type == track.codec_type:
                type_idx += 1

        wav_path = MediaPreview.extract_snippet(
            track.source_path or self.file_path,
            "audio",
            type_idx,
            start_time=self.current_preview_time,
        )
        if wav_path:
            MediaPreview.play_snippet(wav_path)
            self.status_message = f" Playing Track #{track.index} at {time_str} ({PREVIEW_DURATION_SECONDS}s snippet) "
        else:
            self.status_message = " Extraction failed! "

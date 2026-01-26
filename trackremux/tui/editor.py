import curses
import os

from ..core.converter import MediaConverter
from ..core.languages import LANGUAGE_MAP
from ..core.preview import MediaPreview
from ..core.probe import MediaProbe
from .batch_progress import BatchProgressView
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
from .progress import ProgressView


class TrackEditor:
    def __init__(self, app, file_path_or_media, back_view=None, batch_group=None):
        self.app = app
        if hasattr(file_path_or_media, "path"):  # It's a MediaFile
            self.media_file = file_path_or_media
            self.file_path = file_path_or_media.path
        else:
            self.file_path = file_path_or_media
            self.media_file = MediaProbe.probe(file_path_or_media)
        self.back_view = back_view
        self.batch_group = batch_group
        self.selected_idx = 0
        self.scroll_idx = 0
        self.status_message = ""
        self.confirming_exit = False
        self.status_message = ""
        self.confirming_exit = False
        self.current_preview_time = 0.0
        self.previewing_subs = False
        self.preview_lines = []
        self.preview_scroll = 0

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

        return display

    def _get_short_source_name(self, external_path):
        """
        Returns a shortened display name for the external file.
        Uses longest common prefix to strip redundant info.
        """
        if not external_path:
            return ""

        fname = os.path.basename(external_path)
        base = os.path.splitext(self.media_file.filename)[0]

        # Use common prefix
        # Case insensitive check
        s1 = fname.lower()
        s2 = base.lower()
        
        # Manually find length of common prefix
        length = 0
        min_len = min(len(s1), len(s2))
        while length < min_len and s1[length] == s2[length]:
            length += 1
            
        if length > 5: # Only strip if significant overlap
             shortened = fname[length:]
             # If starts with separator, strip it
             if shortened and shortened[0] in (".", "_", "-"):
                 shortened = shortened[1:]
             
             # If result is empty or just extension, keep it descriptive?
             # e.g. "Movie.srt" -> "srt". Prefer "srt" or ".srt"
             if not shortened:
                 shortened = os.path.splitext(fname)[1]
             
             return shortened
        
        # Fallback to standard truncation if no common prefix
        max_len = 30
        if len(fname) > max_len:
            return fname[: max_len - 3] + "..."
        return fname

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
            # Standard os.walk visits everything.
            # We assume user opens a movie folder which contains the structure.
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
                    base = base_name.lower()
                    fname_lower = f.lower()

                    # Mutual Prefix Matching:
                    # 1. Ext starts with Main (Standard: Movie.en.srt matches Movie.mkv)
                    # 2. Main starts with Ext (Tagged: Movie[EtHD].mkv matches Movie.srt)

                    matched = False

                    # Case 1: Ext starts with Main
                    if fname_lower.startswith(base):
                        rest = fname_lower[len(base):]
                        if not rest or rest[0] in (".", "_", "-", " ", "[", "("):
                            matched = True

                    # Case 2: Main starts with Ext (only if Ext is reasonably long to avoid "The.srt" matching "The Matrix.mkv")
                    # We must compare stems, not full filename with extension
                    stem_lower = os.path.splitext(f)[0].lower()
                    
                    if not matched and base.startswith(stem_lower):
                        # Ensure Ext is not too short (e.g. at least 3 chars)
                        if len(stem_lower) >= 3:
                            rest = base[len(stem_lower):]
                            if not rest or rest[0] in (".", "_", "-", " ", "[", "("):
                                matched = True

                    if not matched:
                        continue

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



        if self.batch_group:
            label = " BATCH EDITING: "
            fname = f"{self.batch_group.name} ({self.batch_group.count} files) "
        else:
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

        # Subtitle Preview Overlay
        if self.previewing_subs and self.preview_lines:
            mw = min(80, width - 4)
            mh = min(30, height - 4)
            my = (height - mh) // 2
            mx = (width - mw) // 2
            
            # Draw box
            for r in range(mh):
                self.app.stdscr.addstr(my + r, mx, " " * mw, curses.color_pair(3))
            
            # Header
            title = " Subtitle Preview (First 2000 lines) "
            self.app.stdscr.addstr(my, mx + (mw - len(title))//2, title, curses.color_pair(3) | curses.A_BOLD)
            
            # Content
            content_h = mh - 2
            for i in range(content_h):
                line_idx = self.preview_scroll + i
                if line_idx < len(self.preview_lines):
                    line = self.preview_lines[line_idx]
                    # truncation
                    if len(line) > mw - 2:
                        line = line[:mw-5] + "..."
                    self.app.stdscr.addstr(my + 1 + i, mx + 2, line, curses.color_pair(3))
            
            # Footer
            footer = " [UP/DOWN] Scroll | [ESC/ENTER] Close "
            self.app.stdscr.addstr(my + mh - 1, mx + (mw - len(footer))//2, footer, curses.color_pair(3))

    def handle_input(self, key):
        height, width = self.app.stdscr.getmaxyx()

        # Subtitle Preview Handling
        if self.previewing_subs:
            if key in (KEY_ESC, KEY_ENTER, ord("q"), ord("Q")):
                self.previewing_subs = False
                self.preview_lines = []
            elif key == curses.KEY_UP:
                if self.preview_scroll > 0:
                    self.preview_scroll -= 1
            elif key == curses.KEY_DOWN:
                if self.preview_scroll < len(self.preview_lines) - 1:
                     self.preview_scroll += 1
            elif key == curses.KEY_PPAGE:
                self.preview_scroll = max(0, self.preview_scroll - 10)
            elif key == curses.KEY_NPAGE:
                self.preview_scroll = max(0, min(len(self.preview_lines) - 1, self.preview_scroll + 10))
            return

        if self.confirming_exit:
            if key in (ord("s"), ord("S")):
                # Start conversion immediately
                MediaPreview.stop()
                self.commit_changes()
                if self.batch_group:
                    self.app.switch_view(
                        BatchProgressView(self.app, self.batch_group, self.media_file, self)
                    )
                else:
                    self.app.switch_view(ProgressView(self.app, self.media_file, self))
            elif key in (ord("y"), ord("Y"), KEY_ENTER):
                # Just save and go back
                MediaPreview.stop()
                self.commit_changes()
                self.app.switch_view(self.back_view)
            elif key in (ord("n"), ord("N")):
                # Restore initial state and go back
                MediaPreview.stop()
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
                            MediaPreview.stop()
                            self.commit_changes()
                            self.commit_changes()
                            if self.batch_group:
                                self.app.switch_view(
                                    BatchProgressView(
                                        self.app, self.batch_group, self.media_file, self
                                    )
                                )
                            else:
                                self.app.switch_view(ProgressView(self.app, self.media_file, self))
                        elif 18 <= rel_x <= 32:  # [Y] Save & Back
                            self.status_message = " Saving selection... "
                            MediaPreview.stop()
                            self.commit_changes()
                            self.app.switch_view(self.back_view)
                        elif 35 <= rel_x <= 45:  # [N] Discard
                            self.status_message = " Discarding changes... "
                            MediaPreview.stop()
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
                MediaPreview.stop()
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
                
                # Footer buttons (row is height - 1)
                if my == height - 1:
                    # Build footer to find click zones
                    mouse_status = "APP SELECT" if self.app.mouse_enabled else "TERM SELECT"
                    footer = f" [SPACE] Toggle | [ENTER] Play | [L] Lang | [Shift+↑/↓] Reorder | [←/→] Seek | [S] Start | [M] Mouse: {mouse_status} | [Q/ESC] Back "
                    
                    # Center the footer
                    footer_start = (width - len(footer)) // 2
                    rel_x = mx - footer_start
                    
                    # Use dynamic position detection for all buttons
                    def find_button(text):
                        idx = footer.find(text)
                        if idx != -1:
                            return idx, idx + len(text)
                        return None, None
                    
                    # Check each button (use position-based detection for combined [←/→])
                    # Find the [←/→] text position
                    seek_start = footer.find("[←/→]")
                    if seek_start != -1:
                        # Left arrow is at seek_start to seek_start+2
                        # Right arrow is at seek_start+2 to seek_start+4
                        if seek_start <= rel_x <= seek_start + 1:
                            self.handle_input(curses.KEY_LEFT)
                            return
                        elif seek_start + 2 <= rel_x <= seek_start + 4:
                            self.handle_input(curses.KEY_RIGHT)
                            return
                    
                    # Check for Shift+↑/↓ reorder buttons
                    shift_arrows = footer.find("[Shift+↑/↓]")
                    if shift_arrows != -1:
                        # Up arrow around position shift_arrows+7
                        # Down arrow around position shift_arrows+9
                        if shift_arrows + 7 <= rel_x <= shift_arrows + 8:
                            self.handle_input(curses.KEY_SR)  # Shift+Up
                            return
                        elif shift_arrows + 9 <= rel_x <= shift_arrows + 10:
                            self.handle_input(curses.KEY_SF)  # Shift+Down
                            return
                    
                    # Check other buttons
                    buttons = [
                        ("[SPACE]", KEY_SPACE),
                        ("[ENTER]", KEY_ENTER),
                        ("[L]", KEY_L_LOWER),
                        ("[S]", KEY_S_LOWER),
                        ("[M]", KEY_M_LOWER),
                        ("[Q/ESC]", KEY_Q_LOWER),
                    ]
                    
                    for button_text, key_code in buttons:
                        start, end = find_button(button_text)
                        if start is not None and start <= rel_x <= end:
                            self.handle_input(key_code)
                            return
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
        elif key == curses.KEY_LEFT:
            if self.current_preview_time - SEEK_STEP_SECONDS >= 0:
                self.current_preview_time -= SEEK_STEP_SECONDS
            else:
                self.current_preview_time = 0
            self._play_current_track()
        elif key == curses.KEY_RIGHT:
            if self.current_preview_time + SEEK_STEP_SECONDS < self.media_file.duration:
                self.current_preview_time += SEEK_STEP_SECONDS
            self._play_current_track()
        elif key in (KEY_S_LOWER, KEY_S_UPPER):
            self.commit_changes()
            self.commit_changes()
            if self.batch_group:
                self.app.switch_view(
                    BatchProgressView(self.app, self.batch_group, self.media_file, self)
                )
            else:
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



    def _show_subtitle_preview(self, path):
        """Reads the first few lines of a subtitle file and enables preview mode."""
        try:
            self.preview_lines = []
            with open(path, "rb") as f:
                # Read binary to check for null bytes
                content = f.read(4096)
                if b"\0" in content:
                    self.status_message = " Cannot preview binary file. "
                    return
                
                # Decode
                text = ""
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        text = content.decode("latin-1")
                    except:
                        pass
                
                if not text:
                    self.status_message = " Empty or unreadable file. "
                    return

                self.preview_lines = text.splitlines()[:2000] # Limit to 2000 lines
                self.previewing_subs = True
                self.preview_scroll = 0
                self.status_message = f" Previewing {os.path.basename(path)} "

        except Exception as e:
            self.status_message = f" Error reading file: {e} "

    def _play_current_track(self):
        height, width = self.app.stdscr.getmaxyx()
        track = self.media_file.tracks[self.selected_idx]
        
        # New: Subtitle Preview
        if track.codec_type == "subtitle":
            if track.source_path:
                self._show_subtitle_preview(track.source_path)
            else:
                 # Internal subtitle? Can't easy preview without extraction.
                 # Internal subtitle preview not supported strictly yet.
                 self.status_message = " Preview not supported for internal subtitles yet. "
            return

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
            # MediaPreview.extract_snippet uses ffmpeg -map 0:{codec}:{index}.
            # We must calculate the relative index of this track among all tracks 
            # of the same type within the same source file.

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

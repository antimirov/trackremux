import curses
import os

from ..core.converter import MediaConverter
from ..core.languages import LANGUAGE_MAP
from ..core.models import OutputMode
from ..core.preview import MediaPreview
from ..core.probe import MediaProbe
from .batch_progress import BatchProgressView
from .constants import (
    APP_TIMEOUT_MS,
    KEY_C_LOWER,
    KEY_C_UPPER,
    KEY_ENTER,
    KEY_ESC,
    KEY_L_LOWER,
    KEY_L_UPPER,
    KEY_M_LOWER,
    KEY_M_UPPER,
    KEY_O_LOWER,
    KEY_O_UPPER,
    KEY_P_LOWER,
    KEY_P_UPPER,
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
        self.current_preview_time = 0.0
        self.previewing_subs = False
        self.preview_lines = []
        self.preview_scroll = 0

        # UI state flags for v0.7.0 overlays
        self.showing_output_dialog = False   # Output mode selection [O/M/L]
        self.showing_overwrite_warning = False # Collision prompt
        self.showing_profile_overlay = False  # [P] Save profile overlay
        # Editable fields for profile overlay
        self._profile_keep = ", ".join(self.app.config.keep_langs)
        self._profile_discard = ", ".join(self.app.config.discard_langs)
        self._profile_prefer_ac3 = self.app.config.prefer_ac3_over_dts
        self._profile_field = 0  # 0=keep, 1=discard, 2=ac3 toggle
        self._profile_cursor = len(self._profile_keep)
        self._profile_editing = False  # True when actively editing a text field
        self._profile_edit_backup = ""  # Backup for ESC discard
        self._profile_save_msg = ""  # Shown inside the overlay after saving

        # Track if we are viewing an already converted state
        base_name = os.path.splitext(self.media_file.filename)[0]
        source_dir = os.path.dirname(os.path.abspath(self.file_path))
        dir_name = os.path.basename(os.path.normpath(source_dir))
        
        # Single-file output paths
        local_out = os.path.join(os.getcwd(), f"converted_{base_name}.mkv")
        remote_out = os.path.join(source_dir, f"converted_{base_name}.mkv")
        # Batch output paths
        batch_local = os.path.join(os.getcwd(), f"converted_{dir_name}", f"{base_name}.mkv")
        batch_remote = os.path.join(
            os.path.dirname(os.path.normpath(source_dir)),
            f"converted_{dir_name}",
            f"{base_name}.mkv",
        )
        
        self.output_name = local_out
        if os.path.exists(local_out):
            self.output_name = local_out
        elif os.path.exists(remote_out):
            self.output_name = remote_out
        elif os.path.exists(batch_local):
            self.output_name = batch_local
        elif os.path.exists(batch_remote):
            self.output_name = batch_remote
            
        self._scan_external_tracks()
        self._recognize_existing_output()

        # Check profile match for [A] hint (computed once on open)
        self._profile_candidates = self.app.config.matches(self.media_file)
        self._profile_applied = False  # True once [A] was used this file

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
                # 1. Deterministic match using custom metadata tag
                # Make tags lookup case-insensitive as MKV/ffmpeg may uppercase it
                lower_tags = {k.lower(): v for k, v in ex.tags.items()}
                if "trackremux_id" in lower_tags:
                    try:
                        src_idx = int(lower_tags["trackremux_id"])
                        for src in source_tracks:
                            if src.index == src_idx:
                                src.enabled = True
                                matched_indices.append(src.index)
                                # Detect if this track was transcoded from DTS to AC3 to auto-enable the UI toggle
                                if src.codec_type == "audio" and src.codec_name.lower() in MediaConverter.DTS_CODECS and ex.codec_name.lower() == "ac3":
                                    self.app.settings.convert_audio = True
                                break
                        continue  # Move to next output track
                    except ValueError:
                        pass
                
                # 2. Fallback heuristic match for older converted files without the tag
                for src in source_tracks:
                    if src.index in matched_indices:
                        continue

                    # Determine if codecs match (allowing for DTS->AC3 converted audio)
                    codec_match = (src.codec_name == ex.codec_name)
                    if not codec_match and src.codec_type == "audio" and ex.codec_type == "audio":
                        if src.codec_name.lower() in MediaConverter.DTS_CODECS and ex.codec_name.lower() == "ac3":
                            codec_match = True

                    # Basic matching: type, language, codec
                    if (
                        src.codec_type == ex.codec_type
                        and src.language == ex.language
                        and codec_match
                    ):
                        # For audio, channel counts help disambiguate identical-language tracks
                        if src.codec_type == "audio" and src.channels and ex.channels:
                            if src.channels != ex.channels:
                                continue

                        src.enabled = True
                        matched_indices.append(src.index)
                        
                        # Detect if this track was transcoded from DTS to AC3 to auto-enable the UI toggle
                        if src.codec_type == "audio" and src.codec_name.lower() in MediaConverter.DTS_CODECS and ex.codec_name.lower() == "ac3":
                            self.app.settings.convert_audio = True
                            
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
        mode = self.app.settings.output_mode
        if mode == OutputMode.LOCAL:
            output_name = f"converted_{base_name}.mkv"
        elif mode == OutputMode.REMOTE:
            output_name = f"converted_{base_name}.mkv"
        else:  # OVERWRITE
            output_name = self.media_file.filename
        existing_exists = os.path.exists(output_name)

        est_size_mb = MediaConverter.estimate_output_size(self.media_file) / 1024 / 1024
        mode_tag = f"[{mode.value.upper()}] "
        target_info = f" Output: {mode_tag}{output_name} | Est. file size: {format_size(est_size_mb)}"

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
            
            display_info = track.display_info
            # Give visual feedback if the track is scheduled for DTS>AC3 transcoding
            if (
                self.app.settings.convert_audio 
                and track.enabled 
                and track.codec_type == "audio" 
                and track.codec_name.lower() in MediaConverter.DTS_CODECS
            ):
                display_info = display_info.replace("DTS", "DTS>AC3").replace("DTS-HD", "DTS-HD>AC3").replace("TRUEHD", "TRUEHD>AC3")

            line = f"{prefix}{check} Stream #{track.index}: {track.codec_type.upper():<10} {track_size_str:>11}{source_tag} | {display_info}"

            if idx == self.selected_idx:
                attr = curses.color_pair(5)
            elif track.codec_type == "video":
                attr = curses.color_pair(1)  # Highlight video tracks in Cyan
            elif not track.enabled:
                attr = curses.A_DIM  # Dim disabled tracks

            self.app.stdscr.addstr(i + TRACK_LIST_Y_OFFSET, 0, line[:width].ljust(width), attr)

        # Profile hint row (row height-2)
        if (
            self._profile_candidates
            and not self._profile_applied
            and not self.app.settings.profile_hint_dismissed
        ):
            parts = []
            if self.app.config.keep_langs:
                parts.append("keep: " + ", ".join(self.app.config.keep_langs))
            if self.app.config.discard_langs:
                parts.append("drop: " + ", ".join(self.app.config.discard_langs))
            hint = f" [A] Apply profile ({' | '.join(parts)}) "
            self.app.stdscr.addstr(
                height - 2, 0, hint.center(width)[: width - 1], curses.color_pair(2)
            )

        # Footer
        mouse_status = "APP" if self.app.mouse_enabled else "TERM"
        audio_tag = "DTS>AC3:On" if self.app.settings.convert_audio else "DTS>AC3:Off"
        
        if width < 110:
            footer = (
                f" [SPC] Tgl | [ENT] Play | [L] Lang | [S+↑/↓] Move"
                f" | [C] {audio_tag} | [S] Save | [P] Prof | [M] {mouse_status} | [Q] Back "
            )
        else:
            footer = (
                f" [SPACE] Toggle | [ENTER] Play | [L] Lang | [Shift+↑/↓] Reorder"
                f" | [C] {audio_tag} | [S] Save | [P] Profile | [M] Mouse:{mouse_status} | [Q/ESC] Back "
            )
            
        self.app.stdscr.addstr(
            height - 1, 0, footer.center(width)[: width - 1], curses.color_pair(3)
        )

        # Output Mode Dialog Overlay
        if self.showing_output_dialog:
            self._draw_output_dialog(height, width)
            
        # Overwrite Warning Dialog Overlay
        if self.showing_overwrite_warning:
            self._draw_overwrite_warning_dialog(height, width)

        # Profile Save Overlay
        if self.showing_profile_overlay:
            self._draw_profile_overlay(height, width)

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

        # Overlay dispatch: output mode dialog
        if self.showing_output_dialog:
            self._handle_output_dialog(key)
            return

        # Overlay dispatch: overwrite warning dialog
        if self.showing_overwrite_warning:
            self._handle_overwrite_warning_dialog(key)
            return

        # Overlay dispatch: profile save overlay
        if self.showing_profile_overlay:
            self._handle_profile_overlay(key)
            return

        if self.confirming_exit:
            if key in (ord("s"), ord("S")):
                # Start conversion — show output mode dialog if not yet chosen
                MediaPreview.stop()
                self.confirming_exit = False
                self._on_save_pressed()
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
                    mouse_status = "APP" if self.app.mouse_enabled else "TERM"
                    audio_tag = "AC3:On" if self.app.settings.convert_audio else "AC3:Off"
                    
                    if width < 110:
                        footer = (
                            f" [SPC] Tgl | [ENT] Play | [L] Lang | [S+↑/↓] Move"
                            f" | [C] {audio_tag} | [S] Save | [P] Prof | [M] {mouse_status} | [Q] Back "
                        )
                    else:
                        footer = (
                            f" [SPACE] Toggle | [ENTER] Play | [L] Lang | [Shift+↑/↓] Reorder"
                            f" | [C] Audio:{audio_tag} | [S] Save | [P] Profile | [M] Mouse:{mouse_status} | [Q/ESC] Back "
                        )
                    
                    # Center the footer
                    footer_start = (width - len(footer)) // 2
                    rel_x = mx - footer_start
                    
                    # Use dynamic position detection for all buttons
                    def find_button(text):
                        idx = footer.find(text)
                        if idx != -1:
                            return idx, idx + len(text)
                        return None, None
                        
                    # Check for Shift+↑/↓ or S+↑/↓ reorder buttons
                    shift_arrows = footer.find("[Shift+↑/↓]")
                    arrow_up, arrow_down = 7, 9
                    if shift_arrows == -1:
                        shift_arrows = footer.find("[S+↑/↓]")
                        arrow_up, arrow_down = 3, 5
                        
                    if shift_arrows != -1:
                        if shift_arrows + arrow_up <= rel_x <= shift_arrows + arrow_up + 1:
                            self.handle_input(curses.KEY_SR)  # Shift+Up
                            return
                        elif shift_arrows + arrow_down <= rel_x <= shift_arrows + arrow_down + 1:
                            self.handle_input(curses.KEY_SF)  # Shift+Down
                            return
                    
                    # Check other buttons
                    buttons = [
                        ("[SPACE]", KEY_SPACE),
                        ("[SPC]", KEY_SPACE),
                        ("[ENTER]", KEY_ENTER),
                        ("[ENT]", KEY_ENTER),
                        ("[L]", KEY_L_LOWER),
                        ("[C]", KEY_C_LOWER),
                        ("[S]", KEY_S_LOWER),
                        ("[P]", KEY_P_LOWER),
                        ("[M]", KEY_M_LOWER),
                        ("[Q/ESC]", KEY_Q_LOWER),
                        ("[Q]", KEY_Q_LOWER),
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
            self._on_save_pressed()
        elif key in (KEY_C_LOWER, KEY_C_UPPER):
            self.app.settings.convert_audio = not self.app.settings.convert_audio
            tag = "DTS to AC3 640k" if self.app.settings.convert_audio else "Copy (no transcode)"
            self.status_message = f" Audio conditioning: {tag} "
        elif key in (KEY_P_LOWER, KEY_P_UPPER):
            self._profile_keep = ", ".join(self.app.config.keep_langs)
            self._profile_discard = ", ".join(self.app.config.discard_langs)
            self._profile_prefer_ac3 = self.app.config.prefer_ac3_over_dts
            self._profile_field = 0
            self.showing_profile_overlay = True
        elif key in (KEY_O_LOWER, KEY_O_UPPER):
            # Shortcut: jump straight to output dialog
            self.showing_output_dialog = True
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
        # [A] Apply profile hint
        elif key in (ord("a"), ord("A")):
            if (
                self._profile_candidates
                and not self._profile_applied
                and not self.app.settings.profile_hint_dismissed
            ):
                self.app.config.apply_to(self.media_file)
                self._profile_applied = True
                self._profile_candidates = []
                self.status_message = " Profile applied. "
            else:
                # If already applied or no hint, treat A as normal (ignore or show msg)
                self.status_message = " No profile to apply. "
        # Dismiss profile hint with any unhandled key (but keep typing)
        # We suppress via profile_hint_dismissed only when user actively dismisses

    def _on_save_pressed(self):
        """Called when [S] is pressed.  Shows output mode dialog once per session."""
        if not self.app.settings.output_mode_chosen:
            self.showing_output_dialog = True
        else:
            self._start_conversion()

    def _start_conversion(self):
        """Commits changes and switches to ProgressView."""
        self.commit_changes()
        if self.batch_group:
            from .batch_progress import BatchProgressView
            self.app.switch_view(
                BatchProgressView(
                    self.app,
                    self.batch_group,
                    self.media_file,
                    self,
                    output_mode=self.app.settings.output_mode,
                    convert_audio=self.app.settings.convert_audio,
                )
            )
            return
            
        from .progress import ProgressView
        self.app.switch_view(
            ProgressView(
                self.app,
                self.media_file,
                self,
                output_mode=self.app.settings.output_mode,
                convert_audio=self.app.settings.convert_audio,
            )
        )

    def _draw_output_dialog(self, height, width):
        """Draw the output-mode selection overlay with contextual output preview."""
        source_dir = os.path.dirname(os.path.abspath(self.media_file.path))
        fs_writable = os.access(source_dir, os.W_OK)
        base_name = os.path.splitext(self.media_file.filename)[0]
        dir_name = os.path.basename(os.path.normpath(source_dir))
        is_batch = self.batch_group is not None

        # Compute preview paths per mode
        if is_batch:
            local_preview = f"./converted_{dir_name}/"
            remote_preview = f"…/{os.path.basename(os.path.dirname(source_dir))}/converted_{dir_name}/"
            file_count = f" ({self.batch_group.count} files)"
        else:
            local_preview = f"./converted_{base_name}.mkv"
            remote_preview = f"…/{dir_name}/converted_{base_name}.mkv"
            file_count = ""

        overwrite_preview = f"…/{dir_name}/{self.media_file.filename}"

        lines = [
            "  [O] Overwrite ─ modify in-place",
            f"      → {overwrite_preview}",
        ]
        if not fs_writable:
            lines.append("      ⚠ Source filesystem is read-only!")
        lines += [
            "",
            f"  New converted_* will be created{file_count}:",
            "  [L] Local  ─ save to CWD",
            f"      → {local_preview}",
            "  [R] Remote ─ save next to source",
            f"      → {remote_preview}",
        ]
        if not fs_writable:
            lines.append("      ⚠ Source filesystem is read-only!")
        lines += [
            "",
            "  [ESC] Cancel",
        ]

        mw = max(56, max(len(ln) + 4 for ln in lines))
        mw = min(mw, width - 4)  # Don't exceed terminal width
        mh = len(lines) + 3
        my = (height - mh) // 2
        mx = (width - mw) // 2
        for r in range(mh):
            self.app.stdscr.addstr(my + r, mx, " " * mw, curses.color_pair(3))
        title = "─" * (mw - 2)
        title_text = " Save As "
        tp = (len(title) - len(title_text)) // 2
        title = title[:tp] + title_text + title[tp + len(title_text):]
        self.app.stdscr.addstr(my, mx + 1, title[:mw-2], curses.color_pair(3) | curses.A_BOLD)
        for i, ln in enumerate(lines):
            attr = curses.color_pair(3)
            if "⚠" in ln:
                attr = curses.color_pair(4)
            elif ln.strip().startswith("→"):
                attr = curses.A_DIM
            self.app.stdscr.addstr(my + 2 + i, mx, ln[: mw], attr)

    def _handle_output_dialog(self, key):
        """Handle keypresses inside the output mode dialog."""
        if key in (KEY_ESC, ord("c"), ord("C")):
            self.showing_output_dialog = False
        elif key in (KEY_O_LOWER, KEY_O_UPPER):
            # Check if source filesystem is writable
            source_dir = os.path.dirname(os.path.abspath(self.media_file.path))
            if not os.access(source_dir, os.W_OK):
                self.status_message = " ⚠ Cannot overwrite: source filesystem is read-only! "
                self.showing_output_dialog = False
                return
            
            # Check for existing outputs that might cause confusion
            source_dir = os.path.dirname(os.path.abspath(self.media_file.path))
            dir_name = os.path.basename(os.path.normpath(source_dir))
            base_name = os.path.splitext(self.media_file.filename)[0]
            
            # Single-file residuals
            local_out = os.path.join(self.app.start_path, "converted_" + self.media_file.filename)
            remote_out = os.path.join(source_dir, "converted_" + self.media_file.filename)
            # Batch directory residuals
            batch_local = os.path.join(os.getcwd(), f"converted_{dir_name}", f"{base_name}.mkv")
            batch_remote = os.path.join(
                os.path.dirname(os.path.normpath(source_dir)),
                f"converted_{dir_name}",
                f"{base_name}.mkv",
            )
            
            self.residual_file_to_delete = None
            if os.path.exists(local_out):
                self.residual_file_to_delete = local_out
            elif os.path.exists(remote_out):
                self.residual_file_to_delete = remote_out
            elif os.path.exists(batch_local):
                self.residual_file_to_delete = batch_local
            elif os.path.exists(batch_remote):
                self.residual_file_to_delete = batch_remote
                
            if self.residual_file_to_delete:
                self.showing_output_dialog = False
                self.showing_overwrite_warning = True
            else:
                self.app.settings.output_mode = OutputMode.OVERWRITE
                self.app.settings.output_mode_chosen = True
                self.showing_output_dialog = False
                self._start_conversion()
        elif key in (ord("r"), ord("R")):
            source_dir = os.path.dirname(os.path.abspath(self.media_file.path))
            if not os.access(source_dir, os.W_OK):
                self.status_message = " ⚠ Cannot save remotely: source filesystem is read-only! "
                self.showing_output_dialog = False
                return
            self.app.settings.output_mode = OutputMode.REMOTE
            self.app.settings.output_mode_chosen = True
            self.showing_output_dialog = False
            self._start_conversion()
        elif key in (KEY_L_LOWER, KEY_L_UPPER):
            self.app.settings.output_mode = OutputMode.LOCAL
            self.app.settings.output_mode_chosen = True
            self.showing_output_dialog = False
            self._start_conversion()

    def _draw_overwrite_warning_dialog(self, height, width):
        """Draw the warning dialog when choosing OVERWRITE while residual files exist."""
        mw = 74
        mh = 8
        my = (height - mh) // 2
        mx = (width - mw) // 2
        for r in range(mh):
            self.app.stdscr.addstr(my + r, mx, " " * mw, curses.color_pair(4)) # Red Background
            
        title = "─── Residual Output Found ───────────────────────────────────"
        self.app.stdscr.addstr(my, mx + 1, title, curses.color_pair(4) | curses.A_BOLD)
        
        filename = os.path.basename(self.residual_file_to_delete)
        # Using [O]rphan format to clarify it's an orphaned file
        lines = [
            f"  A residual output file exists from a previous save:",
            f"  > {filename}",
            "  Delete this residual file to prevent workspace confusion?",
            "",
            "  [Y] Yes, Delete it | [N] No, Keep it | [ESC] Cancel"
        ]
        
        for i, ln in enumerate(lines):
            self.app.stdscr.addstr(my + 2 + i, mx, ln[: mw], curses.color_pair(4) | curses.A_BOLD)
            
    def _handle_overwrite_warning_dialog(self, key):
        """Handle keypresses inside the overwrite residual warning dialog."""
        if key in (KEY_ESC, ord("c"), ord("C")):
            self.showing_overwrite_warning = False
            # Re-open the output dialog so they can pick something else
            self.showing_output_dialog = True
        elif key in (ord("y"), ord("Y"), KEY_ENTER):
            # Delete residual
            try:
                if os.path.exists(self.residual_file_to_delete):
                    os.remove(self.residual_file_to_delete)
            except Exception as e:
                pass # Non-fatal if we can't delete it
            
            self.showing_overwrite_warning = False
            self.app.settings.output_mode = OutputMode.OVERWRITE
            self.app.settings.output_mode_chosen = True
            self._start_conversion()
        elif key in (ord("n"), ord("N")):
            # Don't delete, just continue with overwrite
            self.showing_overwrite_warning = False
            self.app.settings.output_mode = OutputMode.OVERWRITE
            self.app.settings.output_mode_chosen = True
            self._start_conversion()

    def _draw_profile_overlay(self, height, width):
        """Draw the profile save overlay."""
        mw = 58
        mh = 13
        my = (height - mh) // 2
        mx = (width - mw) // 2
        for r in range(mh):
            self.app.stdscr.addstr(my + r, mx, " " * mw, curses.color_pair(3))
        title = "─── Save Default Profile ──────────────────────────"
        self.app.stdscr.addstr(my, mx + 1, title[:mw-2], curses.color_pair(3) | curses.A_BOLD)

        # Save confirmation message (right under title)
        if self._profile_save_msg:
            self.app.stdscr.addstr(my + 1, mx + 2, self._profile_save_msg[:mw-4], curses.color_pair(5))

        label_w = 24
        val_w = mw - label_w - 4

        ac3_val = "[yes]" if self._profile_prefer_ac3 else "[no] "
        fields = [
            ("Keep languages:", self._profile_keep),
            ("Discard languages:", self._profile_discard),
            ("Prefer AC3 over DTS:", ac3_val),
        ]
        for i, (label, val) in enumerate(fields):
            is_active = self._profile_field == i
            attr = curses.color_pair(5) if is_active else curses.color_pair(3)
            row_y = my + 3 + i
            self.app.stdscr.addstr(row_y, mx, f"  {label:<{label_w}}"[:mw], attr)

            if is_active and i < 2 and self._profile_editing:
                # Editing mode: draw text field with cursor
                text = val
                cursor_pos = min(self._profile_cursor, len(text))
                before = text[:cursor_pos]
                after = text[cursor_pos:]
                val_x = mx + 2 + label_w
                self.app.stdscr.addstr(row_y, val_x, before[:val_w], attr)
                if cursor_pos < val_w:
                    cursor_ch = after[0] if after else " "
                    self.app.stdscr.addstr(row_y, val_x + len(before), cursor_ch, attr | curses.A_REVERSE)
                    if after[1:]:
                        self.app.stdscr.addstr(row_y, val_x + len(before) + 1, after[1:][:val_w - cursor_pos - 1], attr)
            else:
                self.app.stdscr.addstr(row_y, mx + 2 + label_w, val[:val_w], attr)

        # Contextual hint
        if self._profile_editing:
            ctx = "  [ENTER] Confirm | [ESC] Discard changes"
        elif self._profile_field in (0, 1):
            ctx = "  [ENTER] Edit (comma-separated, e.g. eng, fra)"
        else:
            ctx = "  [ENTER/SPACE] Toggle"
        self.app.stdscr.addstr(my + 7, mx, ctx[: mw], curses.A_DIM)

        hint = "  [TAB/↑↓] Navigate | [ESC] Close"
        self.app.stdscr.addstr(my + mh - 2, mx, hint[: mw], curses.color_pair(3))

    def _profile_get_text(self):
        """Return the current text field value for the active profile field."""
        return self._profile_keep if self._profile_field == 0 else self._profile_discard

    def _profile_set_text(self, val):
        """Set the current text field value for the active profile field."""
        if self._profile_field == 0:
            self._profile_keep = val
        else:
            self._profile_discard = val

    def _profile_save(self):
        """Save the current profile state to config."""
        self.app.config.keep_langs = [
            s.strip() for s in self._profile_keep.split(",") if s.strip()
        ]
        self.app.config.discard_langs = [
            s.strip() for s in self._profile_discard.split(",") if s.strip()
        ]
        self.app.config.prefer_ac3_over_dts = self._profile_prefer_ac3
        self.app.config.save()
        from ..core.config import CONFIG_PATH
        display_path = CONFIG_PATH.replace(os.path.expanduser("~"), "~")
        self._profile_save_msg = f"✓ Saved to {display_path}"

    def _handle_profile_overlay(self, key):
        """Handle keypresses inside the profile overlay (NC/MC style)."""
        if self._profile_editing:
            # Currently editing a text field
            if key == KEY_ESC:
                # Discard changes to this field
                self._profile_set_text(self._profile_edit_backup)
                self._profile_editing = False
                self._profile_save_msg = ""
            elif key == KEY_ENTER:
                # Confirm edit and auto-save
                self._profile_editing = False
                self._profile_save()
            else:
                # Text editing keys
                text = self._profile_get_text()
                pos = min(self._profile_cursor, len(text))

                if key == curses.KEY_LEFT:
                    self._profile_cursor = max(0, pos - 1)
                elif key == curses.KEY_RIGHT:
                    self._profile_cursor = min(len(text), pos + 1)
                elif key == curses.KEY_HOME:
                    self._profile_cursor = 0
                elif key == curses.KEY_END:
                    self._profile_cursor = len(text)
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    if pos > 0:
                        self._profile_set_text(text[:pos-1] + text[pos:])
                        self._profile_cursor = pos - 1
                elif key == curses.KEY_DC:
                    if pos < len(text):
                        self._profile_set_text(text[:pos] + text[pos+1:])
                elif 32 <= key <= 126:
                    ch = chr(key)
                    self._profile_set_text(text[:pos] + ch + text[pos:])
                    self._profile_cursor = pos + 1
            return

        # Not editing — navigation mode
        if key == KEY_ESC:
            self.showing_profile_overlay = False
        elif key in (curses.KEY_UP, curses.KEY_BTAB):
            self._profile_field = (self._profile_field - 1) % 3
        elif key in (curses.KEY_DOWN, ord("\t")):
            self._profile_field = (self._profile_field + 1) % 3
        elif key == KEY_ENTER:
            if self._profile_field == 2:
                # Boolean: toggle and auto-save
                self._profile_prefer_ac3 = not self._profile_prefer_ac3
                self._profile_save()
            else:
                # Text field: enter editing mode
                self._profile_editing = True
                self._profile_edit_backup = self._profile_get_text()
                self._profile_cursor = len(self._profile_get_text())
                self._profile_save_msg = ""
        elif self._profile_field == 2 and key in (KEY_SPACE,):
            self._profile_prefer_ac3 = not self._profile_prefer_ac3
            self._profile_save()

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

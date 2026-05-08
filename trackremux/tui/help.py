import curses
from importlib.metadata import version, PackageNotFoundError
from .constants import KEY_ESC, KEY_Q_LOWER, KEY_Q_UPPER, KEY_HELP, KEY_H_LOWER, KEY_H_UPPER

try:
    VERSION = version("trackremux")
except PackageNotFoundError:
    VERSION = "0.12.3"

# Help content for various screens
HELP_CONTENT = {
    "FileExplorer": """
[ Media Browser ] -- Your library at a glance.

This screen scans your directories to find video files and analyzes their 
track layouts. Use it to find files that are bloated with unwanted tracks 
or incompatible audio formats.

[ CONCEPTS ]
- SCANNING: TrackRemux scans your files in the background. It prioritizes 
  whatever is currently visible on your screen.
- GREEN SIZE: Means the file has been processed by TrackRemux.
- BADGES (THD, DTS, PCM): High-quality audio formats that might not play 
  on all devices. Use the [D] filter to find them.
- [B]ATCH: If similar files (like TV episodes) are found, group them to 
  apply the same settings to all at once.

[ KEYBOARD SHORTCUTS ]
- UP / DOWN:    Navigate the list.
- PgUp / PgDn:  Scroll by page.
- ENTER:        Open the selected file or directory.
- D:            Toggle filter (Show All vs. HD Audio only).
- B:            Open Batch Selector (if groups are detected).
- V:            Open Background Queue View.
- R:            Rescan current directory (clear cache).
- N / S / T / A: Sort by Name, Size, Tracks, or Audio Size.
- M:            Toggle Mouse support (App mode vs. Terminal mode).
- ?:            Show this Help screen.
- ESC / Q:      Quit the application.

[ ABOUT ]
TrackRemux v{VERSION}
A "Surgeon's Scalpel" for your media library.
Vibe coded on a Friday evening. "I'll just add one more thing" — every Saturday since.
© 2026 Yevgen Antymyrov. MIT License.
""".format(VERSION=VERSION),
    "TrackEditor": """
[ Track Editor ] -- Precise control for remuxing.

This is where you decide exactly what stays and what goes. Remuxing is 
lossless (no quality loss), extremely fast, and saves space.

[ CONCEPTS ]
- REMUXING: We copy the audio/video streams exactly as they are into a 
  new container, skipping the ones you unselected.
- [C]ONDITIONING: This flattens high-bitrate audio (DTS-HD, TrueHD) to 
  universally compatible EAC3 or AC3. Essential for older Smart TVs 
  or home theaters that don't support HD audio.
- [L]ANGUAGE: If a track is marked as 'und' (unknown), you can fix it 
  here so your media player recognizes it correctly.
- [D]ONOR: Import an audio track from a DIFFERENT file. Useful for 
  hybrid remuxes (e.g., matching a high-quality video with a specific 
  localized dub from another release).
- TRACK REORDERING: Use Shift+Arrow to move tracks. The first audio and 
  subtitle tracks will be the 'default' in most players.

[ KEYBOARD SHORTCUTS ]
- SPACE:        Toggle selected track (Keep vs. Discard).
- UP / DOWN:    Navigate tracks.
- Shift+UP/DN:  Move (reorder) the selected track.
- ENTER:        Preview the selected audio track (30s seekable).
- L:            Set language code for the selected track (e.g., 'eng').
- C:            Toggle HD Audio Conditioning (EAC3/AC3 fallback chain).
- P:            Open Profile Manager (set auto-rules for languages).
- A:            Apply your Profile to the current file instantly.
- D:            Open Donor File Picker to import external audio.
- S:            Start remuxing (opens Output Mode dialog).
- ?:            Show this Help screen.
- ESC / Q:      Back to Media Browser.
""",
    "BatchSelectorView": """
[ Batch Selector ] -- Save time with automation.

When multiple files (like TV episodes) share the same track structure, 
TrackRemux groups them here.

[ WHY BATCH? ]
Instead of editing 24 episodes one by one, you edit a 'Template' file, 
and TrackRemux identifies the same tracks in every other episode 
automatically—even if the internal ID numbers differ.

[ HOW TO USE ]
1. Select a group and press ENTER.
2. Edit the tracks in the 'Template' file.
3. Start the batch. TrackRemux handles the rest sequentially.
""",
    "BatchProgressView": """
[ Batch Processing ] -- Sit back and watch.

The application is now remuxing all files in your batch one by one.

- PROGRESS BAR: Shows the status of the current file.
- BATCH ETA: An estimate of when the entire season will be finished.
- Q / ESC: Cancels the batch safely after the current file finishes.

You can still use [C] to copy the ffmpeg command of the current file 
if you want to inspect what's happening under the hood.
""",
    "ProgressView": """
[ Conversion ] -- Remuxing in progress.

- REMUXING: This is a fast disk-IO operation. No re-encoding of video.
- SIZE: You can see the estimated final size vs. the current progress.
- ETA: Calculated based on processing speed.

On completion, you'll see a summary of the operation and any 
automatic fallbacks that occurred during audio conditioning.
"""
}


class HelpView:
    def __init__(self, app, view_name, back_view):
        self.app = app
        self.view_name = view_name
        self.back_view = back_view
        self.scroll_y = 0
        
        # Get content or fallback
        raw_text = HELP_CONTENT.get(view_name, "No help available for this screen.")
        # Split into lines for scrolling
        self.lines = [line.rstrip() for line in raw_text.strip().split("\n")]

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        # Draw Header
        title = f" HELP: {self.view_name} "
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * (width - 1))
        self.app.stdscr.addstr(0, max(0, (width - len(title)) // 2), title[:width - 1])
        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # Draw content lines
        max_visible = height - 2
        visible_lines = self.lines[self.scroll_y : self.scroll_y + max_visible]

        for i, line in enumerate(visible_lines):
            row = i + 1
            if row >= height - 1:
                break
            try:
                stripped = line.strip()
                # Section headers like [ CONCEPTS ] or [ KEYBOARD SHORTCUTS ]
                if stripped.startswith("[") and stripped.endswith("]") and not "-" in stripped[:3]:
                    attr = curses.color_pair(3) | curses.A_BOLD
                # Lines with keyboard hints like "- SPACE: ..." or "- [C] ..."
                elif stripped.startswith("- "):
                    attr = curses.A_NORMAL
                elif not stripped:
                    attr = curses.A_NORMAL
                else:
                    attr = curses.A_DIM
                safe_line = line[:width - 4]
                self.app.stdscr.addstr(row, 2, safe_line, attr)
            except curses.error:
                pass

        # Scroll indicator
        total = len(self.lines)
        if total > max_visible:
            pct = int(self.scroll_y / max(1, total - max_visible) * 100)
            scroll_hint = f" {pct}% "
            try:
                self.app.stdscr.addstr(height - 2, width - len(scroll_hint) - 1, scroll_hint, curses.A_DIM)
            except curses.error:
                pass

        # Draw Footer — must NOT write to the very last cell (width-1)
        footer = " [↑/↓] Scroll | [Q/ESC/?] Close "
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(height - 1, 0, " " * (width - 1))
        self.app.stdscr.addstr(height - 1, max(0, (width - len(footer)) // 2), footer[:width - 1])
        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        self.app.stdscr.refresh()

    def handle_input(self, key):
        height, _ = self.app.stdscr.getmaxyx()
        max_visible = height - 2

        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC, KEY_HELP, KEY_H_LOWER, KEY_H_UPPER):
            self.app.switch_view(self.back_view)
        elif key == curses.KEY_UP:
            if self.scroll_y > 0:
                self.scroll_y -= 1
        elif key == curses.KEY_DOWN:
            if self.scroll_y < len(self.lines) - max_visible:
                self.scroll_y += 1
        elif key == curses.KEY_PPAGE:  # Page Up
            self.scroll_y = max(0, self.scroll_y - max_visible)
        elif key == curses.KEY_NPAGE:  # Page Down
            self.scroll_y = min(max(0, len(self.lines) - max_visible), self.scroll_y + max_visible)
        elif key == curses.KEY_HOME:
            self.scroll_y = 0
        elif key == curses.KEY_END:
            self.scroll_y = max(0, len(self.lines) - max_visible)

import curses

from .constants import KEY_ENTER, KEY_ESC, KEY_Q_LOWER, KEY_Q_UPPER

# Direct import.
from .editor import TrackEditor


class BatchSelectorView:
    def __init__(self, app, explorer):
        self.app = app
        self.explorer = explorer
        self.back_view = explorer
        self.selected_idx = 0

    @property
    def batches(self):
        return self.explorer.batches

    def draw(self):
        self.app.stdscr.erase()
        height, width = self.app.stdscr.getmaxyx()

        # Header
        title = " Select Batch Group "
        self.app.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.app.stdscr.addstr(0, 0, " " * width)
        self.app.stdscr.addstr(0, (width - len(title)) // 2, title)
        self.app.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

        # List
        y_offset = 2
        max_display = height - 4

        batches = self.batches
        if self.selected_idx >= len(batches):
            self.selected_idx = max(0, len(batches) - 1)

        start_idx = max(0, self.selected_idx - max_display + 1)
        end_idx = min(len(batches), start_idx + max_display)

        for i in range(start_idx, end_idx):
            batch = batches[i]
            y = y_offset + (i - start_idx)

            prefix = "> " if i == self.selected_idx else "  "
            attr = (
                curses.color_pair(5) | curses.A_BOLD if i == self.selected_idx else curses.A_NORMAL
            )

            line = f"{prefix}{batch.name} {batch.display_fingerprint} ({batch.count} files)"

            self.app.stdscr.addstr(y, 2, line[: width - 4], attr)

        # Footer
        footer = " [ENTER] Select | [Q/ESC] Back "
        self.app.stdscr.addstr(
            height - 1, 0, footer.center(width)[: width - 1], curses.color_pair(3)
        )

        self.app.stdscr.refresh()

    def handle_input(self, key):
        batches = self.batches
        if key in (KEY_Q_LOWER, KEY_Q_UPPER, KEY_ESC):
            self.app.switch_view(self.back_view)
        elif key == curses.KEY_UP:
            if self.selected_idx > 0:
                self.selected_idx -= 1
        elif key == curses.KEY_DOWN:
            if self.selected_idx < len(batches) - 1:
                self.selected_idx += 1
        elif key == KEY_ENTER and batches:
            batch = batches[self.selected_idx]
            media_file = batch.files[0]

            self.app.switch_view(
                TrackEditor(self.app, media_file, back_view=self, batch_group=batch)
            )

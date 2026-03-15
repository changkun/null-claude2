#!/usr/bin/env python3
"""Terminal-based Conway's Game of Life simulator using curses."""

import argparse
import curses
import json
import random
from collections import Counter

# ---------------------------------------------------------------------------
# Pattern library — each pattern is a list of (row, col) offsets from origin
# ---------------------------------------------------------------------------

PATTERNS = {
    "Block": [(0, 0), (0, 1), (1, 0), (1, 1)],
    "Blinker": [(0, 0), (0, 1), (0, 2)],
    "Beacon": [(0, 0), (0, 1), (1, 0), (1, 1), (2, 2), (2, 3), (3, 2), (3, 3)],
    "Glider": [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)],
    "LWSS": [
        (0, 1), (0, 4),
        (1, 0),
        (2, 0), (2, 4),
        (3, 0), (3, 1), (3, 2), (3, 3),
    ],
    "R-pentomino": [(0, 1), (0, 2), (1, 0), (1, 1), (2, 1)],
    "Diehard": [
        (0, 6),
        (1, 0), (1, 1),
        (2, 1), (2, 5), (2, 6), (2, 7),
    ],
    "Acorn": [
        (0, 1),
        (1, 3),
        (2, 0), (2, 1), (2, 4), (2, 5), (2, 6),
    ],
    "Pentadecathlon": [
        (0, 1),
        (1, 1),
        (2, 0), (2, 2),
        (3, 1),
        (4, 1),
        (5, 1),
        (6, 1),
        (7, 0), (7, 2),
        (8, 1),
        (9, 1),
    ],
    "Pulsar": [
        # Top-left quadrant (and symmetry)
        (0, 2), (0, 3), (0, 4), (0, 8), (0, 9), (0, 10),
        (2, 0), (2, 5), (2, 7), (2, 12),
        (3, 0), (3, 5), (3, 7), (3, 12),
        (4, 0), (4, 5), (4, 7), (4, 12),
        (5, 2), (5, 3), (5, 4), (5, 8), (5, 9), (5, 10),
        (7, 2), (7, 3), (7, 4), (7, 8), (7, 9), (7, 10),
        (8, 0), (8, 5), (8, 7), (8, 12),
        (9, 0), (9, 5), (9, 7), (9, 12),
        (10, 0), (10, 5), (10, 7), (10, 12),
        (12, 2), (12, 3), (12, 4), (12, 8), (12, 9), (12, 10),
    ],
    "Gosper Glider Gun": [
        (0, 24),
        (1, 22), (1, 24),
        (2, 12), (2, 13), (2, 20), (2, 21), (2, 34), (2, 35),
        (3, 11), (3, 15), (3, 20), (3, 21), (3, 34), (3, 35),
        (4, 0), (4, 1), (4, 10), (4, 16), (4, 20), (4, 21),
        (5, 0), (5, 1), (5, 10), (5, 14), (5, 16), (5, 17), (5, 22), (5, 24),
        (6, 10), (6, 16), (6, 24),
        (7, 11), (7, 15),
        (8, 12), (8, 13),
    ],
}

PATTERN_NAMES = list(PATTERNS.keys())


# ---------------------------------------------------------------------------
# Grid — simulation logic, decoupled from UI
# ---------------------------------------------------------------------------

class Grid:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells: set[tuple[int, int]] = set()

    def tick(self) -> None:
        """Advance one generation using B3/S23 rules."""
        neighbor_count: Counter[tuple[int, int]] = Counter()
        for r, c in self.cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < self.height and 0 <= nc < self.width:
                        neighbor_count[(nr, nc)] += 1
        new_cells = set()
        for pos, count in neighbor_count.items():
            if count == 3 or (count == 2 and pos in self.cells):
                new_cells.add(pos)
        self.cells = new_cells

    def toggle_cell(self, r: int, c: int) -> None:
        pos = (r, c)
        if pos in self.cells:
            self.cells.discard(pos)
        else:
            self.cells.add(pos)

    def clear(self) -> None:
        self.cells.clear()

    def randomize(self, density: float = 0.3) -> None:
        self.cells.clear()
        for r in range(self.height):
            for c in range(self.width):
                if random.random() < density:
                    self.cells.add((r, c))

    def place_pattern(self, pattern: list[tuple[int, int]], origin_r: int, origin_c: int) -> None:
        for dr, dc in pattern:
            r, c = origin_r + dr, origin_c + dc
            if 0 <= r < self.height and 0 <= c < self.width:
                self.cells.add((r, c))

    def to_dict(self, generation: int = 0) -> dict:
        return {
            "version": 1,
            "width": self.width,
            "height": self.height,
            "generation": generation,
            "cells": sorted(self.cells),
        }

    @classmethod
    def from_dict(cls, data: dict) -> tuple["Grid", int]:
        g = cls(data["width"], data["height"])
        g.cells = {tuple(c) for c in data["cells"]}
        return g, data.get("generation", 0)


# ---------------------------------------------------------------------------
# App — curses UI controller
# ---------------------------------------------------------------------------

class App:
    def __init__(self, stdscr, width: int, height: int, filepath: str = "save.json"):
        self.stdscr = stdscr
        self.grid = Grid(width, height)
        self.running = False
        self.speed = 5  # ticks per second, range 1-20
        self.cursor_r = height // 2
        self.cursor_c = width // 2
        self.pattern_idx: int | None = None  # None = single-cell mode
        self.generation = 0
        self.filepath = filepath
        self.message = ""
        self.message_ttl = 0
        # Viewport offset for scrolling
        self.view_r = 0
        self.view_c = 0

    # --- main loop ---

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self._init_colors()
        self._update_timeout()

        while True:
            if not self._handle_input():
                break
            if self.running:
                self.grid.tick()
                self.generation += 1
            self._update_viewport()
            self._draw()

    # --- colors ---

    def _init_colors(self) -> None:
        self.use_color = curses.has_colors()
        if self.use_color:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)   # alive cells
            curses.init_pair(2, curses.COLOR_YELLOW, -1)  # cursor
            curses.init_pair(3, curses.COLOR_CYAN, -1)    # status bar
            curses.init_pair(4, curses.COLOR_MAGENTA, -1) # ghost pattern preview

    # --- input ---

    def _handle_input(self) -> bool:
        """Process input. Returns False to quit."""
        key = self.stdscr.getch()
        if key == -1:
            return True

        # Quit
        if key == ord("q"):
            return False

        # Movement
        if key in (curses.KEY_UP, ord("k")):
            self.cursor_r = max(0, self.cursor_r - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor_r = min(self.grid.height - 1, self.cursor_r + 1)
        elif key in (curses.KEY_LEFT, ord("h")):
            self.cursor_c = max(0, self.cursor_c - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            self.cursor_c = min(self.grid.width - 1, self.cursor_c + 1)

        # Toggle run / pause
        elif key == ord(" "):
            self.running = not self.running

        # Step
        elif key == ord("s"):
            if not self.running:
                self.grid.tick()
                self.generation += 1

        # Randomize
        elif key == ord("r"):
            self.grid.randomize()
            self.generation = 0
            self._set_message("Randomized")

        # Clear
        elif key == ord("c"):
            self.grid.clear()
            self.generation = 0
            self._set_message("Cleared")

        # Place cell or pattern
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.pattern_idx is not None:
                pat = PATTERNS[PATTERN_NAMES[self.pattern_idx]]
                self.grid.place_pattern(pat, self.cursor_r, self.cursor_c)
            else:
                self.grid.toggle_cell(self.cursor_r, self.cursor_c)

        # Pattern cycling
        elif key == ord("p"):
            if self.pattern_idx is None:
                self.pattern_idx = 0
            else:
                self.pattern_idx = (self.pattern_idx - 1) % len(PATTERN_NAMES)
        elif key == ord("n"):
            if self.pattern_idx is None:
                self.pattern_idx = 0
            else:
                self.pattern_idx = (self.pattern_idx + 1) % len(PATTERN_NAMES)

        # Deselect pattern
        elif key == 27:  # Escape
            self.pattern_idx = None

        # Speed control
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()

        # Save / Load
        elif key == ord("w"):
            self._save()
        elif key == ord("o"):
            self._load()

        # Resize
        elif key == curses.KEY_RESIZE:
            pass  # viewport recalculated each frame

        return True

    # --- viewport ---

    def _update_viewport(self) -> None:
        max_h, max_w = self.stdscr.getmaxyx()
        grid_rows = max(1, max_h - 3)
        grid_cols = max(1, max_w // 2)  # each cell is 2 chars wide

        # Center viewport on cursor
        self.view_r = max(0, min(self.cursor_r - grid_rows // 2, self.grid.height - grid_rows))
        self.view_c = max(0, min(self.cursor_c - grid_cols // 2, self.grid.width - grid_cols))
        self.view_r = max(0, self.view_r)
        self.view_c = max(0, self.view_c)

    # --- drawing ---

    def _draw(self) -> None:
        self.stdscr.erase()
        max_h, max_w = self.stdscr.getmaxyx()
        grid_rows = max(1, max_h - 3)
        grid_cols = max(1, max_w // 2)

        # Build ghost preview set for pattern
        ghost: set[tuple[int, int]] = set()
        if self.pattern_idx is not None:
            pat = PATTERNS[PATTERN_NAMES[self.pattern_idx]]
            for dr, dc in pat:
                ghost.add((self.cursor_r + dr, self.cursor_c + dc))

        # Draw grid
        for screen_r in range(min(grid_rows, self.grid.height)):
            r = screen_r + self.view_r
            if r >= self.grid.height:
                break
            for screen_c in range(min(grid_cols, self.grid.width)):
                c = screen_c + self.view_c
                if c >= self.grid.width:
                    break
                x = screen_c * 2
                if x + 1 >= max_w:
                    break

                is_alive = (r, c) in self.grid.cells
                is_cursor = (r == self.cursor_r and c == self.cursor_c)
                is_ghost = (r, c) in ghost

                if is_cursor:
                    attr = curses.A_REVERSE
                    if self.use_color:
                        attr |= curses.color_pair(2)
                    ch = "██" if is_alive else "▒▒"
                elif is_alive:
                    attr = curses.color_pair(1) if self.use_color else curses.A_BOLD
                    ch = "██"
                elif is_ghost:
                    attr = curses.color_pair(4) if self.use_color else curses.A_DIM
                    ch = "░░"
                else:
                    attr = 0
                    ch = "  "

                try:
                    self.stdscr.addstr(screen_r, x, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            state = "RUNNING" if self.running else "PAUSED"
            status = (
                f" Gen: {self.generation} | Cells: {len(self.grid.cells)} | "
                f"Speed: {self.speed} | {state} "
            )
            if self.message_ttl > 0:
                status += f"| {self.message} "
                self.message_ttl -= 1
            attr = curses.color_pair(3) | curses.A_BOLD if self.use_color else curses.A_REVERSE
            try:
                self.stdscr.addstr(status_y, 0, status.ljust(max_w - 1)[:max_w - 1], attr)
            except curses.error:
                pass

        # Help bar
        help_y = max_h - 1
        if help_y > 0:
            pat_name = PATTERN_NAMES[self.pattern_idx] if self.pattern_idx is not None else "None"
            help_text = (
                f" [Space]Run [S]tep [R]and [C]lear [Q]uit | "
                f"[P/N]Pattern: {pat_name} [Enter]Place [Esc]Desel | "
                f"[+/-]Speed [W]Save [O]Load"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

        self.stdscr.refresh()

    # --- save / load ---

    def _save(self) -> None:
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.grid.to_dict(self.generation), f)
            self._set_message(f"Saved to {self.filepath}")
        except OSError as e:
            self._set_message(f"Save error: {e}")

    def _load(self) -> None:
        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
            self.grid, self.generation = Grid.from_dict(data)
            self.cursor_r = min(self.cursor_r, self.grid.height - 1)
            self.cursor_c = min(self.cursor_c, self.grid.width - 1)
            self._set_message(f"Loaded from {self.filepath}")
        except (OSError, json.JSONDecodeError, KeyError) as e:
            self._set_message(f"Load error: {e}")

    # --- helpers ---

    def _update_timeout(self) -> None:
        self.stdscr.timeout(1000 // self.speed)

    def _set_message(self, msg: str) -> None:
        self.message = msg
        self.message_ttl = self.speed * 2  # show for ~2 seconds


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Conway's Game of Life — terminal simulator")
    parser.add_argument("--width", type=int, default=0, help="Grid width (0 = auto-fit terminal)")
    parser.add_argument("--height", type=int, default=0, help="Grid height (0 = auto-fit terminal)")
    parser.add_argument("--file", type=str, default="save.json", help="Save/load file path")
    args = parser.parse_args()

    def start(stdscr):
        max_h, max_w = stdscr.getmaxyx()
        w = args.width if args.width > 0 else max(1, max_w // 2)
        h = args.height if args.height > 0 else max(1, max_h - 3)
        app = App(stdscr, w, h, filepath=args.file)
        app.run()

    curses.wrapper(start)


if __name__ == "__main__":
    main()

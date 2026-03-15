#!/usr/bin/env python3
"""Terminal-based cellular automaton simulator using curses."""

import argparse
import curses
import json
import os
import random
from collections import Counter
from typing import ClassVar

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

CUSTOM_PATTERNS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patterns.json")


def load_custom_patterns() -> dict[str, list[tuple[int, int]]]:
    """Load user-created patterns from patterns.json."""
    try:
        with open(CUSTOM_PATTERNS_FILE, "r") as f:
            data = json.load(f)
        return {name: [tuple(c) for c in cells] for name, cells in data.items()}
    except (OSError, json.JSONDecodeError):
        return {}


def save_custom_patterns(patterns: dict[str, list[tuple[int, int]]]) -> None:
    """Save user-created patterns to patterns.json."""
    data = {name: [list(c) for c in cells] for name, cells in patterns.items()}
    with open(CUSTOM_PATTERNS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_all_patterns() -> tuple[dict[str, list[tuple[int, int]]], list[str]]:
    """Return merged built-in + custom patterns and ordered name list."""
    custom = load_custom_patterns()
    merged = dict(PATTERNS)
    merged.update(custom)
    names = list(PATTERNS.keys()) + [n for n in custom if n not in PATTERNS]
    return merged, names


PATTERN_NAMES = list(PATTERNS.keys())


# ---------------------------------------------------------------------------
# Ruleset — birth/survival conditions for outer-totalistic cellular automata
# ---------------------------------------------------------------------------

RULESETS = [
    ("Life", {3}, {2, 3}),                          # B3/S23 — Conway's Game of Life
    ("HighLife", {3, 6}, {2, 3}),                    # B36/S23 — has a replicator
    ("Day & Night", {3, 6, 7, 8}, {3, 4, 6, 7, 8}), # B3678/S34678
    ("Seeds", {2}, set()),                           # B2/S — every cell dies each tick
    ("Life w/o Death", {3}, set(range(9))),           # B3/S012345678 — cells never die
    ("Diamoeba", {3, 5, 6, 7, 8}, {5, 6, 7, 8}),    # B35678/S5678
    ("Replicator", {1, 3, 5, 7}, {1, 3, 5, 7}),     # B1357/S1357
    ("2x2", {3, 6}, {1, 2, 5}),                      # B36/S125
    ("Morley", {3, 6, 8}, {2, 4, 5}),                # B368/S245 — Move
    ("Anneal", {4, 6, 7, 8}, {3, 5, 6, 7, 8}),      # B4678/S35678
]


def rule_string(birth: set[int], survival: set[int]) -> str:
    """Format a ruleset as a B/S notation string, e.g. 'B3/S23'."""
    b = "".join(str(d) for d in sorted(birth))
    s = "".join(str(d) for d in sorted(survival))
    return f"B{b}/S{s}"


# ---------------------------------------------------------------------------
# Grid — simulation logic, decoupled from UI
# ---------------------------------------------------------------------------

class Grid:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells: set[tuple[int, int]] = set()
        self.ages: dict[tuple[int, int], int] = {}  # cell -> generations alive
        self.toroidal = False
        self.birth: set[int] = {3}        # neighbor counts that birth a cell
        self.survival: set[int] = {2, 3}  # neighbor counts that keep a cell alive

    def tick(self) -> None:
        """Advance one generation using current birth/survival rules."""
        neighbor_count: Counter[tuple[int, int]] = Counter()
        for r, c in self.cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if self.toroidal:
                        nr %= self.height
                        nc %= self.width
                    elif not (0 <= nr < self.height and 0 <= nc < self.width):
                        continue
                    neighbor_count[(nr, nc)] += 1
        new_cells = set()
        new_ages: dict[tuple[int, int], int] = {}
        for pos, count in neighbor_count.items():
            if pos in self.cells:
                if count in self.survival:
                    new_cells.add(pos)
                    new_ages[pos] = self.ages.get(pos, 0) + 1
            else:
                if count in self.birth:
                    new_cells.add(pos)
                    new_ages[pos] = 1
        self.cells = new_cells
        self.ages = new_ages

    def toggle_cell(self, r: int, c: int) -> None:
        pos = (r, c)
        if pos in self.cells:
            self.cells.discard(pos)
            self.ages.pop(pos, None)
        else:
            self.cells.add(pos)
            self.ages[pos] = 1

    def clear(self) -> None:
        self.cells.clear()
        self.ages.clear()

    def randomize(self, density: float = 0.3) -> None:
        self.cells.clear()
        self.ages.clear()
        for r in range(self.height):
            for c in range(self.width):
                if random.random() < density:
                    self.cells.add((r, c))
                    self.ages[(r, c)] = 1

    def set_cell(self, r: int, c: int) -> None:
        """Set a cell to alive (no toggle — always turns on)."""
        if 0 <= r < self.height and 0 <= c < self.width:
            pos = (r, c)
            if pos not in self.cells:
                self.cells.add(pos)
                self.ages[pos] = 1

    def place_pattern(self, pattern: list[tuple[int, int]], origin_r: int, origin_c: int) -> None:
        for dr, dc in pattern:
            r, c = origin_r + dr, origin_c + dc
            if 0 <= r < self.height and 0 <= c < self.width:
                self.cells.add((r, c))
                self.ages[(r, c)] = 1

    def to_dict(self, generation: int = 0) -> dict:
        return {
            "version": 2,
            "width": self.width,
            "height": self.height,
            "generation": generation,
            "cells": sorted(self.cells),
            "ages": {f"{r},{c}": age for (r, c), age in self.ages.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> tuple["Grid", int]:
        g = cls(data["width"], data["height"])
        g.cells = {tuple(c) for c in data["cells"]}
        if "ages" in data:
            g.ages = {tuple(int(x) for x in k.split(",")): v for k, v in data["ages"].items()}
        else:
            g.ages = {pos: 1 for pos in g.cells}
        return g, data.get("generation", 0)


# ---------------------------------------------------------------------------
# Pattern detector — identifies known still lifes, oscillators, spaceships
# ---------------------------------------------------------------------------

class PatternDetector:
    """Detects known Game of Life patterns on the grid."""

    # Base pattern definitions: name → (category, cells as (row, col) offsets)
    DEFINITIONS: ClassVar[dict[str, tuple[str, list[tuple[int, int]]]]] = {
        # Still lifes
        "Block":   ("still", [(0, 0), (0, 1), (1, 0), (1, 1)]),
        "Beehive": ("still", [(0, 1), (0, 2), (1, 0), (1, 3), (2, 1), (2, 2)]),
        "Loaf":    ("still", [(0, 1), (0, 2), (1, 0), (1, 3), (2, 1), (2, 3), (3, 2)]),
        "Boat":    ("still", [(0, 0), (0, 1), (1, 0), (1, 2), (2, 1)]),
        "Tub":     ("still", [(0, 1), (1, 0), (1, 2), (2, 1)]),
        "Pond":    ("still", [(0, 1), (0, 2), (1, 0), (1, 3), (2, 0), (2, 3), (3, 1), (3, 2)]),
        "Ship":    ("still", [(0, 0), (0, 1), (1, 0), (1, 2), (2, 1), (2, 2)]),
        # Oscillators
        "Blinker": ("oscillator", [(0, 0), (0, 1), (0, 2)]),
        "Toad":    ("oscillator", [(0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2)]),
        "Beacon":  ("oscillator", [(0, 0), (0, 1), (1, 0), (1, 1), (2, 2), (2, 3), (3, 2), (3, 3)]),
        # Spaceships
        "Glider":  ("spaceship", [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]),
        "LWSS":    ("spaceship", [
            (0, 1), (0, 4), (1, 0), (2, 0), (2, 4), (3, 0), (3, 1), (3, 2), (3, 3),
        ]),
    }

    # Category display order
    CATEGORIES = ["still", "oscillator", "spaceship"]
    CATEGORY_LABELS = {"still": "Still Lifes", "oscillator": "Oscillators", "spaceship": "Spaceships"}

    def __init__(self) -> None:
        # templates: list of (name, category, size, list of frozenset variants)
        self.templates: list[tuple[str, str, int, list[frozenset[tuple[int, int]]]]] = []
        self._build_templates()

    # --- template generation helpers ---

    @staticmethod
    def _normalize(cells) -> frozenset[tuple[int, int]]:
        """Normalize cell offsets so min row and col are 0."""
        if not cells:
            return frozenset()
        min_r = min(r for r, c in cells)
        min_c = min(c for r, c in cells)
        return frozenset((r - min_r, c - min_c) for r, c in cells)

    @staticmethod
    def _orientations(cells) -> set[frozenset[tuple[int, int]]]:
        """Generate all 8 orientations (4 rotations x 2 reflections), normalized."""
        results: set[frozenset[tuple[int, int]]] = set()
        coords = list(cells)
        for flip in (False, True):
            current = [(r, -c) if flip else (r, c) for r, c in coords]
            for _ in range(4):
                results.add(PatternDetector._normalize(current))
                current = [(-c, r) for r, c in current]  # 90° CW rotation
        return results

    @staticmethod
    def _tick_isolated(cells: set[tuple[int, int]]) -> set[tuple[int, int]]:
        """Compute one generation for an isolated set of cells (unbounded)."""
        neighbor_count: Counter[tuple[int, int]] = Counter()
        for r, c in cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    neighbor_count[(r + dr, c + dc)] += 1
        new_cells: set[tuple[int, int]] = set()
        for pos, count in neighbor_count.items():
            if count == 3 or (count == 2 and pos in cells):
                new_cells.add(pos)
        return new_cells

    @staticmethod
    def _compute_phases(base_cells: list[tuple[int, int]], max_period: int = 8) -> list[list[tuple[int, int]]]:
        """Compute all distinct phases of a pattern by simulating in isolation."""
        phases = [list(base_cells)]
        current = set(base_cells)
        seen_norms: set[frozenset[tuple[int, int]]] = {PatternDetector._normalize(base_cells)}

        for _ in range(max_period):
            current = PatternDetector._tick_isolated(current)
            if not current:
                break
            norm = PatternDetector._normalize(current)
            if norm in seen_norms:
                break
            # Check if it's an orientation of an already-seen phase
            orientations = PatternDetector._orientations(current)
            if any(o in seen_norms for o in orientations):
                break
            seen_norms.add(norm)
            phases.append(list(current))
        return phases

    def _build_templates(self) -> None:
        """Build detection templates from definitions."""
        for name, (category, base_cells) in self.DEFINITIONS.items():
            if category == "still":
                phases = [base_cells]
            else:
                phases = self._compute_phases(base_cells)

            all_variants: set[frozenset[tuple[int, int]]] = set()
            for phase in phases:
                all_variants.update(self._orientations(phase))

            self.templates.append((name, category, len(base_cells), list(all_variants)))

        # Sort by size descending — match larger patterns first
        self.templates.sort(key=lambda t: -t[2])

    # --- detection ---

    def detect(self, cells: set[tuple[int, int]]) -> tuple[dict[str, int], dict[tuple[int, int], str]]:
        """Detect patterns in the given cell set.

        Returns (counts, highlights) where:
          counts: {pattern_name: count}
          highlights: {cell_position: pattern_name}
        """
        remaining = set(cells)
        counts: dict[str, int] = {}
        highlights: dict[tuple[int, int], str] = {}

        for name, category, size, variants in self.templates:
            if len(remaining) < size:
                continue
            # Precompute: for each variant, pick the first cell (sorted) and
            # compute relative offsets for the remaining cells.
            variant_checks: list[tuple[tuple[int, int], list[tuple[int, int]], frozenset[tuple[int, int]]]] = []
            for variant in variants:
                sorted_cells = sorted(variant)
                first = sorted_cells[0]
                offsets = [(r - first[0], c - first[1]) for r, c in sorted_cells[1:]]
                variant_checks.append((first, offsets, variant))

            found = True
            while found:
                found = False
                if len(remaining) < size:
                    break
                for first, offsets, variant in variant_checks:
                    for ar, ac in list(remaining):
                        # Try placing variant so that 'first' maps to (ar, ac)
                        placed = {(ar, ac)}
                        match = True
                        for dr, dc in offsets:
                            pos = (ar + dr, ac + dc)
                            if pos not in remaining:
                                match = False
                                break
                            placed.add(pos)
                        if match:
                            remaining -= placed
                            counts[name] = counts.get(name, 0) + 1
                            for cell in placed:
                                highlights[cell] = name
                            found = True
                            break
                    if found:
                        break

        return counts, highlights


# ---------------------------------------------------------------------------
# App — curses UI controller
# ---------------------------------------------------------------------------

class App:
    HISTORY_MAX = 500  # max generations to keep in history
    SPARKLINE_WIDTH = 40  # number of generations shown in sparkline

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
        # History timeline: list of (generation, frozenset of cells, ages dict)
        self.history: list[tuple[int, frozenset[tuple[int, int]], dict[tuple[int, int], int]]] = []
        self.history_pos: int = -1  # -1 means live (not rewound)
        # Population history for sparkline
        self.pop_history: list[int] = []
        # Pattern library (built-in + custom, refreshed on changes)
        self._refresh_patterns()
        # Dashboard (pattern census) state
        self.dashboard = False
        self.detector = PatternDetector()
        self.detected_counts: dict[str, int] = {}
        self.detected_highlights: dict[tuple[int, int], str] = {}
        # Rule explorer state
        self.rule_idx = 0  # index into RULESETS (0 = standard Life)
        # Blueprint mode state
        self.blueprint_mode = False
        self.blueprint_cells: set[tuple[int, int]] = set()  # cells drawn in blueprint
        self.sel_corner1: tuple[int, int] | None = None  # first selection corner
        self.sel_corner2: tuple[int, int] | None = None  # second selection corner
        # Brush mode state
        self.brush_active = False  # True while painting
        self.brush_size = 1       # radius: 1 → 1x1, 2 → 3x3, 3 → 5x5, etc.
        self.brush_shape = "square"  # "square", "diamond", "circle"
        self.BRUSH_SHAPES = ["square", "diamond", "circle"]

    def _refresh_patterns(self) -> None:
        """Reload merged pattern library from built-in + custom patterns."""
        self.all_patterns, self.all_pattern_names = get_all_patterns()

    # --- main loop ---

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self._init_colors()
        self._update_timeout()

        while True:
            if not self._handle_input():
                break
            if self.running and self.history_pos == -1:
                self._record_history()
                self._record_population()
                self.grid.tick()
                self.generation += 1
            self._update_viewport()
            self._draw()

    # --- colors ---

    # Age thresholds for color tiers
    AGE_YOUNG = 5
    AGE_MATURE = 20
    AGE_ANCIENT = 50

    def _init_colors(self) -> None:
        self.use_color = curses.has_colors()
        if self.use_color:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)   # newborn cells (age 1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)  # cursor
            curses.init_pair(3, curses.COLOR_CYAN, -1)    # status bar
            curses.init_pair(4, curses.COLOR_MAGENTA, -1) # ghost pattern preview
            curses.init_pair(5, curses.COLOR_CYAN, -1)    # young cells
            curses.init_pair(6, curses.COLOR_YELLOW, -1)  # mature cells
            curses.init_pair(7, curses.COLOR_RED, -1)     # ancient cells
            # Dashboard highlight colors (pattern categories)
            curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_BLUE)     # still life
            curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_MAGENTA)  # oscillator
            curses.init_pair(10, curses.COLOR_WHITE, curses.COLOR_RED)     # spaceship
            curses.init_pair(11, curses.COLOR_CYAN, -1)                   # dashboard text

    def _age_color_pair(self, age: int) -> int:
        """Return curses color pair number based on cell age."""
        if age < self.AGE_YOUNG:
            return 1   # green — newborn
        elif age < self.AGE_MATURE:
            return 5   # cyan — young
        elif age < self.AGE_ANCIENT:
            return 6   # yellow — mature
        else:
            return 7   # red — ancient

    # --- input ---

    def _handle_input(self) -> bool:
        """Process input. Returns False to quit."""
        key = self.stdscr.getch()
        if key == -1:
            return True

        # Blueprint mode has its own input handler
        if self.blueprint_mode:
            return self._handle_blueprint_input(key)

        # Quit
        if key == ord("q"):
            return False

        # Movement
        moved = False
        if key in (curses.KEY_UP, ord("k")):
            self.cursor_r = max(0, self.cursor_r - 1)
            moved = True
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor_r = min(self.grid.height - 1, self.cursor_r + 1)
            moved = True
        elif key in (curses.KEY_LEFT, ord("h")):
            self.cursor_c = max(0, self.cursor_c - 1)
            moved = True
        elif key in (curses.KEY_RIGHT, ord("l")):
            self.cursor_c = min(self.grid.width - 1, self.cursor_c + 1)
            moved = True

        # Paint while brush is active and cursor moves
        if moved and self.brush_active:
            self._brush_paint()

        # Toggle run / pause
        if not moved and key == ord(" "):
            self.running = not self.running

        # Step
        elif key == ord("s"):
            if not self.running and self.history_pos == -1:
                self._record_history()
                self._record_population()
                self.grid.tick()
                self.generation += 1

        # Randomize
        elif key == ord("r"):
            self.grid.randomize()
            self.generation = 0
            self.history.clear()
            self.history_pos = -1
            self.pop_history.clear()
            self._set_message("Randomized")

        # Clear
        elif key == ord("c"):
            self.grid.clear()
            self.generation = 0
            self.history.clear()
            self.history_pos = -1
            self.pop_history.clear()
            self._set_message("Cleared")

        # Place cell or pattern (or brush stamp)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.pattern_idx is not None:
                pat = self.all_patterns[self.all_pattern_names[self.pattern_idx]]
                self.grid.place_pattern(pat, self.cursor_r, self.cursor_c)
            elif self.brush_size > 1:
                self._brush_paint()
            else:
                self.grid.toggle_cell(self.cursor_r, self.cursor_c)

        # Pattern cycling
        elif key == ord("p"):
            if self.pattern_idx is None:
                self.pattern_idx = 0
            else:
                self.pattern_idx = (self.pattern_idx - 1) % len(self.all_pattern_names)
        elif key == ord("n"):
            if self.pattern_idx is None:
                self.pattern_idx = 0
            else:
                self.pattern_idx = (self.pattern_idx + 1) % len(self.all_pattern_names)

        # Deselect pattern / deactivate brush
        elif key == 27:  # Escape
            if self.brush_active:
                self.brush_active = False
                self._set_message("Brush OFF")
            else:
                self.pattern_idx = None

        # Speed control
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()

        # Toroidal toggle
        elif key == ord("t"):
            self.grid.toroidal = not self.grid.toroidal
            mode = "ON" if self.grid.toroidal else "OFF"
            self._set_message(f"Toroidal wrapping {mode}")

        # History rewind / fast-forward
        elif key == ord(",") or key == ord("<"):
            self._history_rewind()
        elif key == ord(".") or key == ord(">"):
            self._history_forward()

        # Save / Load
        elif key == ord("w"):
            self._save()
        elif key == ord("o"):
            self._load()

        # Enter blueprint mode
        elif key == ord("b"):
            self._enter_blueprint()

        # Toggle dashboard
        elif key == ord("d"):
            self.dashboard = not self.dashboard
            state = "ON" if self.dashboard else "OFF"
            self._set_message(f"Pattern dashboard {state}")

        # Cycle ruleset forward
        elif key == ord("f"):
            self.rule_idx = (self.rule_idx + 1) % len(RULESETS)
            self._apply_ruleset()

        # Cycle ruleset backward
        elif key == ord("g"):
            self.rule_idx = (self.rule_idx - 1) % len(RULESETS)
            self._apply_ruleset()

        # Delete custom pattern
        elif key == ord("x"):
            self._delete_custom_pattern()

        # Brush: toggle painting with [V]
        elif key == ord("v"):
            self.brush_active = not self.brush_active
            if self.brush_active:
                self._brush_paint()  # paint at current position immediately
                self._set_message(f"Brush ON ({self._brush_label()}) — move to paint, [V] stop")
            else:
                self._set_message("Brush OFF")

        # Brush shape: cycle with [E]
        elif key == ord("e"):
            idx = self.BRUSH_SHAPES.index(self.brush_shape)
            self.brush_shape = self.BRUSH_SHAPES[(idx + 1) % len(self.BRUSH_SHAPES)]
            self._set_message(f"Brush shape: {self.brush_shape}")

        # Brush size with [z/Z] keys: z shrink, Z grow (shift+z)
        elif key == ord("z"):
            self.brush_size = max(1, self.brush_size - 1)
            self._set_message(f"Brush: {self._brush_label()}")
        elif key == ord("Z"):
            self.brush_size = min(5, self.brush_size + 1)
            self._set_message(f"Brush: {self._brush_label()}")

        # Resize
        elif key == curses.KEY_RESIZE:
            pass  # viewport recalculated each frame

        return True

    def _handle_blueprint_input(self, key: int) -> bool:
        """Handle input while in blueprint mode."""
        # Movement
        if key in (curses.KEY_UP, ord("k")):
            self.cursor_r = max(0, self.cursor_r - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor_r = min(self.grid.height - 1, self.cursor_r + 1)
        elif key in (curses.KEY_LEFT, ord("h")):
            self.cursor_c = max(0, self.cursor_c - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            self.cursor_c = min(self.grid.width - 1, self.cursor_c + 1)

        # Toggle cell in blueprint canvas
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            pos = (self.cursor_r, self.cursor_c)
            if pos in self.blueprint_cells:
                self.blueprint_cells.discard(pos)
            else:
                self.blueprint_cells.add(pos)

        # Mark selection corner
        elif key == ord("m"):
            if self.sel_corner1 is None:
                self.sel_corner1 = (self.cursor_r, self.cursor_c)
                self._set_message("Selection start marked — move to opposite corner and press [M] again")
            else:
                self.sel_corner2 = (self.cursor_r, self.cursor_c)
                r1 = min(self.sel_corner1[0], self.sel_corner2[0])
                r2 = max(self.sel_corner1[0], self.sel_corner2[0])
                c1 = min(self.sel_corner1[1], self.sel_corner2[1])
                c2 = max(self.sel_corner1[1], self.sel_corner2[1])
                count = sum(1 for (r, c) in self.blueprint_cells if r1 <= r <= r2 and c1 <= c <= c2)
                self._set_message(f"Region selected ({r2-r1+1}x{c2-c1+1}, {count} cells) — press [B] to save")

        # Select all drawn cells (no region marking needed)
        elif key == ord("a"):
            if self.blueprint_cells:
                min_r = min(r for r, c in self.blueprint_cells)
                max_r = max(r for r, c in self.blueprint_cells)
                min_c = min(c for r, c in self.blueprint_cells)
                max_c = max(c for r, c in self.blueprint_cells)
                self.sel_corner1 = (min_r, min_c)
                self.sel_corner2 = (max_r, max_c)
                self._set_message(f"All cells selected ({max_r-min_r+1}x{max_c-min_c+1}) — press [B] to save")
            else:
                self._set_message("No cells drawn yet")

        # Clear blueprint canvas
        elif key == ord("c"):
            self.blueprint_cells.clear()
            self.sel_corner1 = None
            self.sel_corner2 = None
            self._set_message("Blueprint cleared")

        # Save pattern and exit blueprint mode
        elif key == ord("b"):
            self._save_blueprint()

        # Cancel blueprint mode
        elif key == 27:  # Escape
            self.blueprint_mode = False
            self.blueprint_cells.clear()
            self.sel_corner1 = None
            self.sel_corner2 = None
            self._set_message("Blueprint mode cancelled")

        elif key == curses.KEY_RESIZE:
            pass

        return True

    # --- rule explorer ---

    def _apply_ruleset(self) -> None:
        """Apply the currently selected ruleset to the grid."""
        name, birth, survival = RULESETS[self.rule_idx]
        self.grid.birth = set(birth)
        self.grid.survival = set(survival)
        rs = rule_string(self.grid.birth, self.grid.survival)
        self._set_message(f"Rule: {name} ({rs})")

    # --- brush mode ---

    def _brush_offsets(self) -> list[tuple[int, int]]:
        """Return list of (dr, dc) offsets for current brush size and shape."""
        radius = self.brush_size - 1  # size 1 → radius 0 (single cell)
        offsets = []
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if self.brush_shape == "square":
                    offsets.append((dr, dc))
                elif self.brush_shape == "diamond":
                    if abs(dr) + abs(dc) <= radius:
                        offsets.append((dr, dc))
                elif self.brush_shape == "circle":
                    if dr * dr + dc * dc <= radius * radius:
                        offsets.append((dr, dc))
        return offsets

    def _brush_paint(self) -> None:
        """Paint cells at cursor position using current brush."""
        for dr, dc in self._brush_offsets():
            self.grid.set_cell(self.cursor_r + dr, self.cursor_c + dc)

    def _brush_label(self) -> str:
        """Return a short label describing the current brush."""
        dim = self.brush_size * 2 - 1
        return f"{dim}x{dim} {self.brush_shape}"

    # --- blueprint mode ---

    def _enter_blueprint(self) -> None:
        """Enter blueprint drawing mode."""
        self.running = False
        self.blueprint_mode = True
        self.blueprint_cells.clear()
        self.sel_corner1 = None
        self.sel_corner2 = None
        self._set_message("BLUEPRINT MODE — draw with [Enter], [M]ark corners, [A]ll, [B] save, [Esc] cancel")

    def _save_blueprint(self) -> None:
        """Extract selected cells, prompt for name, save to custom patterns."""
        # Determine which cells to save
        if self.sel_corner1 is not None and self.sel_corner2 is not None:
            r1 = min(self.sel_corner1[0], self.sel_corner2[0])
            r2 = max(self.sel_corner1[0], self.sel_corner2[0])
            c1 = min(self.sel_corner1[1], self.sel_corner2[1])
            c2 = max(self.sel_corner1[1], self.sel_corner2[1])
            selected = [(r, c) for r, c in self.blueprint_cells if r1 <= r <= r2 and c1 <= c <= c2]
        elif self.blueprint_cells:
            selected = list(self.blueprint_cells)
            r1 = min(r for r, c in selected)
            c1 = min(c for r, c in selected)
        else:
            self._set_message("No cells to save — draw some first!")
            return

        if not selected:
            self._set_message("No cells in selection region!")
            return

        # Normalize offsets relative to top-left of selection
        if self.sel_corner1 is not None:
            origin_r, origin_c = r1, c1
        else:
            origin_r = min(r for r, c in selected)
            origin_c = min(c for r, c in selected)
        offsets = sorted([(r - origin_r, c - origin_c) for r, c in selected])

        # Prompt for pattern name
        name = self._text_prompt("Pattern name: ")
        if not name:
            self._set_message("Save cancelled — no name given")
            return

        # Check for name conflict with built-in patterns
        if name in PATTERNS:
            self._set_message(f"Cannot overwrite built-in pattern '{name}'")
            return

        # Save to custom patterns
        custom = load_custom_patterns()
        custom[name] = offsets
        try:
            save_custom_patterns(custom)
        except OSError as e:
            self._set_message(f"Save error: {e}")
            return

        self._refresh_patterns()
        self.blueprint_mode = False
        self.blueprint_cells.clear()
        self.sel_corner1 = None
        self.sel_corner2 = None
        self._set_message(f"Saved pattern '{name}' ({len(offsets)} cells)")

    def _delete_custom_pattern(self) -> None:
        """Delete the currently selected custom pattern (if it's not built-in)."""
        if self.pattern_idx is None:
            self._set_message("No pattern selected — use [P/N] first")
            return
        name = self.all_pattern_names[self.pattern_idx]
        if name in PATTERNS:
            self._set_message(f"Cannot delete built-in pattern '{name}'")
            return
        custom = load_custom_patterns()
        if name not in custom:
            self._set_message(f"Pattern '{name}' not found in custom library")
            return
        custom.pop(name)
        try:
            save_custom_patterns(custom)
        except OSError as e:
            self._set_message(f"Delete error: {e}")
            return
        self._refresh_patterns()
        self.pattern_idx = min(self.pattern_idx, len(self.all_pattern_names) - 1)
        if not self.all_pattern_names:
            self.pattern_idx = None
        self._set_message(f"Deleted custom pattern '{name}'")

    def _text_prompt(self, prompt: str) -> str:
        """Show a text input prompt at the bottom of the screen. Returns entered text or empty string."""
        curses.curs_set(1)
        self.stdscr.nodelay(False)
        max_h, max_w = self.stdscr.getmaxyx()
        y = max_h - 1
        text = ""
        while True:
            try:
                self.stdscr.move(y, 0)
                self.stdscr.clrtoeol()
                display = (prompt + text)[:max_w - 2]
                self.stdscr.addstr(y, 0, display, curses.A_BOLD)
            except curses.error:
                pass
            self.stdscr.refresh()
            ch = self.stdscr.getch()
            if ch in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                break
            elif ch == 27:  # Escape — cancel
                text = ""
                break
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                text = text[:-1]
            elif 32 <= ch < 127:
                text += chr(ch)
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self._update_timeout()
        return text.strip()

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

        if self.blueprint_mode:
            self._draw_blueprint(max_h, max_w, grid_rows, grid_cols)
        else:
            self._draw_normal(max_h, max_w, grid_rows, grid_cols)

        self.stdscr.refresh()

    DASHBOARD_WIDTH = 22  # sidebar width in characters

    def _category_color_pair(self, pattern_name: str) -> int:
        """Return color pair for highlighting a detected pattern."""
        cat = self.detector.DEFINITIONS.get(pattern_name, ("still",))[0]
        return {
            "still": 8,
            "oscillator": 9,
            "spaceship": 10,
        }.get(cat, 8)

    def _draw_normal(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        # Run pattern detection if dashboard is visible
        sidebar_w = 0
        if self.dashboard:
            self.detected_counts, self.detected_highlights = self.detector.detect(
                self.grid.cells
            )
            sidebar_w = min(self.DASHBOARD_WIDTH, max_w // 3)
            grid_cols = max(1, (max_w - sidebar_w) // 2)

        # Build ghost preview set for pattern or brush
        ghost: set[tuple[int, int]] = set()
        if self.pattern_idx is not None:
            pat = self.all_patterns[self.all_pattern_names[self.pattern_idx]]
            for dr, dc in pat:
                ghost.add((self.cursor_r + dr, self.cursor_c + dc))
        elif self.brush_size > 1 or self.brush_active:
            # Show brush footprint preview
            for dr, dc in self._brush_offsets():
                br, bc = self.cursor_r + dr, self.cursor_c + dc
                if 0 <= br < self.grid.height and 0 <= bc < self.grid.width:
                    ghost.add((br, bc))

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
                if x + 1 >= max_w - sidebar_w:
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
                    if self.dashboard and self.use_color and (r, c) in self.detected_highlights:
                        # Highlight with category color
                        attr = curses.color_pair(
                            self._category_color_pair(self.detected_highlights[(r, c)])
                        ) | curses.A_BOLD
                    elif self.use_color:
                        age = self.grid.ages.get((r, c), 1)
                        attr = curses.color_pair(self._age_color_pair(age))
                    else:
                        attr = curses.A_BOLD
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

        # Draw dashboard sidebar
        if self.dashboard and sidebar_w > 2:
            self._draw_dashboard(max_h, max_w, grid_rows, sidebar_w)

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            state = "RUNNING" if self.running else "PAUSED"
            topo = "Torus" if self.grid.toroidal else "Bounded"
            hist_info = f"Hist: {len(self.history)}"
            if self.history_pos != -1:
                hist_info += f" @{self.history_pos}"
            sparkline = self._sparkline()
            spark_section = f" |{sparkline}|" if sparkline else ""
            rule_name, _, _ = RULESETS[self.rule_idx]
            rs = rule_string(self.grid.birth, self.grid.survival)
            rule_info = f"{rule_name} {rs}"
            brush_section = f" | Brush: {self._brush_label()}" if self.brush_active else ""
            status = (
                f" Gen: {self.generation} | Cells: {len(self.grid.cells)}{spark_section} | "
                f"Rule: {rule_info} | Speed: {self.speed} | {topo} | {hist_info} | {state}{brush_section} "
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
            pat_name = self.all_pattern_names[self.pattern_idx] if self.pattern_idx is not None else "None"
            custom_count = len(self.all_pattern_names) - len(PATTERNS)
            custom_tag = f" (+{custom_count} custom)" if custom_count > 0 else ""
            brush_state = "ON" if self.brush_active else "off"
            brush_info = f" [V]Brush:{brush_state} [z/Z]Size [E]Shape:{self.brush_shape}"
            help_text = (
                f" [Space]Run [S]tep [R]and [C]lear [Q]uit | "
                f"[P/N]Pat: {pat_name}{custom_tag} [Enter]Place [Esc]Desel |"
                f"{brush_info} | "
                f"[F/G]Rule [D]ash [B]lue [X]Del [+/-]Spd [T]orus [</>]Rew [W]Save [O]Load"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    def _draw_dashboard(self, max_h: int, max_w: int, grid_rows: int, sidebar_w: int) -> None:
        """Draw the pattern census sidebar on the right side of the screen."""
        sx = max_w - sidebar_w  # sidebar start x
        inner_w = sidebar_w - 2  # content width (minus borders)
        row = 0

        def put(y: int, text: str, attr: int = 0) -> None:
            if 0 <= y < grid_rows:
                line = text[:sidebar_w]
                try:
                    self.stdscr.addstr(y, sx, line, attr)
                except curses.error:
                    pass

        # Header
        header_attr = curses.color_pair(3) | curses.A_BOLD if self.use_color else curses.A_REVERSE
        put(row, " PATTERN CENSUS ".center(sidebar_w, "─"), header_attr)
        row += 1

        # Compute unclassified count
        classified = sum(self.detected_counts.values())
        total_cells = len(self.grid.cells)
        unclassified_cells = total_cells - len(self.detected_highlights)

        # Group by category
        cat_color = {"still": 8, "oscillator": 9, "spaceship": 10}
        for cat in PatternDetector.CATEGORIES:
            label = PatternDetector.CATEGORY_LABELS[cat]
            cat_attr = curses.color_pair(cat_color[cat]) | curses.A_BOLD if self.use_color else curses.A_BOLD
            if row < grid_rows:
                put(row, f"─{label}─".ljust(sidebar_w, "─"), cat_attr)
                row += 1

            found_any = False
            for name, (pcat, _) in PatternDetector.DEFINITIONS.items():
                if pcat != cat:
                    continue
                count = self.detected_counts.get(name, 0)
                if count > 0:
                    found_any = True
                    line = f" {name}: {count}"
                    text_attr = curses.color_pair(11) if self.use_color else 0
                    if row < grid_rows:
                        put(row, line.ljust(sidebar_w), text_attr)
                        row += 1

            if not found_any and row < grid_rows:
                dim = curses.A_DIM
                put(row, " (none)".ljust(sidebar_w), dim)
                row += 1

        # Separator and summary
        if row < grid_rows:
            put(row, "─" * sidebar_w, curses.A_DIM)
            row += 1
        if row < grid_rows:
            summary_attr = curses.color_pair(11) if self.use_color else 0
            put(row, f" Classified: {classified}".ljust(sidebar_w), summary_attr)
            row += 1
        if row < grid_rows:
            other_attr = curses.A_DIM
            put(row, f" Other cells: {unclassified_cells}".ljust(sidebar_w), other_attr)
            row += 1

    def _draw_blueprint(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the blueprint editing canvas."""
        # Compute selection bounds
        sel_r1 = sel_r2 = sel_c1 = sel_c2 = -1
        if self.sel_corner1 is not None and self.sel_corner2 is not None:
            sel_r1 = min(self.sel_corner1[0], self.sel_corner2[0])
            sel_r2 = max(self.sel_corner1[0], self.sel_corner2[0])
            sel_c1 = min(self.sel_corner1[1], self.sel_corner2[1])
            sel_c2 = max(self.sel_corner1[1], self.sel_corner2[1])

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

                is_drawn = (r, c) in self.blueprint_cells
                is_cursor = (r == self.cursor_r and c == self.cursor_c)
                in_sel = sel_r1 <= r <= sel_r2 and sel_c1 <= c <= sel_c2

                if is_cursor:
                    attr = curses.A_REVERSE
                    if self.use_color:
                        attr |= curses.color_pair(2)
                    ch = "██" if is_drawn else "▒▒"
                elif is_drawn:
                    if in_sel:
                        attr = curses.color_pair(1) | curses.A_BOLD if self.use_color else curses.A_BOLD
                    else:
                        attr = curses.color_pair(4) if self.use_color else curses.A_BOLD
                    ch = "██"
                elif in_sel:
                    attr = curses.color_pair(3) if self.use_color else curses.A_DIM
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
            sel_info = ""
            if self.sel_corner1 is not None and self.sel_corner2 is None:
                sel_info = f" | Sel: ({self.sel_corner1[0]},{self.sel_corner1[1]})->..."
            elif self.sel_corner1 is not None and self.sel_corner2 is not None:
                sel_info = f" | Sel: ({sel_r1},{sel_c1})-({sel_r2},{sel_c2})"
            status = (
                f" BLUEPRINT MODE | Cells drawn: {len(self.blueprint_cells)} | "
                f"Cursor: ({self.cursor_r},{self.cursor_c}){sel_info} "
            )
            if self.message_ttl > 0:
                status += f"| {self.message} "
                self.message_ttl -= 1
            attr = curses.color_pair(7) | curses.A_BOLD if self.use_color else curses.A_REVERSE
            try:
                self.stdscr.addstr(status_y, 0, status.ljust(max_w - 1)[:max_w - 1], attr)
            except curses.error:
                pass

        # Help bar
        help_y = max_h - 1
        if help_y > 0:
            help_text = (
                " [Enter]Toggle cell [M]ark corner [A]Select all [C]lear canvas "
                "[B]Save pattern [Esc]Cancel"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- history ---

    def _record_history(self) -> None:
        """Save current state to history before advancing."""
        # If we rewound and then resumed, truncate future entries
        if self.history_pos != -1:
            self.history = self.history[: self.history_pos + 1]
            self.history_pos = -1
        self.history.append((self.generation, frozenset(self.grid.cells), dict(self.grid.ages)))
        if len(self.history) > self.HISTORY_MAX:
            self.history.pop(0)

    def _history_rewind(self) -> None:
        """Step backward in history."""
        if not self.history:
            self._set_message("No history")
            return
        self.running = False
        if self.history_pos == -1:
            # Save current live state first
            self.history.append((self.generation, frozenset(self.grid.cells), dict(self.grid.ages)))
            if len(self.history) > self.HISTORY_MAX + 1:
                self.history.pop(0)
            self.history_pos = len(self.history) - 2
        elif self.history_pos > 0:
            self.history_pos -= 1
        else:
            self._set_message("At oldest recorded generation")
            return
        gen, cells, ages = self.history[self.history_pos]
        self.generation = gen
        self.grid.cells = set(cells)
        self.grid.ages = dict(ages)
        self._set_message(f"Rewind to gen {gen}")

    def _history_forward(self) -> None:
        """Step forward in history."""
        if self.history_pos == -1:
            self._set_message("Already at latest")
            return
        self.history_pos += 1
        if self.history_pos >= len(self.history):
            self.history_pos = -1
            self._set_message("Returned to live")
        else:
            gen, cells, ages = self.history[self.history_pos]
            self.generation = gen
            self.grid.cells = set(cells)
            self.grid.ages = dict(ages)
            if self.history_pos == len(self.history) - 1:
                self.history_pos = -1
                self._set_message("Returned to live")
            else:
                self._set_message(f"Forward to gen {gen}")

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

    def _record_population(self) -> None:
        """Record current population count for sparkline."""
        self.pop_history.append(len(self.grid.cells))
        if len(self.pop_history) > self.SPARKLINE_WIDTH:
            self.pop_history = self.pop_history[-self.SPARKLINE_WIDTH:]

    def _sparkline(self) -> str:
        """Return a Unicode sparkline string from population history."""
        if not self.pop_history:
            return ""
        bars = "▁▂▃▄▅▆▇█"
        values = self.pop_history[-self.SPARKLINE_WIDTH:]
        lo = min(values)
        hi = max(values)
        if hi == lo:
            return bars[3] * len(values)
        return "".join(bars[round((v - lo) / (hi - lo) * 7)] for v in values)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Cellular Automaton Sandbox — terminal simulator")
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

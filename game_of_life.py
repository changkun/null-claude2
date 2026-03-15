#!/usr/bin/env python3
"""Terminal-based cellular automaton simulator using curses."""

import argparse
import curses
import json
import os
import random
import math
import re
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
# RLE (Run Length Encoded) pattern parser
# ---------------------------------------------------------------------------

def parse_rle(text: str) -> tuple[list[tuple[int, int]], str, str | None]:
    """Parse an RLE-encoded pattern string.

    Returns (cells, name, rule) where cells is a list of (row, col) offsets,
    name is the pattern name (from #N header or "RLE pattern"), and rule is
    the rulestring if present (e.g. "B3/S23") or None.
    """
    name = "RLE pattern"
    rule_str: str | None = None
    body_lines: list[str] = []
    header_seen = False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Comment / metadata lines start with #
        if stripped.startswith("#"):
            tag = stripped[1:2]
            if tag == "N":
                name = stripped[2:].strip() or name
            continue
        # Header line: x = ..., y = ..., rule = ...
        if not header_seen and stripped.startswith("x"):
            header_seen = True
            rule_match = re.search(r"rule\s*=\s*(\S+)", stripped, re.IGNORECASE)
            if rule_match:
                rule_str = rule_match.group(1)
            continue
        # Body line (pattern data)
        body_lines.append(stripped)

    rle_data = "".join(body_lines)

    # Parse the run-length encoded body
    cells: list[tuple[int, int]] = []
    row, col = 0, 0
    i = 0
    while i < len(rle_data):
        ch = rle_data[i]
        if ch == "!":
            break
        # Read optional run count
        run = 0
        while i < len(rle_data) and rle_data[i].isdigit():
            run = run * 10 + int(rle_data[i])
            i += 1
        if run == 0:
            run = 1
        if i >= len(rle_data):
            break
        ch = rle_data[i]
        i += 1
        if ch == "b":
            # Dead cells — advance column
            col += run
        elif ch == "o":
            # Alive cells
            for _ in range(run):
                cells.append((row, col))
                col += 1
        elif ch == "$":
            # End of row(s)
            row += run
            col = 0
        # Skip any other characters (whitespace, etc.)

    return cells, name, rule_str


def load_rle_file(filepath: str) -> tuple[list[tuple[int, int]], str, str | None]:
    """Load and parse an RLE file from disk.

    Returns (cells, name, rule). Raises OSError on file errors,
    ValueError if the file contains no valid pattern data.
    """
    with open(filepath, "r") as f:
        text = f.read()
    cells, name, rule = parse_rle(text)
    if not cells:
        raise ValueError("No alive cells found in RLE data")
    return cells, name, rule


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
# Multi-state automata — Brian's Brain (3 states) and Wireworld (4 states)
# ---------------------------------------------------------------------------

# Automaton type names for cycling
MULTISTATE_TYPES = ["Life", "Brian's Brain", "Wireworld", "Langton's Ant"]

# Brian's Brain cell states
BB_OFF = 0
BB_ON = 1
BB_DYING = 2

# Wireworld cell states
WW_EMPTY = 0
WW_HEAD = 1
WW_TAIL = 2
WW_CONDUCTOR = 3

# Langton's Ant cell states
LA_WHITE = 0
LA_BLACK = 1
# Ant directions: 0=up, 1=right, 2=down, 3=left
LA_UP = 0
LA_RIGHT = 1
LA_DOWN = 2
LA_LEFT = 3
# Direction deltas: (dr, dc) for each direction
LA_DELTAS = {LA_UP: (-1, 0), LA_RIGHT: (0, 1), LA_DOWN: (1, 0), LA_LEFT: (0, -1)}


class MultiStateGrid:
    """Grid that supports multi-state cellular automata (Brian's Brain, Wireworld)."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # Each cell stores an int state; 0 = default/empty, absent = empty
        self.cells: dict[tuple[int, int], int] = {}
        self.toroidal = False
        self.ants: list[tuple[int, int, int]] = []

    def clear(self) -> None:
        self.cells.clear()
        self.ants.clear()

    def _neighbors(self, r: int, c: int):
        """Yield valid neighbor coordinates."""
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
                yield nr, nc

    def tick_brians_brain(self) -> None:
        """Advance one generation of Brian's Brain.

        Rules:
        - ON cells become DYING
        - DYING cells become OFF
        - OFF cells with exactly 2 ON neighbors become ON
        """
        new_cells: dict[tuple[int, int], int] = {}
        # Collect all positions to check (ON/DYING cells and their neighbors)
        candidates: set[tuple[int, int]] = set()
        for pos, state in self.cells.items():
            candidates.add(pos)
            if state == BB_ON:
                for nr, nc in self._neighbors(*pos):
                    candidates.add((nr, nc))

        for pos in candidates:
            state = self.cells.get(pos, BB_OFF)
            if state == BB_ON:
                new_cells[pos] = BB_DYING
            elif state == BB_DYING:
                pass  # becomes OFF (removed)
            else:
                # Count ON neighbors
                on_count = sum(
                    1 for nr, nc in self._neighbors(*pos)
                    if self.cells.get((nr, nc), BB_OFF) == BB_ON
                )
                if on_count == 2:
                    new_cells[pos] = BB_ON
        self.cells = new_cells

    def tick_wireworld(self) -> None:
        """Advance one generation of Wireworld.

        Rules:
        - EMPTY stays EMPTY
        - HEAD becomes TAIL
        - TAIL becomes CONDUCTOR
        - CONDUCTOR becomes HEAD if exactly 1 or 2 neighbors are HEAD, else stays CONDUCTOR
        """
        new_cells: dict[tuple[int, int], int] = {}
        for pos, state in self.cells.items():
            if state == WW_HEAD:
                new_cells[pos] = WW_TAIL
            elif state == WW_TAIL:
                new_cells[pos] = WW_CONDUCTOR
            elif state == WW_CONDUCTOR:
                head_count = sum(
                    1 for nr, nc in self._neighbors(*pos)
                    if self.cells.get((nr, nc), WW_EMPTY) == WW_HEAD
                )
                if head_count in (1, 2):
                    new_cells[pos] = WW_HEAD
                else:
                    new_cells[pos] = WW_CONDUCTOR
        self.cells = new_cells

    def randomize_brians_brain(self, density: float = 0.3) -> None:
        """Fill grid with random Brian's Brain cells."""
        self.cells.clear()
        for r in range(self.height):
            for c in range(self.width):
                if random.random() < density:
                    self.cells[(r, c)] = random.choice([BB_ON, BB_DYING])

    def randomize_wireworld(self) -> None:
        """Fill grid with a random Wireworld circuit.

        Creates random conductor paths with a few electron heads.
        """
        self.cells.clear()
        # Create random conductor paths
        for r in range(self.height):
            for c in range(self.width):
                if random.random() < 0.25:
                    self.cells[(r, c)] = WW_CONDUCTOR
        # Add some electron heads on conductors
        conductors = [pos for pos, s in self.cells.items() if s == WW_CONDUCTOR]
        num_heads = max(1, len(conductors) // 20)
        for pos in random.sample(conductors, min(num_heads, len(conductors))):
            self.cells[pos] = WW_HEAD

    def toggle_cell_brians_brain(self, r: int, c: int) -> None:
        """Cycle cell state: OFF -> ON -> DYING -> OFF."""
        pos = (r, c)
        state = self.cells.get(pos, BB_OFF)
        if state == BB_OFF:
            self.cells[pos] = BB_ON
        elif state == BB_ON:
            self.cells[pos] = BB_DYING
        else:
            del self.cells[pos]

    def toggle_cell_wireworld(self, r: int, c: int) -> None:
        """Cycle cell state: EMPTY -> CONDUCTOR -> HEAD -> TAIL -> EMPTY."""
        pos = (r, c)
        state = self.cells.get(pos, WW_EMPTY)
        if state == WW_EMPTY:
            self.cells[pos] = WW_CONDUCTOR
        elif state == WW_CONDUCTOR:
            self.cells[pos] = WW_HEAD
        elif state == WW_HEAD:
            self.cells[pos] = WW_TAIL
        else:
            del self.cells[pos]

    def from_life_grid(self, grid: "Grid", automaton_type: str) -> None:
        """Convert a standard 2-state Grid into multi-state cells."""
        self.cells.clear()
        self.width = grid.width
        self.height = grid.height
        self.toroidal = grid.toroidal
        if automaton_type == "Brian's Brain":
            for pos in grid.cells:
                self.cells[pos] = BB_ON
        elif automaton_type == "Wireworld":
            for pos in grid.cells:
                self.cells[pos] = WW_CONDUCTOR
            # Turn a few alive cells into electron heads to seed activity
            alive = list(grid.cells)
            num_heads = max(1, len(alive) // 10)
            for pos in random.sample(alive, min(num_heads, len(alive))):
                self.cells[pos] = WW_HEAD
        elif automaton_type == "Langton's Ant":
            # Convert alive cells to black, place one ant at center
            for pos in grid.cells:
                self.cells[pos] = LA_BLACK
            self.ants = [(self.height // 2, self.width // 2, LA_UP)]

    # --- Langton's Ant ---

    def tick_langtons_ant(self) -> None:
        """Advance one step of Langton's Ant.

        Rules for each ant:
        - On a white cell: turn 90° right, flip to black, move forward
        - On a black cell: turn 90° left, flip to white, move forward
        """
        if not hasattr(self, "ants"):
            self.ants = []
        new_ants = []
        for r, c, direction in self.ants:
            state = self.cells.get((r, c), LA_WHITE)
            if state == LA_WHITE:
                # Turn right
                new_dir = (direction + 1) % 4
                self.cells[(r, c)] = LA_BLACK
            else:
                # Turn left
                new_dir = (direction - 1) % 4
                # Flip to white (remove from dict)
                if (r, c) in self.cells:
                    del self.cells[(r, c)]
            # Move forward
            dr, dc = LA_DELTAS[new_dir]
            nr, nc = r + dr, c + dc
            if self.toroidal:
                nr %= self.height
                nc %= self.width
            elif not (0 <= nr < self.height and 0 <= nc < self.width):
                # Ant hits boundary, keep in place
                nr, nc = r, c
            new_ants.append((nr, nc, new_dir))
        self.ants = new_ants

    def randomize_langtons_ant(self, num_ants: int = 4) -> None:
        """Place multiple ants on a blank grid."""
        self.cells.clear()
        self.ants = []
        for _ in range(num_ants):
            r = random.randint(0, self.height - 1)
            c = random.randint(0, self.width - 1)
            direction = random.randint(0, 3)
            self.ants.append((r, c, direction))

    def toggle_cell_langtons_ant(self, r: int, c: int) -> None:
        """Cycle cell state: WHITE -> BLACK -> ANT -> WHITE.

        Placing an ant adds a new upward-facing ant at the position.
        """
        pos = (r, c)
        # Check if there's an ant here
        if hasattr(self, "ants"):
            for i, (ar, ac, ad) in enumerate(self.ants):
                if ar == r and ac == c:
                    # Remove ant, keep cell as-is
                    self.ants.pop(i)
                    return
        state = self.cells.get(pos, LA_WHITE)
        if state == LA_WHITE:
            self.cells[pos] = LA_BLACK
        elif state == LA_BLACK:
            # Place an ant here (on white cell)
            if (r, c) in self.cells:
                del self.cells[(r, c)]
            if not hasattr(self, "ants"):
                self.ants = []
            self.ants.append((r, c, LA_UP))
        else:
            if pos in self.cells:
                del self.cells[pos]


# ---------------------------------------------------------------------------
# Lenia — continuous cellular automaton
# ---------------------------------------------------------------------------

# Lenia preset species: each defines kernel and growth parameters
# Parameters: R (kernel radius), T (time step divisor),
#   kernel_mu, kernel_sigma (bell-curve kernel shape),
#   growth_mu, growth_sigma (growth function center and width)
LENIA_PRESETS = {
    "Orbium": {
        "R": 13, "T": 10,
        "kernel_mu": 0.5, "kernel_sigma": 0.15,
        "growth_mu": 0.15, "growth_sigma": 0.015,
    },
    "Geminium": {
        "R": 10, "T": 10,
        "kernel_mu": 0.5, "kernel_sigma": 0.15,
        "growth_mu": 0.14, "growth_sigma": 0.014,
    },
    "Hydrogeminium": {
        "R": 12, "T": 10,
        "kernel_mu": 0.5, "kernel_sigma": 0.15,
        "growth_mu": 0.16, "growth_sigma": 0.016,
    },
    "Smooth Life": {
        "R": 8, "T": 5,
        "kernel_mu": 0.5, "kernel_sigma": 0.20,
        "growth_mu": 0.26, "growth_sigma": 0.036,
    },
}

LENIA_PRESET_NAMES = list(LENIA_PRESETS.keys())

# Shade characters for rendering continuous values (5 levels)
LENIA_SHADES = " ░▒▓█"

# ---------------------------------------------------------------------------
# Falling Sand simulation — material types and physics
# ---------------------------------------------------------------------------

# Material constants
MAT_EMPTY = 0
MAT_SAND = 1
MAT_WATER = 2
MAT_FIRE = 3
MAT_STONE = 4
MAT_PLANT = 5

SAND_MATERIALS = ["Sand", "Water", "Fire", "Stone", "Plant"]
SAND_MATERIAL_IDS = [MAT_SAND, MAT_WATER, MAT_FIRE, MAT_STONE, MAT_PLANT]

# Display characters per material
SAND_CHARS = {
    MAT_SAND: "░░",
    MAT_WATER: "~~",
    MAT_FIRE: "▲▲",
    MAT_STONE: "██",
    MAT_PLANT: "♣♣",
}


class SandGrid:
    """Falling sand simulation with multiple material types and gravity physics.

    Materials: sand (falls, piles), water (flows, fills), fire (rises, ignites
    plants), stone (static), plant (grows slowly, burns).
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # 2D grid: each cell is a material constant
        self.cells: list[list[int]] = [[MAT_EMPTY] * width for _ in range(height)]

    def clear(self) -> None:
        for r in range(self.height):
            for c in range(self.width):
                self.cells[r][c] = MAT_EMPTY

    def get(self, r: int, c: int) -> int:
        if 0 <= r < self.height and 0 <= c < self.width:
            return self.cells[r][c]
        return -1  # out of bounds

    def set(self, r: int, c: int, mat: int) -> None:
        if 0 <= r < self.height and 0 <= c < self.width:
            self.cells[r][c] = mat

    def swap(self, r1: int, c1: int, r2: int, c2: int) -> None:
        self.cells[r1][c1], self.cells[r2][c2] = self.cells[r2][c2], self.cells[r1][c1]

    def count_material(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for r in range(self.height):
            for c in range(self.width):
                m = self.cells[r][c]
                if m != MAT_EMPTY:
                    counts[m] = counts.get(m, 0) + 1
        return counts

    def randomize(self) -> None:
        self.clear()
        for r in range(self.height):
            for c in range(self.width):
                if random.random() < 0.15:
                    self.cells[r][c] = random.choice(SAND_MATERIAL_IDS)

    def tick(self) -> None:
        """Advance one physics step. Process bottom-up for gravity."""
        w, h = self.width, self.height
        # Track which cells have been updated this tick to avoid double-moves
        updated = [[False] * w for _ in range(h)]

        # Process bottom-to-top so falling particles don't cascade in one tick
        for r in range(h - 2, -1, -1):
            # Randomize column order to avoid left-bias for water/fire spreading
            cols = list(range(w))
            random.shuffle(cols)
            for c in cols:
                if updated[r][c]:
                    continue
                mat = self.cells[r][c]
                if mat == MAT_EMPTY or mat == MAT_STONE:
                    continue

                if mat == MAT_SAND:
                    self._tick_sand(r, c, updated)
                elif mat == MAT_WATER:
                    self._tick_water(r, c, updated)
                elif mat == MAT_FIRE:
                    self._tick_fire(r, c, updated)
                elif mat == MAT_PLANT:
                    self._tick_plant(r, c, updated)

        # Fire on the bottom row fizzles out
        for c in range(w):
            if self.cells[h - 1][c] == MAT_FIRE:
                if random.random() < 0.3:
                    self.cells[h - 1][c] = MAT_EMPTY

    def _tick_sand(self, r: int, c: int, updated: list[list[bool]]) -> None:
        """Sand: falls down; if blocked, slides diagonally; displaces water."""
        below = self.get(r + 1, c)
        if below == MAT_EMPTY:
            self.swap(r, c, r + 1, c)
            updated[r + 1][c] = True
        elif below == MAT_WATER:
            # Sand sinks through water
            self.swap(r, c, r + 1, c)
            updated[r + 1][c] = True
        else:
            # Try diagonal
            dirs = [(-1, 1), (1, 1)]  # (dc, dr_offset=+1)
            random.shuffle(dirs)
            for dc, _ in dirs:
                nc = c + dc
                diag = self.get(r + 1, nc)
                if diag == MAT_EMPTY:
                    self.swap(r, c, r + 1, nc)
                    updated[r + 1][nc] = True
                    return
                elif diag == MAT_WATER:
                    self.swap(r, c, r + 1, nc)
                    updated[r + 1][nc] = True
                    return

    def _tick_water(self, r: int, c: int, updated: list[list[bool]]) -> None:
        """Water: falls down, then spreads horizontally."""
        below = self.get(r + 1, c)
        if below == MAT_EMPTY:
            self.swap(r, c, r + 1, c)
            updated[r + 1][c] = True
        else:
            # Try diagonal down
            dirs = [(-1, 1), (1, 1)]
            random.shuffle(dirs)
            moved = False
            for dc, _ in dirs:
                nc = c + dc
                diag = self.get(r + 1, nc)
                if diag == MAT_EMPTY:
                    self.swap(r, c, r + 1, nc)
                    updated[r + 1][nc] = True
                    moved = True
                    break
            if not moved:
                # Spread horizontally
                dirs2 = [-1, 1]
                random.shuffle(dirs2)
                for dc in dirs2:
                    nc = c + dc
                    side = self.get(r, nc)
                    if side == MAT_EMPTY and not updated[r][nc]:
                        self.swap(r, c, r, nc)
                        updated[r][nc] = True
                        break

    def _tick_fire(self, r: int, c: int, updated: list[list[bool]]) -> None:
        """Fire: rises upward, spreads to adjacent plants, fizzles randomly."""
        # Fire has a chance to die out
        if random.random() < 0.08:
            self.cells[r][c] = MAT_EMPTY
            return

        # Ignite adjacent plants
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = r + dr, c + dc
                if self.get(nr, nc) == MAT_PLANT:
                    if random.random() < 0.4:
                        self.cells[nr][nc] = MAT_FIRE
                        updated[nr][nc] = True

        # Rise upward
        above = self.get(r - 1, c)
        if above == MAT_EMPTY:
            self.swap(r, c, r - 1, c)
            updated[r - 1][c] = True
        else:
            # Try diagonal up
            dirs = [-1, 1]
            random.shuffle(dirs)
            for dc in dirs:
                nc = c + dc
                if self.get(r - 1, nc) == MAT_EMPTY:
                    self.swap(r, c, r - 1, nc)
                    updated[r - 1][nc] = True
                    return
            # Fire trapped: more likely to die
            if random.random() < 0.2:
                self.cells[r][c] = MAT_EMPTY

    def _tick_plant(self, r: int, c: int, updated: list[list[bool]]) -> None:
        """Plant: slowly grows into adjacent empty cells."""
        if random.random() < 0.005:
            dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]
            random.shuffle(dirs)
            for dr, dc in dirs:
                nr, nc = r + dr, c + dc
                if self.get(nr, nc) == MAT_EMPTY and not updated[nr][nc]:
                    self.cells[nr][nc] = MAT_PLANT
                    updated[nr][nc] = True
                    return


# ---------------------------------------------------------------------------
# Reaction-Diffusion (Gray-Scott model) — presets and grid
# ---------------------------------------------------------------------------

# Gray-Scott presets: (feed_rate, kill_rate) — each produces distinct patterns
RD_PRESETS = {
    "Mitosis": {"f": 0.0367, "k": 0.0649},    # self-replicating spots
    "Coral": {"f": 0.0545, "k": 0.062},        # coral-like branching growth
    "Maze": {"f": 0.029, "k": 0.057},          # labyrinthine stripes
    "Solitons": {"f": 0.03, "k": 0.06},        # stable moving spots
    "Worms": {"f": 0.078, "k": 0.061},         # long worm-like structures
    "Bubbles": {"f": 0.012, "k": 0.05},        # expanding rings / bubbles
    "Waves": {"f": 0.014, "k": 0.054},         # pulsating wave patterns
}

RD_PRESET_NAMES = list(RD_PRESETS.keys())

# Shade characters for rendering chemical U concentration (5 levels)
RD_SHADES = " ░▒▓█"


class ReactionDiffusionGrid:
    """Gray-Scott reaction-diffusion model.

    Two chemicals U and V diffuse across a 2D grid and react:
        U + 2V → 3V   (autocatalytic conversion)
        V → P          (V decays to inert product)

    Parameters:
        Du, Dv  — diffusion rates for U and V
        f       — feed rate (replenishes U, removes V)
        k       — kill rate (removes V)

    The interplay of diffusion, reaction, feed, and kill produces
    Turing patterns: spots, stripes, spirals, and more.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # U starts at 1.0 everywhere, V starts at 0.0
        self.U: list[list[float]] = [[1.0] * width for _ in range(height)]
        self.V: list[list[float]] = [[0.0] * width for _ in range(height)]
        self.toroidal = True
        # Diffusion rates
        self.Du = 0.21
        self.Dv = 0.105
        # Reaction parameters (default: Mitosis)
        preset = RD_PRESETS["Mitosis"]
        self.f = preset["f"]
        self.k = preset["k"]
        # Time step (multiple sub-steps per visible tick for stability)
        self.dt = 1.0
        self.substeps = 4

    def apply_preset(self, name: str) -> None:
        """Switch to a named Gray-Scott preset."""
        if name in RD_PRESETS:
            p = RD_PRESETS[name]
            self.f = p["f"]
            self.k = p["k"]

    def clear(self) -> None:
        """Reset to uniform U=1, V=0."""
        for r in range(self.height):
            for c in range(self.width):
                self.U[r][c] = 1.0
                self.V[r][c] = 0.0

    def seed_center(self) -> None:
        """Place a square seed of V in the center with small perturbations."""
        self.clear()
        cx, cy = self.width // 2, self.height // 2
        radius = max(3, min(self.width, self.height) // 10)
        for r in range(max(0, cy - radius), min(self.height, cy + radius + 1)):
            for c in range(max(0, cx - radius), min(self.width, cx + radius + 1)):
                self.U[r][c] = 0.5 + random.uniform(-0.01, 0.01)
                self.V[r][c] = 0.25 + random.uniform(-0.01, 0.01)

    def seed_random_spots(self) -> None:
        """Place several random seed spots of V across the grid."""
        self.clear()
        num_spots = max(3, (self.width * self.height) // 600)
        for _ in range(num_spots):
            cr = random.randint(0, self.height - 1)
            cc = random.randint(0, self.width - 1)
            spot_r = random.randint(2, 4)
            for r in range(max(0, cr - spot_r), min(self.height, cr + spot_r + 1)):
                for c in range(max(0, cc - spot_r), min(self.width, cc + spot_r + 1)):
                    self.U[r][c] = 0.5 + random.uniform(-0.01, 0.01)
                    self.V[r][c] = 0.25 + random.uniform(-0.01, 0.01)

    def _laplacian(self, grid: list[list[float]], r: int, c: int) -> float:
        """Compute discrete Laplacian at (r, c) using a 5-point stencil."""
        h, w = self.height, self.width
        if self.toroidal:
            up = grid[(r - 1) % h][c]
            dn = grid[(r + 1) % h][c]
            lt = grid[r][(c - 1) % w]
            rt = grid[r][(c + 1) % w]
        else:
            up = grid[r - 1][c] if r > 0 else grid[r][c]
            dn = grid[r + 1][c] if r < h - 1 else grid[r][c]
            lt = grid[r][c - 1] if c > 0 else grid[r][c]
            rt = grid[r][c + 1] if c < w - 1 else grid[r][c]
        return up + dn + lt + rt - 4.0 * grid[r][c]

    def tick(self) -> None:
        """Advance one visible time step (multiple sub-steps for stability)."""
        dt = self.dt / self.substeps
        for _ in range(self.substeps):
            newU = [[0.0] * self.width for _ in range(self.height)]
            newV = [[0.0] * self.width for _ in range(self.height)]
            for r in range(self.height):
                for c in range(self.width):
                    u = self.U[r][c]
                    v = self.V[r][c]
                    lapU = self._laplacian(self.U, r, c)
                    lapV = self._laplacian(self.V, r, c)
                    uvv = u * v * v
                    nu = u + dt * (self.Du * lapU - uvv + self.f * (1.0 - u))
                    nv = v + dt * (self.Dv * lapV + uvv - (self.f + self.k) * v)
                    newU[r][c] = max(0.0, min(1.0, nu))
                    newV[r][c] = max(0.0, min(1.0, nv))
            self.U = newU
            self.V = newV

    def population(self) -> float:
        """Total V chemical concentration (mass)."""
        total = 0.0
        for r in range(self.height):
            for c in range(self.width):
                total += self.V[r][c]
        return total

    def active_count(self) -> int:
        """Number of cells where V > 0.01."""
        count = 0
        for r in range(self.height):
            for c in range(self.width):
                if self.V[r][c] > 0.01:
                    count += 1
        return count


# ---------------------------------------------------------------------------
# Wa-Tor Ecosystem — predator-prey simulation
# ---------------------------------------------------------------------------

# Cell states
WATOR_EMPTY = 0
WATOR_FISH = 1
WATOR_SHARK = 2

# Display characters
WATOR_CHARS = {WATOR_EMPTY: " ", WATOR_FISH: ".", WATOR_SHARK: "#"}


class WaTorWorld:
    """Wa-Tor predator-prey ecosystem simulation.

    A toroidal ocean grid populated by fish and sharks.
    Fish breed after a set number of turns.  Sharks eat adjacent fish to
    gain energy and starve if they cannot feed.  The result is emergent
    Lotka-Volterra population oscillations visible in real-time.
    """

    def __init__(self, width: int, height: int,
                 fish_breed: int = 3, shark_breed: int = 8,
                 shark_starve: int = 4, initial_fish: int = 0,
                 initial_sharks: int = 0):
        self.width = width
        self.height = height
        self.fish_breed = fish_breed
        self.shark_breed = shark_breed
        self.shark_starve = shark_starve

        # Grid stores cell type (EMPTY / FISH / SHARK)
        self.grid: list[list[int]] = [[WATOR_EMPTY] * width for _ in range(height)]
        # Age grid — turns survived (used for breeding)
        self.age: list[list[int]] = [[0] * width for _ in range(height)]
        # Energy grid — only meaningful for sharks
        self.energy: list[list[int]] = [[0] * width for _ in range(height)]

        # Population history for graphing
        self.fish_history: list[int] = []
        self.shark_history: list[int] = []

        self.seed(initial_fish, initial_sharks)

    def seed(self, n_fish: int = 0, n_sharks: int = 0) -> None:
        """Populate the grid randomly with fish and sharks."""
        w, h = self.width, self.height
        total = w * h
        if n_fish == 0:
            n_fish = total // 4
        if n_sharks == 0:
            n_sharks = total // 16

        # Clear
        for r in range(h):
            for c in range(w):
                self.grid[r][c] = WATOR_EMPTY
                self.age[r][c] = 0
                self.energy[r][c] = 0

        positions = list(range(total))
        random.shuffle(positions)

        for i in range(min(n_fish, total)):
            r, c = divmod(positions[i], w)
            self.grid[r][c] = WATOR_FISH
            self.age[r][c] = random.randint(0, self.fish_breed - 1)

        offset = min(n_fish, total)
        for i in range(min(n_sharks, total - offset)):
            r, c = divmod(positions[offset + i], w)
            self.grid[r][c] = WATOR_SHARK
            self.age[r][c] = random.randint(0, self.shark_breed - 1)
            self.energy[r][c] = self.shark_starve

        self.fish_history.clear()
        self.shark_history.clear()

    def _neighbors(self, r: int, c: int) -> list[tuple[int, int]]:
        """Return the four toroidal neighbors in random order."""
        ns = [
            ((r - 1) % self.height, c),
            ((r + 1) % self.height, c),
            (r, (c - 1) % self.width),
            (r, (c + 1) % self.width),
        ]
        random.shuffle(ns)
        return ns

    def tick(self) -> None:
        """Advance the simulation by one chronon (time step)."""
        w, h = self.width, self.height
        moved: list[list[bool]] = [[False] * w for _ in range(h)]

        # Process sharks first (they eat fish)
        for r in range(h):
            for c in range(w):
                if self.grid[r][c] != WATOR_SHARK or moved[r][c]:
                    continue
                self.age[r][c] += 1
                self.energy[r][c] -= 1

                # Starve?
                if self.energy[r][c] <= 0:
                    self.grid[r][c] = WATOR_EMPTY
                    self.age[r][c] = 0
                    self.energy[r][c] = 0
                    continue

                # Look for adjacent fish to eat
                neighbors = self._neighbors(r, c)
                fish_n = [n for n in neighbors if self.grid[n[0]][n[1]] == WATOR_FISH]
                empty_n = [n for n in neighbors if self.grid[n[0]][n[1]] == WATOR_EMPTY]

                if fish_n:
                    nr, nc = fish_n[0]
                    # Eat the fish
                    self.energy[r][c] += self.shark_starve  # regain energy
                    # Move to fish cell
                    self.grid[nr][nc] = WATOR_SHARK
                    self.age[nr][nc] = self.age[r][c]
                    self.energy[nr][nc] = self.energy[r][c]
                    moved[nr][nc] = True
                    # Breed?
                    if self.age[r][c] >= self.shark_breed:
                        self.grid[r][c] = WATOR_SHARK
                        self.age[r][c] = 0
                        self.energy[r][c] = self.shark_starve
                        self.age[nr][nc] = 0
                    else:
                        self.grid[r][c] = WATOR_EMPTY
                        self.age[r][c] = 0
                        self.energy[r][c] = 0
                elif empty_n:
                    nr, nc = empty_n[0]
                    self.grid[nr][nc] = WATOR_SHARK
                    self.age[nr][nc] = self.age[r][c]
                    self.energy[nr][nc] = self.energy[r][c]
                    moved[nr][nc] = True
                    if self.age[r][c] >= self.shark_breed:
                        self.grid[r][c] = WATOR_SHARK
                        self.age[r][c] = 0
                        self.energy[r][c] = self.shark_starve
                        self.age[nr][nc] = 0
                    else:
                        self.grid[r][c] = WATOR_EMPTY
                        self.age[r][c] = 0
                        self.energy[r][c] = 0

        # Process fish
        for r in range(h):
            for c in range(w):
                if self.grid[r][c] != WATOR_FISH or moved[r][c]:
                    continue
                self.age[r][c] += 1
                neighbors = self._neighbors(r, c)
                empty_n = [n for n in neighbors if self.grid[n[0]][n[1]] == WATOR_EMPTY]

                if empty_n:
                    nr, nc = empty_n[0]
                    self.grid[nr][nc] = WATOR_FISH
                    self.age[nr][nc] = self.age[r][c]
                    moved[nr][nc] = True
                    if self.age[r][c] >= self.fish_breed:
                        # Breed — leave a new fish behind
                        self.grid[r][c] = WATOR_FISH
                        self.age[r][c] = 0
                        self.age[nr][nc] = 0
                    else:
                        self.grid[r][c] = WATOR_EMPTY
                        self.age[r][c] = 0

        # Record population
        fish_count = 0
        shark_count = 0
        for r in range(h):
            for c in range(w):
                if self.grid[r][c] == WATOR_FISH:
                    fish_count += 1
                elif self.grid[r][c] == WATOR_SHARK:
                    shark_count += 1
        self.fish_history.append(fish_count)
        self.shark_history.append(shark_count)
        # Keep history bounded
        max_hist = 200
        if len(self.fish_history) > max_hist:
            self.fish_history = self.fish_history[-max_hist:]
            self.shark_history = self.shark_history[-max_hist:]

    def population(self) -> tuple[int, int]:
        """Return (fish_count, shark_count)."""
        fish = shark = 0
        for r in range(self.height):
            for c in range(self.width):
                if self.grid[r][c] == WATOR_FISH:
                    fish += 1
                elif self.grid[r][c] == WATOR_SHARK:
                    shark += 1
        return fish, shark


# ---------------------------------------------------------------------------
# Particle Life — continuous-space particle simulation
# ---------------------------------------------------------------------------

# Number of particle types (colors)
PL_NUM_TYPES = 6

# Particle type color names (for display)
PL_TYPE_NAMES = ["Red", "Green", "Blue", "Yellow", "Cyan", "Magenta"]

# Shade characters for rendering particles
PL_SHADES = "●"


class ParticleLifeWorld:
    """Continuous-space particle life simulation.

    Particles of different color types attract or repel each other based on
    a randomized interaction matrix.  Despite trivially simple rules, this
    produces stunning emergent behaviors — clusters, orbits, chains, and
    cell-like structures that look remarkably alive.

    Each particle has continuous (x, y) position and (vx, vy) velocity.
    Forces between particles follow a piecewise-linear profile that is
    repulsive at very short range and attractive (or repulsive, depending
    on the matrix entry) at medium range, tapering to zero at ``rmax``.
    """

    def __init__(self, width: float, height: float, n_particles: int = 300):
        self.width = width
        self.height = height
        self.n_particles = n_particles
        self.num_types = PL_NUM_TYPES
        self.friction = 0.05        # velocity damping per tick
        self.dt = 0.02              # integration time step
        self.rmax = 80.0            # max interaction radius (in pixel units)
        self.force_scale = 5.0      # global force multiplier
        self.beta = 0.3             # repulsion distance as fraction of rmax

        # Particle state arrays
        self.px: list[float] = []   # x positions
        self.py: list[float] = []   # y positions
        self.vx: list[float] = []   # x velocities
        self.vy: list[float] = []   # y velocities
        self.pt: list[int] = []     # type indices

        # Interaction matrix: attraction[i][j] = force of type j on type i
        # Values in [-1, 1]; positive = attract, negative = repel
        self.attraction: list[list[float]] = []

        self.randomize_matrix()
        self.seed_random()

    def randomize_matrix(self) -> None:
        """Generate a new random interaction matrix."""
        self.attraction = [
            [random.uniform(-1.0, 1.0) for _ in range(self.num_types)]
            for _ in range(self.num_types)
        ]

    def seed_random(self) -> None:
        """Place particles randomly across the world."""
        self.px = [random.uniform(0, self.width) for _ in range(self.n_particles)]
        self.py = [random.uniform(0, self.height) for _ in range(self.n_particles)]
        self.vx = [0.0] * self.n_particles
        self.vy = [0.0] * self.n_particles
        self.pt = [random.randint(0, self.num_types - 1) for _ in range(self.n_particles)]

    def _force(self, r: float, a: float) -> float:
        """Compute force magnitude at distance r with attraction a.

        Piecewise-linear force profile:
        - [0, beta*rmax]: repulsion (universal, pushes apart at close range)
        - [beta*rmax, rmax]: attraction or repulsion per matrix entry
        - [rmax, inf]: zero (no interaction)
        """
        beta = self.beta
        if r < beta * self.rmax:
            # Short-range repulsion: linearly from -1 at r=0 to 0 at r=beta*rmax
            return r / (beta * self.rmax) - 1.0
        elif r < self.rmax:
            # Medium range: linearly ramp from 0 to a and back to 0
            numer = r - beta * self.rmax
            denom = self.rmax - beta * self.rmax
            if denom < 1e-9:
                return 0.0
            t = numer / denom
            # Triangular profile peaking at a in the middle
            if t < 0.5:
                return a * (2.0 * t)
            else:
                return a * (2.0 - 2.0 * t)
        return 0.0

    def tick(self) -> None:
        """Advance the simulation by one time step."""
        n = self.n_particles
        w = self.width
        h = self.height
        rmax = self.rmax
        rmax2 = rmax * rmax
        dt = self.dt
        fscale = self.force_scale
        friction = self.friction

        # Compute forces
        fx = [0.0] * n
        fy = [0.0] * n

        for i in range(n):
            xi, yi, ti = self.px[i], self.py[i], self.pt[i]
            total_fx = 0.0
            total_fy = 0.0
            for j in range(n):
                if i == j:
                    continue
                dx = self.px[j] - xi
                dy = self.py[j] - yi
                # Toroidal wrapping for distance
                if dx > w * 0.5:
                    dx -= w
                elif dx < -w * 0.5:
                    dx += w
                if dy > h * 0.5:
                    dy -= h
                elif dy < -h * 0.5:
                    dy += h
                r2 = dx * dx + dy * dy
                if r2 > rmax2 or r2 < 1e-6:
                    continue
                r = math.sqrt(r2)
                a = self.attraction[ti][self.pt[j]]
                f = self._force(r, a) * fscale
                total_fx += f * dx / r
                total_fy += f * dy / r
            fx[i] = total_fx
            fy[i] = total_fy

        # Integrate velocities and positions
        for i in range(n):
            self.vx[i] = self.vx[i] * (1.0 - friction) + fx[i] * dt
            self.vy[i] = self.vy[i] * (1.0 - friction) + fy[i] * dt
            self.px[i] += self.vx[i] * dt
            self.py[i] += self.vy[i] * dt
            # Wrap around (toroidal)
            self.px[i] %= w
            self.py[i] %= h

    def population_by_type(self) -> list[int]:
        """Count particles per type."""
        counts = [0] * self.num_types
        for t in self.pt:
            counts[t] += 1
        return counts


class LeniaGrid:
    """Continuous-state cellular automaton grid (Lenia).

    Cell values are floats in [0.0, 1.0]. The kernel and growth function
    are parameterized bell curves, producing smooth, organic dynamics.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        # 2D grid of floats [0.0, 1.0]
        self.cells: list[list[float]] = [[0.0] * width for _ in range(height)]
        self.toroidal = True
        # Default to Orbium parameters
        self._set_params(LENIA_PRESETS["Orbium"])
        # Precomputed kernel (ring of weights)
        self._kernel: list[tuple[int, int, float]] = []
        self._kernel_sum = 0.0
        self._build_kernel()

    def _set_params(self, params: dict) -> None:
        """Apply a preset's parameters."""
        self.R = params["R"]
        self.T = params["T"]
        self.kernel_mu = params["kernel_mu"]
        self.kernel_sigma = params["kernel_sigma"]
        self.growth_mu = params["growth_mu"]
        self.growth_sigma = params["growth_sigma"]

    def _bell(self, x: float, mu: float, sigma: float) -> float:
        """Gaussian bell curve."""
        return math.exp(-((x - mu) ** 2) / (2.0 * sigma * sigma))

    def _build_kernel(self) -> None:
        """Build the convolution kernel as a list of (dr, dc, weight) tuples."""
        self._kernel = []
        self._kernel_sum = 0.0
        R = self.R
        for dr in range(-R, R + 1):
            for dc in range(-R, R + 1):
                dist = math.sqrt(dr * dr + dc * dc) / R
                if 0.0 < dist <= 1.0:
                    w = self._bell(dist, self.kernel_mu, self.kernel_sigma)
                    self._kernel.append((dr, dc, w))
                    self._kernel_sum += w

    def apply_preset(self, name: str) -> None:
        """Switch to a named Lenia preset species."""
        if name in LENIA_PRESETS:
            self._set_params(LENIA_PRESETS[name])
            self._build_kernel()

    def clear(self) -> None:
        """Set all cells to 0."""
        for r in range(self.height):
            for c in range(self.width):
                self.cells[r][c] = 0.0

    def seed_center(self) -> None:
        """Place a circular seed blob in the center of the grid."""
        cx, cy = self.width // 2, self.height // 2
        radius = max(3, self.R)
        for r in range(self.height):
            for c in range(self.width):
                dr = r - cy
                dc = c - cx
                dist = math.sqrt(dr * dr + dc * dc)
                if dist < radius:
                    # Smooth falloff from center
                    self.cells[r][c] = max(0.0, 1.0 - (dist / radius) ** 2)

    def randomize(self, density: float = 0.2) -> None:
        """Fill grid with random continuous values in scattered patches."""
        self.clear()
        # Create several random blobs
        num_blobs = max(3, (self.width * self.height) // 400)
        for _ in range(num_blobs):
            cr = random.randint(0, self.height - 1)
            cc = random.randint(0, self.width - 1)
            blob_r = random.randint(2, max(3, self.R))
            for r in range(max(0, cr - blob_r), min(self.height, cr + blob_r + 1)):
                for c in range(max(0, cc - blob_r), min(self.width, cc + blob_r + 1)):
                    dr = r - cr
                    dc = c - cc
                    dist = math.sqrt(dr * dr + dc * dc)
                    if dist < blob_r and random.random() < density * 3:
                        self.cells[r][c] = min(1.0, self.cells[r][c] + random.random() * 0.8)

    def tick(self) -> None:
        """Advance one Lenia time step."""
        if self._kernel_sum <= 0:
            return
        new = [[0.0] * self.width for _ in range(self.height)]
        dt = 1.0 / self.T
        for r in range(self.height):
            for c in range(self.width):
                # Compute neighborhood potential (weighted average)
                potential = 0.0
                for dr, dc, w in self._kernel:
                    if self.toroidal:
                        nr = (r + dr) % self.height
                        nc = (c + dc) % self.width
                    else:
                        nr = r + dr
                        nc = c + dc
                        if nr < 0 or nr >= self.height or nc < 0 or nc >= self.width:
                            continue
                    potential += self.cells[nr][nc] * w
                potential /= self._kernel_sum
                # Growth function
                growth = 2.0 * self._bell(potential, self.growth_mu, self.growth_sigma) - 1.0
                # Update with time step
                new[r][c] = max(0.0, min(1.0, self.cells[r][c] + dt * growth))
        self.cells = new

    def population(self) -> float:
        """Return total mass (sum of all cell values)."""
        return sum(self.cells[r][c] for r in range(self.height) for c in range(self.width))

    def active_count(self) -> int:
        """Return number of cells with value > 0.01."""
        return sum(1 for r in range(self.height) for c in range(self.width) if self.cells[r][c] > 0.01)


# ---------------------------------------------------------------------------
# Physarum (slime mold) simulation
# ---------------------------------------------------------------------------

# Preset configurations: (sensor_angle, sensor_distance, turn_angle, deposit, decay, diffuse_k)
PHYSARUM_PRESETS = {
    "network": (math.pi / 4, 9.0, math.pi / 4, 5.0, 0.1, 0.9),
    "ring": (math.pi / 8, 15.0, math.pi / 4, 3.0, 0.05, 0.95),
    "maze-solver": (math.pi / 3, 5.0, math.pi / 6, 8.0, 0.15, 0.85),
    "tendrils": (math.pi / 6, 12.0, math.pi / 3, 4.0, 0.08, 0.92),
    "dense": (math.pi / 2, 7.0, math.pi / 2, 6.0, 0.12, 0.88),
}
PHYSARUM_PRESET_NAMES = list(PHYSARUM_PRESETS.keys())

# Graded trail rendering characters (low → high concentration)
PHYSARUM_SHADES = " .·:░▒▓█"


class PhysarumWorld:
    """Physarum polycephalum (slime mold) agent-based simulation.

    Thousands of simple agents move, sense chemical trails, and deposit
    pheromones — producing stunning emergent network structures that
    resemble veins, transit maps, and neural pathways.

    Each agent has a position and heading.  On every tick it:
      1. Senses the trail map at three forward positions (left, center, right)
      2. Rotates toward the strongest signal
      3. Moves one step forward
      4. Deposits pheromone at its new position

    The trail map then diffuses and decays, producing smooth gradients
    that guide subsequent agent movement (stigmergy).
    """

    def __init__(self, width: int, height: int, n_agents: int = 0,
                 preset: str = "network"):
        self.width = width
        self.height = height
        # Default agent count scales with grid size
        self.n_agents = n_agents if n_agents > 0 else max(500, width * height // 4)
        self.preset_idx = PHYSARUM_PRESET_NAMES.index(preset)

        # Agent state: position (continuous), heading (radians)
        self.ax: list[float] = []
        self.ay: list[float] = []
        self.ah: list[float] = []  # heading in radians

        # Trail map (continuous values, same resolution as display)
        self.trail: list[list[float]] = [[0.0] * width for _ in range(height)]

        # Apply preset parameters
        self._apply_preset(preset)
        self.seed()

    def _apply_preset(self, name: str) -> None:
        """Load parameters from a named preset."""
        sa, sd, ta, dep, dec, dk = PHYSARUM_PRESETS[name]
        self.sensor_angle = sa       # angle offset of left/right sensors
        self.sensor_dist = sd        # distance of sensor from agent
        self.turn_angle = ta         # rotation step when turning
        self.deposit_amount = dep    # pheromone deposited per step
        self.decay_rate = dec        # fraction of trail lost per tick
        self.diffuse_k = dk          # diffusion kernel weight (0-1)
        self.step_size = 1.0         # movement speed per tick

    def seed(self) -> None:
        """Place agents randomly across the world."""
        self.ax = [random.uniform(0, self.width - 1) for _ in range(self.n_agents)]
        self.ay = [random.uniform(0, self.height - 1) for _ in range(self.n_agents)]
        self.ah = [random.uniform(0, 2 * math.pi) for _ in range(self.n_agents)]
        # Clear trail
        self.trail = [[0.0] * self.width for _ in range(self.height)]

    def seed_ring(self) -> None:
        """Place agents in a ring formation pointing inward."""
        cx, cy = self.width / 2, self.height / 2
        radius = min(cx, cy) * 0.7
        self.ax = []
        self.ay = []
        self.ah = []
        for i in range(self.n_agents):
            angle = 2 * math.pi * i / self.n_agents
            x = cx + radius * math.cos(angle)
            y = cy + radius * math.sin(angle)
            self.ax.append(x % self.width)
            self.ay.append(y % self.height)
            # Point inward (toward center)
            self.ah.append(angle + math.pi)
        self.trail = [[0.0] * self.width for _ in range(self.height)]

    def seed_center(self) -> None:
        """Place all agents at center pointing outward."""
        cx, cy = self.width / 2, self.height / 2
        self.ax = [cx + random.gauss(0, 2) for _ in range(self.n_agents)]
        self.ay = [cy + random.gauss(0, 2) for _ in range(self.n_agents)]
        self.ah = [random.uniform(0, 2 * math.pi) for _ in range(self.n_agents)]
        self.trail = [[0.0] * self.width for _ in range(self.height)]

    def cycle_preset(self, direction: int = 1) -> str:
        """Switch to next/prev preset and return name."""
        self.preset_idx = (self.preset_idx + direction) % len(PHYSARUM_PRESET_NAMES)
        name = PHYSARUM_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def _sense(self, x: float, y: float, heading: float, offset_angle: float) -> float:
        """Sample trail intensity at a sensor position."""
        sx = x + self.sensor_dist * math.cos(heading + offset_angle)
        sy = y + self.sensor_dist * math.sin(heading + offset_angle)
        # Wrap toroidally
        ix = int(sx) % self.width
        iy = int(sy) % self.height
        return self.trail[iy][ix]

    def tick(self) -> None:
        """Advance one simulation step: sense-rotate-move-deposit then diffuse-decay."""
        w = self.width
        h = self.height
        sa = self.sensor_angle
        ta = self.turn_angle
        step = self.step_size

        # Phase 1: sense, rotate, move, deposit for each agent
        for i in range(self.n_agents):
            x, y, heading = self.ax[i], self.ay[i], self.ah[i]

            # Sense left, center, right
            sl = self._sense(x, y, heading, -sa)
            sc = self._sense(x, y, heading, 0.0)
            sr = self._sense(x, y, heading, sa)

            # Rotate based on sensor readings
            if sc >= sl and sc >= sr:
                pass  # keep heading (center is strongest)
            elif sl > sr:
                heading -= ta  # turn left
            elif sr > sl:
                heading += ta  # turn right
            else:
                # sl == sr and both > sc: random turn
                heading += ta if random.random() < 0.5 else -ta

            # Move forward
            nx = (x + step * math.cos(heading)) % w
            ny = (y + step * math.sin(heading)) % h

            self.ax[i] = nx
            self.ay[i] = ny
            self.ah[i] = heading

            # Deposit pheromone
            ix = int(nx) % w
            iy = int(ny) % h
            self.trail[iy][ix] += self.deposit_amount

        # Phase 2: diffuse and decay trail map
        self._diffuse_decay()

    def _diffuse_decay(self) -> None:
        """Apply 3x3 mean-filter diffusion and multiplicative decay to the trail."""
        w = self.width
        h = self.height
        old = self.trail
        dk = self.diffuse_k
        inv_dk = 1.0 - dk
        decay_mult = 1.0 - self.decay_rate
        new = [[0.0] * w for _ in range(h)]

        for r in range(h):
            rp = (r - 1) % h
            rn = (r + 1) % h
            for c in range(w):
                cp = (c - 1) % w
                cn = (c + 1) % w
                # 3x3 mean
                avg = (
                    old[rp][cp] + old[rp][c] + old[rp][cn] +
                    old[r][cp] + old[r][c] + old[r][cn] +
                    old[rn][cp] + old[rn][c] + old[rn][cn]
                ) / 9.0
                # Blend original with diffused, then decay
                new[r][c] = (inv_dk * old[r][c] + dk * avg) * decay_mult

        self.trail = new

    def max_trail(self) -> float:
        """Return the maximum trail value (for normalization)."""
        mx = 0.0
        for row in self.trail:
            for v in row:
                if v > mx:
                    mx = v
        return mx


# ---------------------------------------------------------------------------
# Fluid Dynamics — Lattice Boltzmann Method (D2Q9)
# ---------------------------------------------------------------------------

# Presets: (viscosity, inlet_velocity, description)
FLUID_PRESETS = {
    "laminar": (0.08, 0.08, "Smooth laminar flow"),
    "moderate": (0.04, 0.12, "Moderate Reynolds number"),
    "turbulent": (0.02, 0.15, "Turbulent vortex streets"),
    "viscous": (0.15, 0.06, "High viscosity, slow flow"),
    "fast": (0.01, 0.18, "Fast flow, chaotic vortices"),
}
FLUID_PRESET_NAMES = list(FLUID_PRESETS.keys())

# Rendering characters for fluid (velocity magnitude)
FLUID_SHADES = " ·:░▒▓█"


class FluidWorld:
    """Lattice Boltzmann Method (D2Q9) fluid dynamics simulation.

    Simulates 2D incompressible fluid on a lattice.  Users can place solid
    obstacles and watch vortex streets, eddies, and laminar-to-turbulent
    flow emerge in real time.

    The D2Q9 model uses 9 velocity directions per lattice node.  Each
    tick performs: streaming → boundary conditions → collision (BGK).
    """

    # D2Q9 lattice velocities (cx, cy) and weights
    #   0: rest, 1-4: cardinal, 5-8: diagonal
    CX = [0, 1, 0, -1, 0, 1, -1, -1, 1]
    CY = [0, 0, 1, 0, -1, 1, 1, -1, -1]
    W = [4/9, 1/9, 1/9, 1/9, 1/9, 1/36, 1/36, 1/36, 1/36]
    # Opposite direction index (for bounce-back)
    OPP = [0, 3, 4, 1, 2, 7, 8, 5, 6]

    def __init__(self, width: int, height: int, preset: str = "moderate"):
        self.width = width
        self.height = height
        self.preset_idx = FLUID_PRESET_NAMES.index(preset)

        # Obstacle mask: True = solid wall
        self.obstacle: list[list[bool]] = [[False] * width for _ in range(height)]

        # Distribution functions: f[i][y][x] for direction i
        self.f: list[list[list[float]]] = [
            [[0.0] * width for _ in range(height)] for _ in range(9)
        ]

        # Macroscopic fields (cached for rendering)
        self.rho: list[list[float]] = [[1.0] * width for _ in range(height)]
        self.ux: list[list[float]] = [[0.0] * width for _ in range(height)]
        self.uy: list[list[float]] = [[0.0] * width for _ in range(height)]

        # Parameters
        self._apply_preset(preset)

        # Initialize equilibrium distribution
        self._init_equilibrium()

        # Place default obstacle (cylinder in center)
        self._place_default_obstacle()

    def _apply_preset(self, name: str) -> None:
        visc, vel, _desc = FLUID_PRESETS[name]
        self.viscosity = visc
        self.inlet_velocity = vel
        # BGK relaxation parameter: tau = 3*nu + 0.5
        self.tau = 3.0 * self.viscosity + 0.5
        self.omega = 1.0 / self.tau

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(FLUID_PRESET_NAMES)
        name = FLUID_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def _init_equilibrium(self) -> None:
        """Initialize all nodes to equilibrium at rest density with inlet velocity."""
        u0 = self.inlet_velocity
        for y in range(self.height):
            for x in range(self.width):
                for i in range(9):
                    cu = self.CX[i] * u0 + self.CY[i] * 0.0
                    usq = u0 * u0
                    self.f[i][y][x] = self.W[i] * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq)
                self.ux[y][x] = u0
                self.uy[y][x] = 0.0
                self.rho[y][x] = 1.0

    def _place_default_obstacle(self) -> None:
        """Place a circular obstacle in the left-center of the domain."""
        cx = self.width // 5
        cy = self.height // 2
        radius = max(2, min(self.width, self.height) // 8)
        r2 = radius * radius
        for y in range(self.height):
            for x in range(self.width):
                if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= r2:
                    self.obstacle[y][x] = True

    def clear_obstacles(self) -> None:
        for y in range(self.height):
            for x in range(self.width):
                self.obstacle[y][x] = False

    def toggle_obstacle(self, x: int, y: int, radius: int = 1) -> None:
        """Toggle obstacle cells in a radius around (x, y)."""
        new_val = not self.obstacle[max(0, min(y, self.height-1))][max(0, min(x, self.width-1))]
        for dy in range(-radius + 1, radius):
            for dx in range(-radius + 1, radius):
                ny, nx = y + dy, x + dx
                if 0 <= ny < self.height and 0 <= nx < self.width:
                    if dx * dx + dy * dy < radius * radius:
                        self.obstacle[ny][nx] = new_val

    def set_obstacle(self, x: int, y: int, radius: int = 1) -> None:
        """Set obstacle cells (paint mode)."""
        for dy in range(-radius + 1, radius):
            for dx in range(-radius + 1, radius):
                ny, nx = y + dy, x + dx
                if 0 <= ny < self.height and 0 <= nx < self.width:
                    if dx * dx + dy * dy < radius * radius:
                        self.obstacle[ny][nx] = True

    def tick(self) -> None:
        """Advance one LBM time step: stream → bounce-back → inlet/outlet BC → collide."""
        w = self.width
        h = self.height

        # --- Streaming (propagation) ---
        # Move distributions to neighboring cells in their velocity direction
        new_f: list[list[list[float]]] = [
            [[0.0] * w for _ in range(h)] for _ in range(9)
        ]
        for i in range(9):
            cx, cy = self.CX[i], self.CY[i]
            for y in range(h):
                for x in range(w):
                    # Source cell (where the distribution came from)
                    sx = x - cx
                    sy = y - cy
                    if 0 <= sx < w and 0 <= sy < h:
                        new_f[i][y][x] = self.f[i][sy][sx]
                    else:
                        # Boundary: use current cell value (open boundary)
                        new_f[i][y][x] = self.f[i][y][x]

        # --- Bounce-back on obstacles ---
        for y in range(h):
            for x in range(w):
                if self.obstacle[y][x]:
                    for i in range(9):
                        new_f[self.OPP[i]][y][x] = self.f[i][y][x]

        self.f = new_f

        # --- Inlet boundary (left wall, Zou-He style simplified) ---
        u0 = self.inlet_velocity
        for y in range(1, h - 1):
            if not self.obstacle[y][0]:
                rho_in = 1.0
                self.f[1][y][0] = self.f[3][y][0] + (2.0/3.0) * rho_in * u0
                self.f[5][y][0] = self.f[7][y][0] + (1.0/6.0) * rho_in * u0
                self.f[8][y][0] = self.f[6][y][0] + (1.0/6.0) * rho_in * u0

        # --- Outlet boundary (right wall, zero-gradient) ---
        for y in range(h):
            for i in range(9):
                self.f[i][y][w-1] = self.f[i][y][w-2]

        # --- Top/bottom walls: bounce-back ---
        for x in range(w):
            for i in range(9):
                self.f[self.OPP[i]][0][x] = self.f[i][0][x]
                self.f[self.OPP[i]][h-1][x] = self.f[i][h-1][x]

        # --- Compute macroscopic quantities and collide (BGK) ---
        omega = self.omega
        for y in range(h):
            for x in range(w):
                if self.obstacle[y][x]:
                    self.rho[y][x] = 0.0
                    self.ux[y][x] = 0.0
                    self.uy[y][x] = 0.0
                    continue

                # Density and velocity from distribution
                r = 0.0
                vx = 0.0
                vy = 0.0
                for i in range(9):
                    fi = self.f[i][y][x]
                    r += fi
                    vx += self.CX[i] * fi
                    vy += self.CY[i] * fi

                if r > 0.0:
                    vx /= r
                    vy /= r
                else:
                    r = 1.0
                    vx = 0.0
                    vy = 0.0

                self.rho[y][x] = r
                self.ux[y][x] = vx
                self.uy[y][x] = vy

                # Equilibrium and collision
                usq = vx * vx + vy * vy
                for i in range(9):
                    cu = self.CX[i] * vx + self.CY[i] * vy
                    feq = self.W[i] * r * (1.0 + 3.0 * cu + 4.5 * cu * cu - 1.5 * usq)
                    self.f[i][y][x] += omega * (feq - self.f[i][y][x])

    def velocity_magnitude(self, y: int, x: int) -> float:
        vx = self.ux[y][x]
        vy = self.uy[y][x]
        return math.sqrt(vx * vx + vy * vy)

    def curl(self, y: int, x: int) -> float:
        """Compute vorticity (curl of velocity) at (x, y) for visualization."""
        w, h = self.width, self.height
        # duy/dx - dux/dy (finite differences)
        uy_right = self.uy[y][min(x+1, w-1)]
        uy_left = self.uy[y][max(x-1, 0)]
        ux_up = self.ux[max(y-1, 0)][x]
        ux_down = self.ux[min(y+1, h-1)][x]
        return (uy_right - uy_left) - (ux_down - ux_up)

    def max_velocity(self) -> float:
        mx = 0.0
        for y in range(self.height):
            for x in range(self.width):
                if not self.obstacle[y][x]:
                    v = self.velocity_magnitude(y, x)
                    if v > mx:
                        mx = v
        return mx

    def reynolds_number(self) -> float:
        """Approximate Reynolds number: Re = U*L / nu."""
        # L = characteristic length (obstacle diameter ~ width/4)
        L = max(1, min(self.width, self.height) // 4)
        nu = self.viscosity
        return self.inlet_velocity * L / nu if nu > 0 else 0.0

    def reset(self) -> None:
        """Reset fluid to initial equilibrium state."""
        self._init_equilibrium()


# ---------------------------------------------------------------------------
# Ising Model — 2D ferromagnetic spin simulation (Metropolis-Hastings)
# ---------------------------------------------------------------------------

# Presets: (temperature, coupling_J, description)
# Critical temperature for 2D Ising: Tc = 2J / ln(1+sqrt(2)) ≈ 2.269 for J=1
ISING_PRESETS = {
    "cold":       (0.5,  1.0, "Deep ferromagnetic — highly ordered"),
    "cool":       (1.5,  1.0, "Below critical — large domains"),
    "critical":   (2.269, 1.0, "Critical temperature — phase transition"),
    "warm":       (3.0,  1.0, "Above critical — paramagnetic"),
    "hot":        (5.0,  1.0, "High temperature — fully disordered"),
    "anti-ferro": (1.5, -1.0, "Antiferromagnetic — checkerboard order"),
}
ISING_PRESET_NAMES = list(ISING_PRESETS.keys())

# Rendering characters: spin-up and spin-down
ISING_SPIN_UP = "▀▀"
ISING_SPIN_DOWN = "▄▄"


class IsingWorld:
    """2D Ising Model simulation using Metropolis-Hastings algorithm.

    Each site on a 2D square lattice holds a spin (+1 or -1).  The
    Hamiltonian H = -J Σ s_i s_j (sum over nearest neighbours) drives
    the dynamics via the Metropolis acceptance rule at temperature T.

    At low T the system is ferromagnetic (ordered); above the critical
    temperature Tc ≈ 2.269 J/kB it becomes paramagnetic (disordered).
    """

    def __init__(self, width: int, height: int, preset: str = "critical"):
        self.width = width
        self.height = height
        self.preset_idx = ISING_PRESET_NAMES.index(preset)

        # Spin lattice: +1 or -1
        self.spin: list[list[int]] = [
            [random.choice((-1, 1)) for _ in range(width)]
            for _ in range(height)
        ]

        # Parameters
        self._apply_preset(preset)

        # Cached observables (updated each tick)
        self._magnetization = 0.0
        self._energy = 0.0
        self._update_observables()

        # Steps per tick (multiple Metropolis sweeps per rendered frame)
        self.sweeps_per_tick = 1

    def _apply_preset(self, name: str) -> None:
        temp, J, _desc = ISING_PRESETS[name]
        self.temperature = temp
        self.J = J
        # beta = 1 / (kB * T); we set kB = 1
        self.beta = 1.0 / max(self.temperature, 1e-9)

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(ISING_PRESET_NAMES)
        name = ISING_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def set_temperature(self, T: float) -> None:
        """Set temperature directly (for real-time slider control)."""
        self.temperature = max(0.01, T)
        self.beta = 1.0 / self.temperature

    def _neighbour_sum(self, y: int, x: int) -> int:
        """Sum of nearest-neighbour spins (periodic boundary conditions)."""
        w, h = self.width, self.height
        return (
            self.spin[(y - 1) % h][x] +
            self.spin[(y + 1) % h][x] +
            self.spin[y][(x - 1) % w] +
            self.spin[y][(x + 1) % w]
        )

    def tick(self) -> None:
        """Perform Metropolis-Hastings sweeps over the lattice."""
        w, h = self.width, self.height
        J = self.J
        beta = self.beta
        spin = self.spin
        rand = random.random

        for _ in range(self.sweeps_per_tick):
            # One full sweep = N random single-spin flips
            n_sites = w * h
            for _ in range(n_sites):
                x = random.randint(0, w - 1)
                y = random.randint(0, h - 1)
                s = spin[y][x]
                nn = (
                    spin[(y - 1) % h][x] +
                    spin[(y + 1) % h][x] +
                    spin[y][(x - 1) % w] +
                    spin[y][(x + 1) % w]
                )
                # Energy change if we flip: ΔE = 2 * J * s * Σnn
                dE = 2.0 * J * s * nn
                if dE <= 0.0 or rand() < math.exp(-beta * dE):
                    spin[y][x] = -s

        self._update_observables()

    def _update_observables(self) -> None:
        """Compute magnetization and energy."""
        w, h = self.width, self.height
        total_spin = 0
        total_energy = 0.0
        for y in range(h):
            for x in range(w):
                s = self.spin[y][x]
                total_spin += s
                # Count right and down neighbours only to avoid double-counting
                total_energy -= self.J * s * self.spin[y][(x + 1) % w]
                total_energy -= self.J * s * self.spin[(y + 1) % h][x]
        n = w * h
        self._magnetization = total_spin / n
        self._energy = total_energy / n

    @property
    def magnetization(self) -> float:
        """Average magnetization per site: M = <s> in [-1, 1]."""
        return self._magnetization

    @property
    def energy(self) -> float:
        """Average energy per site."""
        return self._energy

    def reset_random(self) -> None:
        """Reset to random spin configuration."""
        for y in range(self.height):
            for x in range(self.width):
                self.spin[y][x] = random.choice((-1, 1))
        self._update_observables()

    def reset_aligned(self, direction: int = 1) -> None:
        """Reset to fully aligned spin configuration."""
        s = 1 if direction >= 0 else -1
        for y in range(self.height):
            for x in range(self.width):
                self.spin[y][x] = s
        self._update_observables()


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
# Genetic Algorithm Pattern Evolver
# ---------------------------------------------------------------------------

class PatternEvolver:
    """Breeds cellular automaton patterns using a genetic algorithm.

    Each individual is a set of (row, col) offsets within a bounded region.
    Fitness is evaluated by simulating the pattern for a number of generations
    and measuring one of: longevity, max population, or symmetry.
    """

    FITNESS_CRITERIA = ["longevity", "max_population", "symmetry"]
    FITNESS_LABELS = {
        "longevity": "Longevity (survive longest)",
        "max_population": "Max Population (peak cells)",
        "symmetry": "Symmetry (bilateral balance)",
    }

    def __init__(
        self,
        region_w: int = 20,
        region_h: int = 20,
        pop_size: int = 20,
        sim_steps: int = 200,
        mutation_rate: float = 0.05,
        density: float = 0.3,
        birth: set[int] | None = None,
        survival: set[int] | None = None,
    ):
        self.region_w = region_w
        self.region_h = region_h
        self.pop_size = pop_size
        self.sim_steps = sim_steps
        self.mutation_rate = mutation_rate
        self.density = density
        self.birth = birth or {3}
        self.survival = survival or {2, 3}

        self.population: list[set[tuple[int, int]]] = []
        self.fitness_scores: list[float] = []
        self.ga_generation = 0
        self.criterion = "longevity"
        self.best_pattern: set[tuple[int, int]] = set()
        self.best_fitness: float = 0.0
        self.best_ever_pattern: set[tuple[int, int]] = set()
        self.best_ever_fitness: float = 0.0
        self.eval_index = 0  # which individual we're evaluating next
        self.phase = "evaluating"  # "evaluating" or "breeding"

    def initialize(self) -> None:
        """Create initial random population."""
        self.population = []
        for _ in range(self.pop_size):
            self.population.append(self._random_individual())
        self.fitness_scores = [0.0] * self.pop_size
        self.ga_generation = 0
        self.eval_index = 0
        self.phase = "evaluating"
        self.best_pattern = set()
        self.best_fitness = 0.0
        self.best_ever_pattern = set()
        self.best_ever_fitness = 0.0

    def _random_individual(self) -> set[tuple[int, int]]:
        """Generate a random pattern within the region."""
        cells = set()
        for r in range(self.region_h):
            for c in range(self.region_w):
                if random.random() < self.density:
                    cells.add((r, c))
        return cells

    def evaluate_one(self) -> tuple[int, float]:
        """Evaluate the next individual. Returns (index, fitness).

        Call this repeatedly until eval_index wraps to trigger breeding.
        """
        idx = self.eval_index
        pattern = self.population[idx]
        fitness = self._compute_fitness(pattern)
        self.fitness_scores[idx] = fitness

        self.eval_index += 1
        if self.eval_index >= self.pop_size:
            self.phase = "breeding"

        return idx, fitness

    def breed_next_generation(self) -> None:
        """Select, crossover, and mutate to create a new generation."""
        # Find best of this generation
        best_idx = max(range(self.pop_size), key=lambda i: self.fitness_scores[i])
        self.best_pattern = self.population[best_idx]
        self.best_fitness = self.fitness_scores[best_idx]

        if self.best_fitness > self.best_ever_fitness:
            self.best_ever_fitness = self.best_fitness
            self.best_ever_pattern = set(self.best_pattern)

        # Build next generation
        new_pop: list[set[tuple[int, int]]] = []

        # Elitism: keep top 2
        ranked = sorted(range(self.pop_size), key=lambda i: self.fitness_scores[i], reverse=True)
        new_pop.append(set(self.population[ranked[0]]))
        new_pop.append(set(self.population[ranked[1]]))

        # Fill rest via tournament selection + crossover + mutation
        while len(new_pop) < self.pop_size:
            parent_a = self._tournament_select()
            parent_b = self._tournament_select()
            child = self._crossover(parent_a, parent_b)
            child = self._mutate(child)
            new_pop.append(child)

        self.population = new_pop
        self.fitness_scores = [0.0] * self.pop_size
        self.ga_generation += 1
        self.eval_index = 0
        self.phase = "evaluating"

    def _compute_fitness(self, pattern: set[tuple[int, int]]) -> float:
        """Simulate pattern and return fitness score."""
        if not pattern:
            return 0.0

        # Build an isolated simulation grid (unbounded, using dict tracking)
        cells = set(pattern)
        birth = self.birth
        survival = self.survival

        max_pop = len(cells)
        last_alive_gen = 0
        # Track states for cycle detection
        seen_states: dict[frozenset[tuple[int, int]], int] = {}
        symmetry_sum = 0.0
        symmetry_count = 0

        for gen in range(1, self.sim_steps + 1):
            state_key = frozenset(cells)
            if state_key in seen_states:
                # Entered a cycle — pattern is stable/oscillating
                cycle_len = gen - seen_states[state_key]
                if self.criterion == "longevity":
                    # Reward reaching a stable cycle: full marks + bonus for cycle
                    return float(self.sim_steps + cycle_len)
                elif self.criterion == "max_population":
                    return float(max_pop)
                elif self.criterion == "symmetry":
                    return symmetry_sum / max(symmetry_count, 1)
            seen_states[state_key] = gen

            # Tick
            neighbor_count: Counter[tuple[int, int]] = Counter()
            for r, c in cells:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if dr == 0 and dc == 0:
                            continue
                        neighbor_count[(r + dr, c + dc)] += 1
            new_cells: set[tuple[int, int]] = set()
            for pos, count in neighbor_count.items():
                if pos in cells:
                    if count in survival:
                        new_cells.add(pos)
                else:
                    if count in birth:
                        new_cells.add(pos)
            cells = new_cells

            if not cells:
                break

            pop = len(cells)
            if pop > max_pop:
                max_pop = pop
            last_alive_gen = gen

            # Measure symmetry periodically
            if gen % 10 == 0 and cells:
                symmetry_sum += self._measure_symmetry(cells)
                symmetry_count += 1

        if self.criterion == "longevity":
            return float(last_alive_gen)
        elif self.criterion == "max_population":
            return float(max_pop)
        elif self.criterion == "symmetry":
            return symmetry_sum / max(symmetry_count, 1)
        return 0.0

    @staticmethod
    def _measure_symmetry(cells: set[tuple[int, int]]) -> float:
        """Measure bilateral symmetry (0.0 to 1.0) of a cell pattern."""
        if not cells:
            return 0.0
        min_r = min(r for r, _ in cells)
        max_r = max(r for r, _ in cells)
        min_c = min(c for _, c in cells)
        max_c = max(c for _, c in cells)
        center_r = (min_r + max_r) / 2.0
        center_c = (min_c + max_c) / 2.0

        total = len(cells)
        h_matches = 0  # horizontal symmetry
        v_matches = 0  # vertical symmetry
        for r, c in cells:
            # Horizontal mirror
            mr = int(round(2 * center_r - r))
            if (mr, c) in cells:
                h_matches += 1
            # Vertical mirror
            mc = int(round(2 * center_c - c))
            if (r, mc) in cells:
                v_matches += 1

        return max(h_matches, v_matches) / total

    def _tournament_select(self, k: int = 3) -> set[tuple[int, int]]:
        """Select an individual via tournament selection."""
        candidates = random.sample(range(self.pop_size), min(k, self.pop_size))
        winner = max(candidates, key=lambda i: self.fitness_scores[i])
        return self.population[winner]

    def _crossover(self, a: set[tuple[int, int]], b: set[tuple[int, int]]) -> set[tuple[int, int]]:
        """Combine two parents using uniform crossover over the region."""
        child: set[tuple[int, int]] = set()
        all_positions = a | b
        for pos in all_positions:
            if random.random() < 0.5:
                child.add(pos)
        return child

    def _mutate(self, individual: set[tuple[int, int]]) -> set[tuple[int, int]]:
        """Randomly flip cells within the region."""
        result = set(individual)
        for r in range(self.region_h):
            for c in range(self.region_w):
                if random.random() < self.mutation_rate:
                    pos = (r, c)
                    if pos in result:
                        result.discard(pos)
                    else:
                        result.add(pos)
        return result

    def get_current_pattern(self) -> set[tuple[int, int]]:
        """Return the pattern currently being evaluated (for display)."""
        if self.eval_index < self.pop_size:
            return self.population[self.eval_index]
        return self.best_pattern

    def status_text(self) -> str:
        """Return a short status string for the status bar."""
        crit_short = {
            "longevity": "LONGEV",
            "max_population": "MAXPOP",
            "symmetry": "SYMM",
        }[self.criterion]
        return (
            f"GA Gen:{self.ga_generation} Eval:{self.eval_index}/{self.pop_size} "
            f"Best:{self.best_fitness:.0f} Ever:{self.best_ever_fitness:.0f} [{crit_short}]"
        )


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
        # Heatmap mode state
        self.heatmap_mode = False
        self.heatmap: Counter[tuple[int, int]] = Counter()  # cumulative alive ticks per cell
        # Evolve (genetic algorithm) mode state
        self.evolve_mode = False
        self.evolver: PatternEvolver | None = None
        # Split-screen comparison mode state
        self.split_mode = False
        self.split_grid_left: Grid | None = None
        self.split_grid_right: Grid | None = None
        self.split_rule_left = 0   # index into RULESETS
        self.split_rule_right = 1  # index into RULESETS
        self.split_gen = 0
        self.split_pop_left: list[int] = []
        self.split_pop_right: list[int] = []
        # Multi-state automaton mode (Brian's Brain / Wireworld)
        self.multistate_mode = False
        self.multistate_type_idx = 0  # 0=Life, 1=Brian's Brain, 2=Wireworld
        self.multistate_grid: MultiStateGrid | None = None
        self.multistate_gen = 0
        # Lenia (continuous cellular automaton) mode
        self.lenia_mode = False
        self.lenia_grid: LeniaGrid | None = None
        self.lenia_gen = 0
        self.lenia_preset_idx = 0  # index into LENIA_PRESET_NAMES
        # Wolfram 1D elementary cellular automaton mode
        self.wolfram_mode = False
        self.wolfram_rule = 30  # Wolfram rule number (0-255)
        self.wolfram_rows: list[list[bool]] = []  # computed rows of cells
        self.wolfram_generation = 0
        self.wolfram_notable = [30, 54, 60, 90, 110, 150, 182, 184, 250]
        # Falling sand simulation mode
        self.sand_mode = False
        self.sand_grid: SandGrid | None = None
        self.sand_gen = 0
        self.sand_material_idx = 0  # index into SAND_MATERIALS
        self.sand_brush_size = 2    # brush radius for placing material
        # Reaction-Diffusion (Gray-Scott) mode
        self.rd_mode = False
        self.rd_grid: ReactionDiffusionGrid | None = None
        self.rd_gen = 0
        self.rd_preset_idx = 0  # index into RD_PRESET_NAMES
        # Particle Life mode
        self.pl_mode = False
        self.pl_world: ParticleLifeWorld | None = None
        self.pl_gen = 0
        # Wa-Tor Ecosystem mode
        self.eco_mode = False
        self.eco_world: WaTorWorld | None = None
        self.eco_gen = 0
        # Physarum (slime mold) mode
        self.physarum_mode = False
        self.physarum_world: PhysarumWorld | None = None
        self.physarum_gen = 0
        self.physarum_preset_idx = 0
        # Fluid Dynamics (Lattice Boltzmann) mode
        self.fluid_mode = False
        self.fluid_world: FluidWorld | None = None
        self.fluid_gen = 0
        self.fluid_preset_idx = 0
        self.fluid_viz = 0          # 0=velocity, 1=vorticity, 2=density
        self.fluid_brush_size = 2   # obstacle brush radius
        self.fluid_cursor_x = 0
        self.fluid_cursor_y = 0
        self.fluid_painting = False  # True while painting obstacles
        # Ising Model (statistical mechanics) mode
        self.ising_mode = False
        self.ising_world: IsingWorld | None = None
        self.ising_gen = 0
        self.ising_preset_idx = 0

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
            if self.lenia_mode:
                if self.running:
                    self._lenia_tick()
            elif self.wolfram_mode:
                if self.running:
                    self._wolfram_tick()
            elif self.multistate_mode:
                if self.running:
                    self._multistate_tick()
            elif self.sand_mode:
                if self.running:
                    self._sand_tick()
            elif self.rd_mode:
                if self.running:
                    self._rd_tick()
            elif self.pl_mode:
                if self.running:
                    self._pl_tick()
            elif self.eco_mode:
                if self.running:
                    self._eco_tick()
            elif self.physarum_mode:
                if self.running:
                    self._physarum_tick()
            elif self.fluid_mode:
                if self.running:
                    self._fluid_tick()
            elif self.ising_mode:
                if self.running:
                    self._ising_tick()
            elif self.split_mode:
                if self.running:
                    self._split_tick()
            elif self.evolve_mode:
                self._evolve_tick()
            elif self.running and self.history_pos == -1:
                self._record_history()
                self._record_population()
                # Accumulate heatmap before tick (count current alive cells)
                if self.heatmap_mode:
                    self.heatmap.update(self.grid.cells)
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
            # Heatmap gradient: cool → hot (blue, cyan, green, yellow, red)
            curses.init_pair(12, curses.COLOR_BLUE, -1)    # cold (rarely active)
            curses.init_pair(13, curses.COLOR_CYAN, -1)    # cool
            curses.init_pair(14, curses.COLOR_GREEN, -1)   # warm
            curses.init_pair(15, curses.COLOR_YELLOW, -1)  # hot
            curses.init_pair(16, curses.COLOR_RED, -1)     # hottest (frequently active)
            # Multi-state automaton colors
            curses.init_pair(17, curses.COLOR_WHITE, -1)   # Brian's Brain: ON
            curses.init_pair(18, curses.COLOR_BLUE, -1)    # Brian's Brain: DYING
            curses.init_pair(19, curses.COLOR_YELLOW, -1)  # Wireworld: HEAD (electron)
            curses.init_pair(20, curses.COLOR_RED, -1)     # Wireworld: TAIL
            curses.init_pair(21, curses.COLOR_CYAN, -1)    # Wireworld: CONDUCTOR
            curses.init_pair(22, curses.COLOR_WHITE, -1)   # Langton's Ant: BLACK cell
            curses.init_pair(23, curses.COLOR_RED, -1)     # Langton's Ant: ANT
            # Lenia continuous CA gradient (dark → bright)
            curses.init_pair(24, curses.COLOR_BLUE, -1)    # Lenia: dim/low
            curses.init_pair(25, curses.COLOR_CYAN, -1)    # Lenia: low-mid
            curses.init_pair(26, curses.COLOR_GREEN, -1)   # Lenia: mid
            curses.init_pair(27, curses.COLOR_YELLOW, -1)  # Lenia: mid-high
            curses.init_pair(28, curses.COLOR_WHITE, -1)   # Lenia: high/bright
            # Falling sand material colors
            curses.init_pair(29, curses.COLOR_YELLOW, -1)  # Sand
            curses.init_pair(30, curses.COLOR_BLUE, -1)    # Water
            curses.init_pair(31, curses.COLOR_RED, -1)     # Fire
            curses.init_pair(32, curses.COLOR_WHITE, -1)   # Stone
            curses.init_pair(33, curses.COLOR_GREEN, -1)   # Plant
            # Reaction-Diffusion gradient (chemical V concentration)
            curses.init_pair(34, curses.COLOR_BLUE, -1)    # RD: low V
            curses.init_pair(35, curses.COLOR_CYAN, -1)    # RD: low-mid V
            curses.init_pair(36, curses.COLOR_GREEN, -1)   # RD: mid V
            curses.init_pair(37, curses.COLOR_YELLOW, -1)  # RD: mid-high V
            curses.init_pair(38, curses.COLOR_RED, -1)     # RD: high V (bright)
            # Particle Life type colors
            curses.init_pair(39, curses.COLOR_RED, -1)      # PL: type 0 Red
            curses.init_pair(40, curses.COLOR_GREEN, -1)    # PL: type 1 Green
            curses.init_pair(41, curses.COLOR_BLUE, -1)     # PL: type 2 Blue
            curses.init_pair(42, curses.COLOR_YELLOW, -1)   # PL: type 3 Yellow
            curses.init_pair(43, curses.COLOR_CYAN, -1)     # PL: type 4 Cyan
            curses.init_pair(44, curses.COLOR_MAGENTA, -1)  # PL: type 5 Magenta
            # Wa-Tor Ecosystem colors
            curses.init_pair(45, curses.COLOR_GREEN, -1)   # Fish
            curses.init_pair(46, curses.COLOR_RED, -1)     # Shark
            # Physarum trail gradient (dark → bright organic greens/yellows)
            curses.init_pair(47, curses.COLOR_BLUE, -1)    # Physarum: trace
            curses.init_pair(48, curses.COLOR_CYAN, -1)    # Physarum: low
            curses.init_pair(49, curses.COLOR_GREEN, -1)   # Physarum: mid
            curses.init_pair(50, curses.COLOR_YELLOW, -1)  # Physarum: high
            curses.init_pair(51, curses.COLOR_WHITE, -1)   # Physarum: peak
            # Fluid Dynamics gradient (velocity/vorticity visualization)
            curses.init_pair(52, curses.COLOR_BLUE, -1)    # Fluid: slow/neg vort
            curses.init_pair(53, curses.COLOR_CYAN, -1)    # Fluid: low
            curses.init_pair(54, curses.COLOR_GREEN, -1)   # Fluid: medium
            curses.init_pair(55, curses.COLOR_YELLOW, -1)  # Fluid: high
            curses.init_pair(56, curses.COLOR_RED, -1)     # Fluid: fast/pos vort
            curses.init_pair(57, curses.COLOR_WHITE, -1)   # Fluid: obstacle
            curses.init_pair(58, curses.COLOR_MAGENTA, -1) # Fluid: cursor
            # Ising Model spin colors
            curses.init_pair(59, curses.COLOR_CYAN, -1)    # Ising: spin up (+1)
            curses.init_pair(60, curses.COLOR_RED, -1)     # Ising: spin down (-1)

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

    def _heatmap_color_pair(self, count: int, max_count: int) -> tuple[int, int]:
        """Return (color_pair, attr) for heatmap intensity.

        Maps count to a 5-tier gradient from cold (blue) to hot (red).
        """
        if max_count <= 0:
            return 12, 0
        ratio = count / max_count
        if ratio < 0.2:
            return 12, curses.A_DIM      # blue, dim
        elif ratio < 0.4:
            return 13, 0                  # cyan
        elif ratio < 0.6:
            return 14, 0                  # green
        elif ratio < 0.8:
            return 15, 0                  # yellow
        else:
            return 16, curses.A_BOLD      # red, bold

    # --- input ---

    def _handle_input(self) -> bool:
        """Process input. Returns False to quit."""
        key = self.stdscr.getch()
        if key == -1:
            return True

        # Blueprint mode has its own input handler
        if self.blueprint_mode:
            return self._handle_blueprint_input(key)

        # Wolfram 1D mode has its own input handler
        if self.wolfram_mode:
            return self._handle_wolfram_input(key)

        # Lenia continuous CA mode has its own input handler
        if self.lenia_mode:
            return self._handle_lenia_input(key)

        # Multi-state automaton mode has its own input handler
        if self.multistate_mode:
            return self._handle_multistate_input(key)

        # Falling sand mode has its own input handler
        if self.sand_mode:
            return self._handle_sand_input(key)

        # Reaction-Diffusion mode has its own input handler
        if self.rd_mode:
            return self._handle_rd_input(key)

        # Particle Life mode has its own input handler
        if self.pl_mode:
            return self._handle_pl_input(key)

        # Wa-Tor Ecosystem mode has its own input handler
        if self.eco_mode:
            return self._handle_eco_input(key)

        # Physarum (slime mold) mode has its own input handler
        if self.physarum_mode:
            return self._handle_physarum_input(key)

        # Fluid Dynamics (LBM) mode has its own input handler
        if self.fluid_mode:
            return self._handle_fluid_input(key)

        # Ising Model mode has its own input handler
        if self.ising_mode:
            return self._handle_ising_input(key)

        # Split mode has limited input
        if self.split_mode:
            return self._handle_split_input(key)

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
                if self.heatmap_mode:
                    self.heatmap.update(self.grid.cells)
                self.grid.tick()
                self.generation += 1

        # Randomize
        elif key == ord("r"):
            self.grid.randomize()
            self.generation = 0
            self.history.clear()
            self.history_pos = -1
            self.pop_history.clear()
            self.heatmap.clear()
            self._set_message("Randomized")

        # Clear
        elif key == ord("c"):
            self.grid.clear()
            self.generation = 0
            self.history.clear()
            self.history_pos = -1
            self.pop_history.clear()
            self.heatmap.clear()
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

        # Import RLE pattern file
        elif key == ord("L"):
            self._import_rle()

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

        # Heatmap mode toggle
        elif key == ord("H"):
            self.heatmap_mode = not self.heatmap_mode
            if self.heatmap_mode:
                self._set_message("Heatmap ON — tracking cell activity")
            else:
                self._set_message("Heatmap OFF")

        # Wolfram 1D elementary CA mode
        elif key == ord("W"):
            self._start_wolfram()

        # Lenia continuous CA mode
        elif key == ord("L"):
            self._start_lenia()

        # Multi-state automaton mode (Brian's Brain / Wireworld)
        elif key == ord("X"):
            self._start_multistate()

        # Falling sand simulation mode
        elif key == ord("F"):
            self._start_sand()

        # Reaction-Diffusion (Gray-Scott) mode
        elif key == ord("R"):
            self._start_rd()

        # Particle Life mode
        elif key == ord("P"):
            self._start_pl()

        # Ecosystem (Wa-Tor) mode
        elif key == ord("E"):
            self._start_eco()

        # Physarum (slime mold) mode
        elif key == ord("S"):
            self._start_physarum()

        # Fluid Dynamics (Lattice Boltzmann) mode
        elif key == ord("D"):
            self._start_fluid()

        # Ising Model (statistical mechanics) mode
        elif key == ord("I"):
            self._start_ising()

        # Split-screen comparison mode
        elif key == ord("m"):
            if self.split_mode:
                self._stop_split()
            else:
                self._start_split()

        # Evolve (genetic algorithm) mode
        elif key == ord("a"):
            if self.evolve_mode:
                self._stop_evolve()
            else:
                self._start_evolve()

        # Change evolve fitness criterion on the fly
        elif self.evolve_mode and self.evolver and key in (ord("1"), ord("2"), ord("3")):
            criteria = ["longevity", "max_population", "symmetry"]
            idx = key - ord("1")
            self.evolver.criterion = criteria[idx]
            self._set_message(
                f"Evolve goal: {PatternEvolver.FITNESS_LABELS[criteria[idx]]}"
            )

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

    def _handle_split_input(self, key: int) -> bool:
        """Handle input while in split-screen comparison mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        elif key == ord("m") or key == 27:
            self._stop_split()
        elif key == ord("s"):
            # Single step
            if not self.running:
                self._split_tick()
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

    # --- split-screen comparison mode ---

    def _ruleset_menu(self, prompt: str, exclude: int | None = None) -> int | None:
        """Show a menu to pick a ruleset. Returns index or None if cancelled."""
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        max_h, max_w = self.stdscr.getmaxyx()
        selected = 0

        while True:
            self.stdscr.erase()
            title = prompt
            try:
                self.stdscr.addstr(0, 0, title[:max_w - 1], curses.A_BOLD)
            except curses.error:
                pass
            for i, (name, birth, survival) in enumerate(RULESETS):
                rs = rule_string(birth, survival)
                marker = " >> " if i == selected else "    "
                label = f"{marker}{name} ({rs})"
                if i == exclude:
                    label += "  [already selected]"
                attr = curses.A_REVERSE if i == selected else 0
                if i + 2 < max_h:
                    try:
                        self.stdscr.addstr(i + 2, 0, label.ljust(max_w - 1)[:max_w - 1], attr)
                    except curses.error:
                        pass
            footer = " [Up/Down] Navigate  [Enter] Select  [Esc] Cancel"
            if len(RULESETS) + 3 < max_h:
                try:
                    self.stdscr.addstr(len(RULESETS) + 3, 0, footer[:max_w - 1], curses.A_DIM)
                except curses.error:
                    pass
            self.stdscr.refresh()

            key = self.stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(RULESETS)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(RULESETS)
            elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
                self.stdscr.nodelay(True)
                self._update_timeout()
                return selected
            elif key == 27:
                self.stdscr.nodelay(True)
                self._update_timeout()
                return None

    def _start_split(self) -> None:
        """Enter split-screen comparison mode."""
        if not self.grid.cells:
            self._set_message("Place a pattern first — split needs a seed")
            return

        # Pick left ruleset
        left = self._ruleset_menu("Select LEFT ruleset:")
        if left is None:
            self._set_message("Split cancelled")
            return

        # Pick right ruleset
        right = self._ruleset_menu("Select RIGHT ruleset:", exclude=left)
        if right is None:
            self._set_message("Split cancelled")
            return

        if left == right:
            self._set_message("Pick two different rulesets to compare")
            return

        self.split_rule_left = left
        self.split_rule_right = right

        # Clone current grid state into two independent grids
        self.split_grid_left = Grid(self.grid.width, self.grid.height)
        self.split_grid_left.cells = set(self.grid.cells)
        self.split_grid_left.ages = dict(self.grid.ages)
        self.split_grid_left.toroidal = self.grid.toroidal
        _, birth_l, surv_l = RULESETS[left]
        self.split_grid_left.birth = set(birth_l)
        self.split_grid_left.survival = set(surv_l)

        self.split_grid_right = Grid(self.grid.width, self.grid.height)
        self.split_grid_right.cells = set(self.grid.cells)
        self.split_grid_right.ages = dict(self.grid.ages)
        self.split_grid_right.toroidal = self.grid.toroidal
        _, birth_r, surv_r = RULESETS[right]
        self.split_grid_right.birth = set(birth_r)
        self.split_grid_right.survival = set(surv_r)

        self.split_gen = 0
        self.split_pop_left = []
        self.split_pop_right = []
        self.split_mode = True
        self.running = False
        name_l = RULESETS[left][0]
        name_r = RULESETS[right][0]
        self._set_message(f"Split: {name_l} vs {name_r} — [Space] run, [M] exit")

    def _stop_split(self) -> None:
        """Exit split-screen comparison mode."""
        self.split_mode = False
        self.running = False
        self.split_grid_left = None
        self.split_grid_right = None
        self.split_pop_left.clear()
        self.split_pop_right.clear()
        self._set_message("Split mode ended")

    def _split_tick(self) -> None:
        """Advance both split grids one generation."""
        if self.split_grid_left and self.split_grid_right:
            self.split_grid_left.tick()
            self.split_grid_right.tick()
            self.split_gen += 1
            self.split_pop_left.append(len(self.split_grid_left.cells))
            self.split_pop_right.append(len(self.split_grid_right.cells))
            if len(self.split_pop_left) > self.SPARKLINE_WIDTH:
                self.split_pop_left = self.split_pop_left[-self.SPARKLINE_WIDTH:]
            if len(self.split_pop_right) > self.SPARKLINE_WIDTH:
                self.split_pop_right = self.split_pop_right[-self.SPARKLINE_WIDTH:]

    def _split_sparkline(self, pop_history: list[int]) -> str:
        """Return a sparkline for a split-screen population history."""
        if not pop_history:
            return ""
        bars = "▁▂▃▄▅▆▇█"
        values = pop_history[-20:]  # shorter sparkline to fit
        lo = min(values)
        hi = max(values)
        if hi == lo:
            return bars[3] * len(values)
        return "".join(bars[round((v - lo) / (hi - lo) * 7)] for v in values)

    # --- Lenia continuous cellular automaton mode ---

    def _handle_lenia_input(self, key: int) -> bool:
        """Handle input while in Lenia continuous CA mode."""
        if key == ord("q"):
            return False
        # Run / pause
        elif key == ord(" "):
            self.running = not self.running
        # Step
        elif key == ord("s"):
            if not self.running:
                self._lenia_tick()
        # Randomize
        elif key == ord("r"):
            if self.lenia_grid:
                self.lenia_grid.randomize()
                self.lenia_gen = 0
                self._set_message("Randomized")
        # Clear
        elif key == ord("c"):
            if self.lenia_grid:
                self.lenia_grid.clear()
                self.lenia_gen = 0
                self._set_message("Cleared")
        # Seed center blob
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.lenia_grid:
                self.lenia_grid.seed_center()
                self.lenia_gen = 0
                self._set_message("Seeded center blob")
        # Cycle preset species with F/G
        elif key == ord("f"):
            self.lenia_preset_idx = (self.lenia_preset_idx + 1) % len(LENIA_PRESET_NAMES)
            self._switch_lenia_preset()
        elif key == ord("g"):
            self.lenia_preset_idx = (self.lenia_preset_idx - 1) % len(LENIA_PRESET_NAMES)
            self._switch_lenia_preset()
        # Speed control
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Toroidal toggle
        elif key == ord("t"):
            if self.lenia_grid:
                self.lenia_grid.toroidal = not self.lenia_grid.toroidal
                mode = "ON" if self.lenia_grid.toroidal else "OFF"
                self._set_message(f"Toroidal wrapping {mode}")
        # Exit Lenia mode
        elif key == ord("L") or key == 27:
            self._stop_lenia()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_lenia(self) -> None:
        """Enter Lenia continuous CA mode."""
        self.running = False
        self.lenia_mode = True
        self.lenia_gen = 0
        self.lenia_preset_idx = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(1, max_w // 2)
        h = max(1, max_h - 3)
        self.lenia_grid = LeniaGrid(w, h)
        self.lenia_grid.seed_center()
        preset = LENIA_PRESET_NAMES[self.lenia_preset_idx]
        self._set_message(
            f"LENIA — {preset} | [F/G]Species [Space]Run [S]tep [R]and [Enter]Seed [L]Exit"
        )

    def _stop_lenia(self) -> None:
        """Exit Lenia mode."""
        self.lenia_mode = False
        self.running = False
        self.lenia_grid = None
        self.lenia_gen = 0
        self._set_message("Lenia mode ended")

    def _switch_lenia_preset(self) -> None:
        """Switch to a different Lenia preset species."""
        preset = LENIA_PRESET_NAMES[self.lenia_preset_idx]
        if self.lenia_grid:
            self.lenia_grid.apply_preset(preset)
            self.lenia_grid.clear()
            self.lenia_grid.seed_center()
        self.lenia_gen = 0
        self.running = False
        self._set_message(
            f"LENIA — {preset} | R={self.lenia_grid.R} T={self.lenia_grid.T}"
            if self.lenia_grid else f"LENIA — {preset}"
        )

    def _lenia_tick(self) -> None:
        """Advance one Lenia generation."""
        if self.lenia_grid:
            self.lenia_grid.tick()
            self.lenia_gen += 1

    def _lenia_cell_attr(self, value: float) -> tuple[str, int]:
        """Return (shade_char, curses attr) for a Lenia cell value in [0, 1]."""
        if value < 0.01:
            return "  ", 0
        # Map to shade index (1-4, skipping 0=space)
        idx = min(4, max(1, int(value * 4.99)))
        shade = LENIA_SHADES[idx]
        ch = shade + shade  # double-wide for square cells
        # Color gradient based on intensity
        if value < 0.2:
            pair = 24  # blue/dim
            extra = curses.A_DIM
        elif value < 0.4:
            pair = 25  # cyan
            extra = 0
        elif value < 0.6:
            pair = 26  # green
            extra = 0
        elif value < 0.8:
            pair = 27  # yellow
            extra = 0
        else:
            pair = 28  # white/bright
            extra = curses.A_BOLD
        attr = (curses.color_pair(pair) | extra) if self.use_color else extra
        return ch, attr

    def _draw_lenia(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Lenia continuous CA grid."""
        if not self.lenia_grid:
            return
        lg = self.lenia_grid

        for screen_r in range(min(grid_rows, lg.height)):
            for screen_c in range(min(grid_cols, lg.width)):
                x = screen_c * 2
                if x + 1 >= max_w:
                    break
                value = lg.cells[screen_r][screen_c]
                ch, attr = self._lenia_cell_attr(value)
                try:
                    self.stdscr.addstr(screen_r, x, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset = LENIA_PRESET_NAMES[self.lenia_preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            topo = "Torus" if lg.toroidal else "Bounded"
            mass = lg.population()
            active = lg.active_count()
            status = (
                f" Lenia: {preset} | Gen: {self.lenia_gen} | "
                f"Mass: {mass:.1f} Active: {active} | "
                f"R={lg.R} T={lg.T} | Speed: {self.speed} | {topo} | {state_str} "
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
            preset = LENIA_PRESET_NAMES[self.lenia_preset_idx]
            help_text = (
                f" [Space]Run [S]tep [R]and [C]lear [Enter]Seed | "
                f"[F/G]Species:{preset} | "
                f"░▒▓█ intensity | [+/-]Spd [T]orus [L]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Wolfram 1D elementary cellular automaton mode ---

    def _handle_wolfram_input(self, key: int) -> bool:
        """Handle input while in Wolfram 1D mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._wolfram_tick()
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Cycle through notable rules
        elif key in (ord("f"), curses.KEY_RIGHT):
            idx = -1
            for i, r in enumerate(self.wolfram_notable):
                if r == self.wolfram_rule:
                    idx = i
                    break
            if idx >= 0:
                self.wolfram_rule = self.wolfram_notable[(idx + 1) % len(self.wolfram_notable)]
            else:
                self.wolfram_rule = self.wolfram_notable[0]
            self._wolfram_reset()
            self._set_message(f"Rule {self.wolfram_rule}")
        elif key in (ord("g"), curses.KEY_LEFT):
            idx = -1
            for i, r in enumerate(self.wolfram_notable):
                if r == self.wolfram_rule:
                    idx = i
                    break
            if idx >= 0:
                self.wolfram_rule = self.wolfram_notable[(idx - 1) % len(self.wolfram_notable)]
            else:
                self.wolfram_rule = self.wolfram_notable[-1]
            self._wolfram_reset()
            self._set_message(f"Rule {self.wolfram_rule}")
        # Enter a specific rule number
        elif key == ord("#"):
            text = self._text_prompt("Rule number (0-255): ")
            if text:
                try:
                    num = int(text)
                    if 0 <= num <= 255:
                        self.wolfram_rule = num
                        self._wolfram_reset()
                        self._set_message(f"Rule {self.wolfram_rule}")
                    else:
                        self._set_message("Rule must be 0-255")
                except ValueError:
                    self._set_message("Invalid number")
        # Randomize initial row
        elif key == ord("r"):
            self._wolfram_reset(randomize=True)
            self._set_message("Randomized initial row")
        # Reset to single center cell
        elif key == ord("c"):
            self._wolfram_reset()
            self._set_message("Reset to center seed")
        # Exit Wolfram mode
        elif key == ord("W") or key == 27:
            self._stop_wolfram()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_wolfram(self) -> None:
        """Enter Wolfram 1D elementary CA mode."""
        self.running = False
        self.wolfram_mode = True
        self._wolfram_reset()
        self._set_message(
            f"WOLFRAM 1D — Rule {self.wolfram_rule} | [F/G]Cycle rules [#]Enter rule [Space]Run [W]Exit"
        )

    def _stop_wolfram(self) -> None:
        """Exit Wolfram 1D mode."""
        self.wolfram_mode = False
        self.running = False
        self.wolfram_rows.clear()
        self.wolfram_generation = 0
        self._set_message("Wolfram mode ended")

    def _wolfram_reset(self, randomize: bool = False) -> None:
        """Reset the Wolfram automaton with a fresh initial row."""
        max_h, max_w = self.stdscr.getmaxyx()
        width = max(1, max_w // 2)
        if randomize:
            row = [random.random() < 0.5 for _ in range(width)]
        else:
            row = [False] * width
            row[width // 2] = True
        self.wolfram_rows = [row]
        self.wolfram_generation = 0

    def _wolfram_apply_rule(self, left: bool, center: bool, right: bool) -> bool:
        """Apply the current Wolfram rule to a 3-cell neighborhood."""
        index = (int(left) << 2) | (int(center) << 1) | int(right)
        return bool(self.wolfram_rule & (1 << index))

    def _wolfram_tick(self) -> None:
        """Compute the next row of the Wolfram 1D automaton."""
        if not self.wolfram_rows:
            return
        prev = self.wolfram_rows[-1]
        width = len(prev)
        new_row = [False] * width
        for i in range(width):
            left = prev[i - 1] if i > 0 else False
            center = prev[i]
            right = prev[i + 1] if i < width - 1 else False
            new_row[i] = self._wolfram_apply_rule(left, center, right)
        self.wolfram_rows.append(new_row)
        self.wolfram_generation += 1

        # Limit stored rows to what fits on screen + a buffer
        max_h, _ = self.stdscr.getmaxyx()
        max_rows = max(1, max_h - 3)
        if len(self.wolfram_rows) > max_rows:
            self.wolfram_rows = self.wolfram_rows[-max_rows:]

    # --- multi-state automaton mode ---

    def _handle_multistate_input(self, key: int) -> bool:
        """Handle input while in multi-state automaton mode."""
        # Movement
        if key in (curses.KEY_UP, ord("k")):
            self.cursor_r = max(0, self.cursor_r - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor_r = min(self.grid.height - 1, self.cursor_r + 1)
        elif key in (curses.KEY_LEFT, ord("h")):
            self.cursor_c = max(0, self.cursor_c - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            self.cursor_c = min(self.grid.width - 1, self.cursor_c + 1)
        # Run / pause
        elif key == ord(" "):
            self.running = not self.running
        # Step
        elif key == ord("s"):
            if not self.running:
                self._multistate_tick()
        # Randomize
        elif key == ord("r"):
            self._multistate_randomize()
            self.multistate_gen = 0
            self._set_message("Randomized")
        # Clear
        elif key == ord("c"):
            if self.multistate_grid:
                self.multistate_grid.clear()
            self.multistate_gen = 0
            self._set_message("Cleared")
        # Toggle cell (cycle through states)
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.multistate_grid:
                atype = MULTISTATE_TYPES[self.multistate_type_idx]
                if atype == "Brian's Brain":
                    self.multistate_grid.toggle_cell_brians_brain(self.cursor_r, self.cursor_c)
                elif atype == "Wireworld":
                    self.multistate_grid.toggle_cell_wireworld(self.cursor_r, self.cursor_c)
                elif atype == "Langton's Ant":
                    self.multistate_grid.toggle_cell_langtons_ant(self.cursor_r, self.cursor_c)
        # Cycle automaton type with F/G
        elif key == ord("f"):
            self.multistate_type_idx = (self.multistate_type_idx + 1) % len(MULTISTATE_TYPES)
            atype = MULTISTATE_TYPES[self.multistate_type_idx]
            if atype == "Life":
                self._stop_multistate()
            else:
                self._switch_multistate_type()
        elif key == ord("g"):
            self.multistate_type_idx = (self.multistate_type_idx - 1) % len(MULTISTATE_TYPES)
            atype = MULTISTATE_TYPES[self.multistate_type_idx]
            if atype == "Life":
                self._stop_multistate()
            else:
                self._switch_multistate_type()
        # Speed control
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Toroidal toggle
        elif key == ord("t"):
            if self.multistate_grid:
                self.multistate_grid.toroidal = not self.multistate_grid.toroidal
                mode = "ON" if self.multistate_grid.toroidal else "OFF"
                self._set_message(f"Toroidal wrapping {mode}")
        # Quit
        elif key == ord("q"):
            return False
        # Exit multi-state mode
        elif key == ord("X") or key == 27:
            self._stop_multistate()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_multistate(self) -> None:
        """Enter multi-state automaton mode, prompting for type."""
        # Start with Brian's Brain (index 1)
        self.multistate_type_idx = 1
        self.running = False
        self.multistate_mode = True
        self.multistate_gen = 0
        self.multistate_grid = MultiStateGrid(self.grid.width, self.grid.height)
        self.multistate_grid.toroidal = self.grid.toroidal
        self.multistate_grid.from_life_grid(self.grid, MULTISTATE_TYPES[self.multistate_type_idx])
        atype = MULTISTATE_TYPES[self.multistate_type_idx]
        self._set_message(
            f"{atype} — [F/G]Cycle type [Space]Run [S]tep [R]and [Enter]Toggle cell [X]Exit"
        )

    def _stop_multistate(self) -> None:
        """Exit multi-state automaton mode."""
        self.multistate_mode = False
        self.multistate_type_idx = 0
        self.running = False
        self.multistate_grid = None
        self.multistate_gen = 0
        self._set_message("Multi-state mode ended")

    def _switch_multistate_type(self) -> None:
        """Switch to a different multi-state automaton type."""
        atype = MULTISTATE_TYPES[self.multistate_type_idx]
        self.multistate_gen = 0
        self.running = False
        if self.multistate_grid:
            self.multistate_grid.clear()
        else:
            self.multistate_grid = MultiStateGrid(self.grid.width, self.grid.height)
            self.multistate_grid.toroidal = self.grid.toroidal
        self.multistate_grid.from_life_grid(self.grid, atype)
        self._set_message(
            f"{atype} — [F/G]Cycle type [Space]Run [S]tep [R]and [Enter]Toggle cell [X]Exit"
        )

    def _multistate_tick(self) -> None:
        """Advance one generation of the multi-state automaton."""
        if not self.multistate_grid:
            return
        atype = MULTISTATE_TYPES[self.multistate_type_idx]
        if atype == "Brian's Brain":
            self.multistate_grid.tick_brians_brain()
        elif atype == "Wireworld":
            self.multistate_grid.tick_wireworld()
        elif atype == "Langton's Ant":
            self.multistate_grid.tick_langtons_ant()
        self.multistate_gen += 1

    def _multistate_randomize(self) -> None:
        """Randomize the multi-state grid for the current type."""
        if not self.multistate_grid:
            return
        atype = MULTISTATE_TYPES[self.multistate_type_idx]
        if atype == "Brian's Brain":
            self.multistate_grid.randomize_brians_brain()
        elif atype == "Wireworld":
            self.multistate_grid.randomize_wireworld()
        elif atype == "Langton's Ant":
            self.multistate_grid.randomize_langtons_ant()

    # --- falling sand simulation mode ---

    def _handle_sand_input(self, key: int) -> bool:
        """Handle input while in falling sand mode."""
        # Movement
        if key in (curses.KEY_UP, ord("k")):
            self.cursor_r = max(0, self.cursor_r - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor_r = min(self.grid.height - 1, self.cursor_r + 1)
        elif key in (curses.KEY_LEFT, ord("h")):
            self.cursor_c = max(0, self.cursor_c - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            self.cursor_c = min(self.grid.width - 1, self.cursor_c + 1)
        # Run / pause
        elif key == ord(" "):
            self.running = not self.running
        # Step
        elif key == ord("s"):
            if not self.running:
                self._sand_tick()
        # Place material at cursor
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.sand_grid:
                mat = SAND_MATERIAL_IDS[self.sand_material_idx]
                self._sand_place(self.cursor_r, self.cursor_c, mat)
        # Erase at cursor
        elif key == ord("d"):
            if self.sand_grid:
                self._sand_place(self.cursor_r, self.cursor_c, MAT_EMPTY)
        # Cycle material with F/G
        elif key == ord("f"):
            self.sand_material_idx = (self.sand_material_idx + 1) % len(SAND_MATERIALS)
            self._set_message(f"Material: {SAND_MATERIALS[self.sand_material_idx]}")
        elif key == ord("g"):
            self.sand_material_idx = (self.sand_material_idx - 1) % len(SAND_MATERIALS)
            self._set_message(f"Material: {SAND_MATERIALS[self.sand_material_idx]}")
        # Brush size
        elif key == ord("z"):
            self.sand_brush_size = max(1, self.sand_brush_size - 1)
            self._set_message(f"Brush size: {self.sand_brush_size}")
        elif key == ord("Z"):
            self.sand_brush_size = min(5, self.sand_brush_size + 1)
            self._set_message(f"Brush size: {self.sand_brush_size}")
        # Randomize
        elif key == ord("r"):
            if self.sand_grid:
                self.sand_grid.randomize()
                self.sand_gen = 0
                self._set_message("Randomized")
        # Clear
        elif key == ord("c"):
            if self.sand_grid:
                self.sand_grid.clear()
                self.sand_gen = 0
                self._set_message("Cleared")
        # Speed control
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Quit
        elif key == ord("q"):
            return False
        # Exit sand mode
        elif key == ord("F") or key == 27:
            self._stop_sand()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_sand(self) -> None:
        """Enter falling sand simulation mode."""
        self.sand_mode = True
        self.running = False
        self.sand_gen = 0
        self.sand_material_idx = 0
        self.sand_grid = SandGrid(self.grid.width, self.grid.height)
        self._set_message(
            "Falling Sand — [Enter]Place [F/G]Material [Space]Run [S]tep [R]and [F]Exit"
        )

    def _stop_sand(self) -> None:
        """Exit falling sand simulation mode."""
        self.sand_mode = False
        self.running = False
        self.sand_grid = None
        self.sand_gen = 0
        self._set_message("Sand mode ended")

    def _sand_tick(self) -> None:
        """Advance one physics step of the sand simulation."""
        if self.sand_grid:
            self.sand_grid.tick()
            self.sand_gen += 1

    def _sand_place(self, r: int, c: int, mat: int) -> None:
        """Place material at position using brush size."""
        if not self.sand_grid:
            return
        radius = self.sand_brush_size - 1
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.sand_grid.height and 0 <= nc < self.sand_grid.width:
                    self.sand_grid.set(nr, nc, mat)

    def _draw_sand(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the falling sand simulation grid."""
        if not self.sand_grid:
            return
        sg = self.sand_grid

        # Material color pair mapping
        mat_color = {
            MAT_SAND: 29,
            MAT_WATER: 30,
            MAT_FIRE: 31,
            MAT_STONE: 32,
            MAT_PLANT: 33,
        }

        for screen_r in range(min(grid_rows, sg.height)):
            r = screen_r + self.view_r
            if r >= sg.height:
                break
            for screen_c in range(min(grid_cols, sg.width)):
                c = screen_c + self.view_c
                if c >= sg.width:
                    break
                x = screen_c * 2
                if x + 1 >= max_w:
                    break

                mat = sg.cells[r][c]
                is_cursor = (r == self.cursor_r and c == self.cursor_c)

                if is_cursor:
                    attr = curses.A_REVERSE
                    if self.use_color:
                        # Show selected material color at cursor
                        sel_mat = SAND_MATERIAL_IDS[self.sand_material_idx]
                        attr |= curses.color_pair(mat_color.get(sel_mat, 29))
                    ch = SAND_CHARS.get(mat, "▒▒") if mat != MAT_EMPTY else "▒▒"
                elif mat != MAT_EMPTY:
                    ch = SAND_CHARS.get(mat, "██")
                    pair = mat_color.get(mat, 0)
                    attr = curses.color_pair(pair) if self.use_color else 0
                    if mat == MAT_FIRE:
                        attr |= curses.A_BOLD
                else:
                    ch, attr = "  ", 0

                try:
                    self.stdscr.addstr(screen_r, x, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            state_str = "RUNNING" if self.running else "PAUSED"
            counts = sg.count_material()
            total = sum(counts.values())
            parts = []
            for mid, name in zip(SAND_MATERIAL_IDS, SAND_MATERIALS):
                cnt = counts.get(mid, 0)
                if cnt > 0:
                    parts.append(f"{name}:{cnt}")
            breakdown = " ".join(parts) if parts else "empty"
            sel_name = SAND_MATERIALS[self.sand_material_idx]
            status = (
                f" Falling Sand | Gen: {self.sand_gen} | Particles: {total} ({breakdown}) | "
                f"Brush: {sel_name} sz={self.sand_brush_size} | Speed: {self.speed} | {state_str} "
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
            legend = "Sand=░░ Water=~~ Fire=▲▲ Stone=██ Plant=♣♣"
            help_text = (
                f" [Space]Run [S]tep [Enter]Place [D]elete [F/G]Mat:{SAND_MATERIALS[self.sand_material_idx]} | "
                f"[z/Z]BrushSz [R]and [C]lear | {legend} | "
                f"[+/-]Spd [F]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Reaction-Diffusion (Gray-Scott) mode ---

    def _handle_rd_input(self, key: int) -> bool:
        """Handle input while in reaction-diffusion mode."""
        if key == ord("q"):
            return False
        # Run / pause
        elif key == ord(" "):
            self.running = not self.running
        # Step
        elif key == ord("s"):
            if not self.running:
                self._rd_tick()
        # Randomize
        elif key == ord("r"):
            if self.rd_grid:
                self.rd_grid.seed_random_spots()
                self.rd_gen = 0
                self._set_message("Randomized")
        # Clear
        elif key == ord("c"):
            if self.rd_grid:
                self.rd_grid.clear()
                self.rd_gen = 0
                self._set_message("Cleared")
        # Seed center
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.rd_grid:
                self.rd_grid.seed_center()
                self.rd_gen = 0
                self._set_message("Seeded center")
        # Cycle preset with F/G
        elif key == ord("f"):
            self.rd_preset_idx = (self.rd_preset_idx + 1) % len(RD_PRESET_NAMES)
            self._switch_rd_preset()
        elif key == ord("g"):
            self.rd_preset_idx = (self.rd_preset_idx - 1) % len(RD_PRESET_NAMES)
            self._switch_rd_preset()
        # Speed control
        elif key in (ord("+"), ord("="), ord("]")):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key in (ord("-"), ord("_"), ord("[")):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Toroidal toggle
        elif key == ord("t"):
            if self.rd_grid:
                self.rd_grid.toroidal = not self.rd_grid.toroidal
                mode = "ON" if self.rd_grid.toroidal else "OFF"
                self._set_message(f"Toroidal wrapping {mode}")
        # Exit RD mode
        elif key == ord("R") or key == 27:
            self._stop_rd()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_rd(self) -> None:
        """Enter reaction-diffusion (Gray-Scott) mode."""
        self.running = False
        self.rd_mode = True
        self.rd_gen = 0
        self.rd_preset_idx = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(1, max_w // 2)
        h = max(1, max_h - 3)
        self.rd_grid = ReactionDiffusionGrid(w, h)
        self.rd_grid.seed_center()
        preset = RD_PRESET_NAMES[self.rd_preset_idx]
        self._set_message(
            f"Reaction-Diffusion — {preset} | [F/G]Preset [Space]Run [S]tep [R]and [Enter]Seed [R]Exit"
        )

    def _stop_rd(self) -> None:
        """Exit reaction-diffusion mode."""
        self.rd_mode = False
        self.running = False
        self.rd_grid = None
        self.rd_gen = 0
        self._set_message("Reaction-Diffusion mode ended")

    def _switch_rd_preset(self) -> None:
        """Switch to a different Gray-Scott preset."""
        preset = RD_PRESET_NAMES[self.rd_preset_idx]
        if self.rd_grid:
            self.rd_grid.apply_preset(preset)
            self.rd_grid.seed_center()
        self.rd_gen = 0
        self.running = False
        self._set_message(
            f"RD — {preset} | f={self.rd_grid.f:.4f} k={self.rd_grid.k:.4f}"
            if self.rd_grid else f"RD — {preset}"
        )

    def _rd_tick(self) -> None:
        """Advance one reaction-diffusion generation."""
        if self.rd_grid:
            self.rd_grid.tick()
            self.rd_gen += 1

    def _rd_cell_attr(self, v_value: float) -> tuple[str, int]:
        """Return (shade_char, curses attr) for V concentration in [0, 1]."""
        if v_value < 0.01:
            return "  ", 0
        # Map to shade index (1-4)
        idx = min(4, max(1, int(v_value * 4.99)))
        shade = RD_SHADES[idx]
        ch = shade + shade  # double-wide for square cells
        # Color gradient based on V concentration
        if v_value < 0.1:
            pair = 34  # blue/dim
            extra = curses.A_DIM
        elif v_value < 0.2:
            pair = 35  # cyan
            extra = 0
        elif v_value < 0.35:
            pair = 36  # green
            extra = 0
        elif v_value < 0.5:
            pair = 37  # yellow
            extra = 0
        else:
            pair = 38  # red/bright
            extra = curses.A_BOLD
        attr = (curses.color_pair(pair) | extra) if self.use_color else extra
        return ch, attr

    def _draw_rd(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the reaction-diffusion grid."""
        if not self.rd_grid:
            return
        rg = self.rd_grid

        for screen_r in range(min(grid_rows, rg.height)):
            for screen_c in range(min(grid_cols, rg.width)):
                x = screen_c * 2
                if x + 1 >= max_w:
                    break
                value = rg.V[screen_r][screen_c]
                ch, attr = self._rd_cell_attr(value)
                try:
                    self.stdscr.addstr(screen_r, x, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset = RD_PRESET_NAMES[self.rd_preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            topo = "Torus" if rg.toroidal else "Bounded"
            mass = rg.population()
            active = rg.active_count()
            status = (
                f" Gray-Scott RD: {preset} | Gen: {self.rd_gen} | "
                f"V-mass: {mass:.1f} Active: {active} | "
                f"f={rg.f:.4f} k={rg.k:.4f} | Speed: {self.speed} | {topo} | {state_str} "
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
            preset = RD_PRESET_NAMES[self.rd_preset_idx]
            help_text = (
                f" [Space]Run [S]tep [R]and [C]lear [Enter]Seed | "
                f"[F/G]Preset:{preset} | "
                f"░▒▓█ V concentration | [+/-]Spd [T]orus [R]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Particle Life mode ---

    def _handle_pl_input(self, key: int) -> bool:
        """Handle input while in particle life mode."""
        if key == ord("q"):
            return False
        # Run / pause
        elif key == ord(" "):
            self.running = not self.running
        # Step
        elif key == ord("s"):
            if not self.running:
                self._pl_tick()
        # Randomize particles
        elif key == ord("r"):
            if self.pl_world:
                self.pl_world.seed_random()
                self.pl_gen = 0
                self._set_message("Particles randomized")
        # New interaction matrix
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            if self.pl_world:
                self.pl_world.randomize_matrix()
                self.pl_world.seed_random()
                self.pl_gen = 0
                self._set_message("New interaction matrix")
        # Clear (reset everything)
        elif key == ord("c"):
            if self.pl_world:
                self.pl_world.randomize_matrix()
                self.pl_world.seed_random()
                self.pl_gen = 0
                self._set_message("Cleared & reset")
        # Adjust particle count
        elif key == ord("]") or key == ord("+") or key == ord("="):
            if self.pl_world:
                self.pl_world.n_particles = min(600, self.pl_world.n_particles + 50)
                self.pl_world.seed_random()
                self.pl_gen = 0
                self._set_message(f"Particles: {self.pl_world.n_particles}")
        elif key == ord("[") or key == ord("-") or key == ord("_"):
            if self.pl_world:
                self.pl_world.n_particles = max(50, self.pl_world.n_particles - 50)
                self.pl_world.seed_random()
                self.pl_gen = 0
                self._set_message(f"Particles: {self.pl_world.n_particles}")
        # Adjust friction
        elif key == ord("f"):
            if self.pl_world:
                self.pl_world.friction = min(0.5, self.pl_world.friction + 0.01)
                self._set_message(f"Friction: {self.pl_world.friction:.2f}")
        elif key == ord("g"):
            if self.pl_world:
                self.pl_world.friction = max(0.0, self.pl_world.friction - 0.01)
                self._set_message(f"Friction: {self.pl_world.friction:.2f}")
        # Speed control
        elif key == ord(">"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("<"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Particle Life mode
        elif key == ord("P") or key == 27:
            self._stop_pl()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_pl(self) -> None:
        """Enter particle life mode."""
        self.running = False
        self.pl_mode = True
        self.pl_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        # World size in pixel-equivalent units (each terminal cell = 2 pixels wide)
        w = max(1, max_w)
        h = max(1, max_h - 3)
        self.pl_world = ParticleLifeWorld(float(w), float(h), n_particles=300)
        self._set_message(
            "Particle Life — [Space]Run [S]tep [R]and [Enter]NewMatrix [P]Exit"
        )

    def _stop_pl(self) -> None:
        """Exit particle life mode."""
        self.pl_mode = False
        self.running = False
        self.pl_world = None
        self.pl_gen = 0
        self._set_message("Particle Life mode ended")

    def _pl_tick(self) -> None:
        """Advance one particle life generation."""
        if self.pl_world:
            self.pl_world.tick()
            self.pl_gen += 1

    PL_COLOR_PAIRS = [39, 40, 41, 42, 43, 44]  # color pairs for particle types

    def _draw_pl(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the particle life world."""
        if not self.pl_world:
            return
        pw = self.pl_world

        # Render particles onto a screen buffer
        # Each terminal cell is 1 char wide, particles have continuous coords
        # We'll draw each particle as a single character at its position
        drawn: dict[tuple[int, int], int] = {}  # (row, col) -> particle type

        for i in range(pw.n_particles):
            # Map continuous coords to screen coords
            screen_c = int(pw.px[i])
            screen_r = int(pw.py[i])
            if 0 <= screen_r < grid_rows and 0 <= screen_c < max_w - 1:
                drawn[(screen_r, screen_c)] = pw.pt[i]

        for (r, c), t in drawn.items():
            pair = self.PL_COLOR_PAIRS[t % len(self.PL_COLOR_PAIRS)]
            attr = curses.color_pair(pair) | curses.A_BOLD if self.use_color else curses.A_BOLD
            try:
                self.stdscr.addstr(r, c, PL_SHADES, attr)
            except curses.error:
                pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            state_str = "RUNNING" if self.running else "PAUSED"
            counts = pw.population_by_type()
            type_str = " ".join(f"{PL_TYPE_NAMES[i][0]}:{counts[i]}" for i in range(pw.num_types))
            status = (
                f" Particle Life | Gen: {self.pl_gen} | "
                f"N={pw.n_particles} Friction={pw.friction:.2f} | "
                f"{type_str} | Speed: {self.speed} | {state_str} "
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
            help_text = (
                " [Space]Run [S]tep [R]and [C]lear [Enter]NewMatrix | "
                "[F/G]Friction [+/-]Particles [</>]Spd | [P]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Wa-Tor Ecosystem mode ---

    def _handle_eco_input(self, key: int) -> bool:
        """Handle input while in ecosystem mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._eco_tick()
        elif key == ord("r"):
            if self.eco_world:
                self.eco_world.seed()
                self.eco_gen = 0
                self._set_message("Ocean repopulated")
        elif key == ord("c"):
            if self.eco_world:
                self.eco_world.seed()
                self.eco_gen = 0
                self._set_message("Cleared & reset")
        # Adjust fish breed time
        elif key == ord("]") or key == ord("+") or key == ord("="):
            if self.eco_world:
                self.eco_world.fish_breed = min(20, self.eco_world.fish_breed + 1)
                self._set_message(f"Fish breed: {self.eco_world.fish_breed}")
        elif key == ord("[") or key == ord("-") or key == ord("_"):
            if self.eco_world:
                self.eco_world.fish_breed = max(1, self.eco_world.fish_breed - 1)
                self._set_message(f"Fish breed: {self.eco_world.fish_breed}")
        # Adjust shark breed time
        elif key == ord("b"):
            if self.eco_world:
                self.eco_world.shark_breed = min(30, self.eco_world.shark_breed + 1)
                self._set_message(f"Shark breed: {self.eco_world.shark_breed}")
        elif key == ord("n"):
            if self.eco_world:
                self.eco_world.shark_breed = max(1, self.eco_world.shark_breed - 1)
                self._set_message(f"Shark breed: {self.eco_world.shark_breed}")
        # Adjust shark starve time
        elif key == ord("f"):
            if self.eco_world:
                self.eco_world.shark_starve = min(20, self.eco_world.shark_starve + 1)
                self._set_message(f"Shark starve: {self.eco_world.shark_starve}")
        elif key == ord("g"):
            if self.eco_world:
                self.eco_world.shark_starve = max(1, self.eco_world.shark_starve - 1)
                self._set_message(f"Shark starve: {self.eco_world.shark_starve}")
        # Speed control
        elif key == ord(">"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("<"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit ecosystem mode
        elif key == ord("E") or key == 27:
            self._stop_eco()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_eco(self) -> None:
        """Enter ecosystem (Wa-Tor) mode."""
        self.running = False
        self.eco_mode = True
        self.eco_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(1, max_w - 1)
        h = max(1, max_h - 3)
        self.eco_world = WaTorWorld(w, h)
        self._set_message(
            "Wa-Tor Ecosystem — [Space]Run [S]tep [R]eset [E]xit"
        )

    def _stop_eco(self) -> None:
        """Exit ecosystem mode."""
        self.eco_mode = False
        self.running = False
        self.eco_world = None
        self.eco_gen = 0
        self._set_message("Ecosystem mode ended")

    def _eco_tick(self) -> None:
        """Advance one ecosystem generation."""
        if self.eco_world:
            self.eco_world.tick()
            self.eco_gen += 1

    def _draw_eco(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Wa-Tor ecosystem world."""
        if not self.eco_world:
            return
        ew = self.eco_world

        # Draw grid
        for r in range(min(grid_rows, ew.height)):
            line_parts: list[tuple[str, int]] = []
            for c in range(min(max_w - 1, ew.width)):
                cell = ew.grid[r][c]
                if cell == WATOR_FISH:
                    ch = WATOR_CHARS[WATOR_FISH]
                    attr = curses.color_pair(45) if self.use_color else 0
                elif cell == WATOR_SHARK:
                    ch = WATOR_CHARS[WATOR_SHARK]
                    attr = curses.color_pair(46) | curses.A_BOLD if self.use_color else curses.A_BOLD
                else:
                    ch = " "
                    attr = 0
                try:
                    self.stdscr.addstr(r, c, ch, attr)
                except curses.error:
                    pass

        # Population graph (sparkline in the rightmost columns)
        graph_w = min(40, max_w // 4)
        graph_x = max_w - graph_w - 1
        if graph_x > 10 and len(ew.fish_history) > 1:
            # Normalize histories to fit in grid_rows
            fish_h = ew.fish_history[-graph_w:]
            shark_h = ew.shark_history[-graph_w:]
            max_pop = max(max(fish_h, default=1), max(shark_h, default=1), 1)
            for i, (fp, sp) in enumerate(zip(fish_h, shark_h)):
                col = graph_x + i
                if col >= max_w - 1:
                    break
                fish_row = grid_rows - 1 - int((fp / max_pop) * (grid_rows - 1))
                shark_row = grid_rows - 1 - int((sp / max_pop) * (grid_rows - 1))
                fish_row = max(0, min(grid_rows - 1, fish_row))
                shark_row = max(0, min(grid_rows - 1, shark_row))
                try:
                    self.stdscr.addstr(
                        fish_row, col, ".",
                        curses.color_pair(45) if self.use_color else 0
                    )
                    self.stdscr.addstr(
                        shark_row, col, "x",
                        curses.color_pair(46) if self.use_color else 0
                    )
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            fish_count, shark_count = ew.population()
            state_str = "RUNNING" if self.running else "PAUSED"
            status = (
                f" Wa-Tor | Gen: {self.eco_gen} | "
                f"Fish: {fish_count} Sharks: {shark_count} | "
                f"Breed F:{ew.fish_breed} S:{ew.shark_breed} "
                f"Starve:{ew.shark_starve} | "
                f"Speed: {self.speed} | {state_str} "
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
            help_text = (
                " [Space]Run [S]tep [R]eset [C]lear | "
                "[+/-]FishBreed [B/N]SharkBreed [F/G]Starve [</>]Spd | [E]xit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Physarum (slime mold) mode ---

    def _handle_physarum_input(self, key: int) -> bool:
        """Handle input while in Physarum mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._physarum_tick()
        elif key == ord("r"):
            if self.physarum_world:
                self.physarum_world.seed()
                self.physarum_gen = 0
                self._set_message("Agents scattered randomly")
        elif key == ord("c"):
            if self.physarum_world:
                self.physarum_world.seed()
                self.physarum_gen = 0
                self._set_message("Cleared & reset")
        # Cycle preset forward
        elif key == ord("p") or key == ord("n"):
            if self.physarum_world:
                direction = 1 if key == ord("n") else -1
                name = self.physarum_world.cycle_preset(direction)
                self.physarum_preset_idx = self.physarum_world.preset_idx
                self._set_message(f"Preset: {name}")
        # Seed patterns
        elif key == ord("1"):
            if self.physarum_world:
                self.physarum_world.seed()
                self.physarum_gen = 0
                self._set_message("Seed: random scatter")
        elif key == ord("2"):
            if self.physarum_world:
                self.physarum_world.seed_ring()
                self.physarum_gen = 0
                self._set_message("Seed: ring inward")
        elif key == ord("3"):
            if self.physarum_world:
                self.physarum_world.seed_center()
                self.physarum_gen = 0
                self._set_message("Seed: center burst")
        # Adjust deposit amount
        elif key == ord("]") or key == ord("+") or key == ord("="):
            if self.physarum_world:
                self.physarum_world.deposit_amount = min(
                    20.0, self.physarum_world.deposit_amount + 0.5
                )
                self._set_message(f"Deposit: {self.physarum_world.deposit_amount:.1f}")
        elif key == ord("[") or key == ord("-") or key == ord("_"):
            if self.physarum_world:
                self.physarum_world.deposit_amount = max(
                    0.5, self.physarum_world.deposit_amount - 0.5
                )
                self._set_message(f"Deposit: {self.physarum_world.deposit_amount:.1f}")
        # Adjust decay rate
        elif key == ord("d"):
            if self.physarum_world:
                self.physarum_world.decay_rate = min(
                    0.5, self.physarum_world.decay_rate + 0.01
                )
                self._set_message(f"Decay: {self.physarum_world.decay_rate:.2f}")
        elif key == ord("f"):
            if self.physarum_world:
                self.physarum_world.decay_rate = max(
                    0.01, self.physarum_world.decay_rate - 0.01
                )
                self._set_message(f"Decay: {self.physarum_world.decay_rate:.2f}")
        # Speed control
        elif key == ord(">"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("<"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Physarum mode
        elif key == ord("S") or key == 27:
            self._stop_physarum()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_physarum(self) -> None:
        """Enter Physarum (slime mold) mode."""
        self.running = False
        self.physarum_mode = True
        self.physarum_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(1, max_w // 2)  # each cell rendered as 2 chars wide
        h = max(1, max_h - 3)
        preset = PHYSARUM_PRESET_NAMES[self.physarum_preset_idx]
        self.physarum_world = PhysarumWorld(w, h, preset=preset)
        self._set_message(
            "Physarum Slime Mold — [Space]Run [S]tep [S]hift+S Exit"
        )

    def _stop_physarum(self) -> None:
        """Exit Physarum mode."""
        self.physarum_mode = False
        self.running = False
        self.physarum_world = None
        self.physarum_gen = 0
        self._set_message("Physarum mode ended")

    def _physarum_tick(self) -> None:
        """Advance one Physarum generation."""
        if self.physarum_world:
            self.physarum_world.tick()
            self.physarum_gen += 1

    def _draw_physarum(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Physarum trail map with graded characters."""
        if not self.physarum_world:
            return
        pw = self.physarum_world
        shades = PHYSARUM_SHADES
        n_shades = len(shades)

        # Find max trail value for normalization
        mx = pw.max_trail()
        if mx < 0.001:
            mx = 1.0

        # Color tiers mapped to shade index
        # shades: 0=space, 1=., 2=·, 3=:, 4=░, 5=▒, 6=▓, 7=█
        color_tiers = [0, 47, 47, 48, 48, 49, 50, 51]

        for r in range(min(grid_rows, pw.height)):
            for c in range(min(grid_cols, pw.width)):
                v = pw.trail[r][c]
                # Map to shade index
                idx = int((v / mx) * (n_shades - 1))
                idx = max(0, min(n_shades - 1, idx))
                ch = shades[idx]
                if idx == 0:
                    continue  # skip empty cells
                sc = c * 2  # screen column (double-wide)
                if sc + 1 >= max_w:
                    break
                pair = color_tiers[idx]
                attr = curses.color_pair(pair) if self.use_color and pair > 0 else 0
                if idx >= n_shades - 2:
                    attr |= curses.A_BOLD
                try:
                    self.stdscr.addstr(r, sc, ch * 2, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = PHYSARUM_PRESET_NAMES[pw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            status = (
                f" Physarum | Gen: {self.physarum_gen} | "
                f"Agents: {pw.n_agents} | "
                f"Preset: {preset_name} | "
                f"Deposit: {pw.deposit_amount:.1f} Decay: {pw.decay_rate:.2f} | "
                f"Speed: {self.speed} | {state_str} "
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
            help_text = (
                " [Space]Run [S]tep [R]eset | "
                "[P/N]Preset [1]Random [2]Ring [3]Center | "
                "[+/-]Deposit [D/F]Decay [</>]Spd | [Shift+S]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Fluid Dynamics (Lattice Boltzmann) mode ---

    def _handle_fluid_input(self, key: int) -> bool:
        """Handle input while in Fluid Dynamics mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._fluid_tick()
        elif key == ord("r"):
            if self.fluid_world:
                self.fluid_world.reset()
                self.fluid_gen = 0
                self._set_message("Fluid reset to equilibrium")
        elif key == ord("c"):
            if self.fluid_world:
                self.fluid_world.clear_obstacles()
                self.fluid_world.reset()
                self.fluid_gen = 0
                self._set_message("Obstacles cleared & fluid reset")
        elif key == ord("o"):
            if self.fluid_world:
                self.fluid_world.clear_obstacles()
                self.fluid_world._place_default_obstacle()
                self.fluid_world.reset()
                self.fluid_gen = 0
                self._set_message("Default obstacle restored")
        # Cycle visualization mode
        elif key == ord("v"):
            viz_names = ["velocity", "vorticity", "density"]
            self.fluid_viz = (self.fluid_viz + 1) % 3
            self._set_message(f"Visualization: {viz_names[self.fluid_viz]}")
        # Cycle preset forward/back
        elif key == ord("p") or key == ord("n"):
            if self.fluid_world:
                direction = 1 if key == ord("n") else -1
                name = self.fluid_world.cycle_preset(direction)
                self.fluid_preset_idx = self.fluid_world.preset_idx
                self.fluid_world.reset()
                self.fluid_gen = 0
                self._set_message(f"Preset: {name}")
        # Cursor movement for obstacle placement
        elif key in (curses.KEY_UP, ord("k")):
            self.fluid_cursor_y = max(0, self.fluid_cursor_y - 1)
            if self.fluid_painting and self.fluid_world:
                self.fluid_world.set_obstacle(self.fluid_cursor_x, self.fluid_cursor_y, self.fluid_brush_size)
        elif key in (curses.KEY_DOWN, ord("j")):
            if self.fluid_world:
                self.fluid_cursor_y = min(self.fluid_world.height - 1, self.fluid_cursor_y + 1)
                if self.fluid_painting:
                    self.fluid_world.set_obstacle(self.fluid_cursor_x, self.fluid_cursor_y, self.fluid_brush_size)
        elif key in (curses.KEY_LEFT, ord("h")):
            self.fluid_cursor_x = max(0, self.fluid_cursor_x - 1)
            if self.fluid_painting and self.fluid_world:
                self.fluid_world.set_obstacle(self.fluid_cursor_x, self.fluid_cursor_y, self.fluid_brush_size)
        elif key in (curses.KEY_RIGHT, ord("l")):
            if self.fluid_world:
                self.fluid_cursor_x = min(self.fluid_world.width - 1, self.fluid_cursor_x + 1)
                if self.fluid_painting:
                    self.fluid_world.set_obstacle(self.fluid_cursor_x, self.fluid_cursor_y, self.fluid_brush_size)
        # Toggle obstacle at cursor
        elif key == 10 or key == 13:  # Enter
            if self.fluid_world:
                self.fluid_world.toggle_obstacle(self.fluid_cursor_x, self.fluid_cursor_y, self.fluid_brush_size)
        # Paint mode toggle
        elif key == ord("b"):
            self.fluid_painting = not self.fluid_painting
            self._set_message(f"Paint obstacles: {'ON' if self.fluid_painting else 'OFF'}")
        # Brush size
        elif key == ord("]") or key == ord("+") or key == ord("="):
            self.fluid_brush_size = min(8, self.fluid_brush_size + 1)
            self._set_message(f"Brush size: {self.fluid_brush_size}")
        elif key == ord("[") or key == ord("-") or key == ord("_"):
            self.fluid_brush_size = max(1, self.fluid_brush_size - 1)
            self._set_message(f"Brush size: {self.fluid_brush_size}")
        # Adjust inlet velocity
        elif key == ord("."):
            if self.fluid_world:
                self.fluid_world.inlet_velocity = min(0.25, self.fluid_world.inlet_velocity + 0.01)
                self._set_message(f"Inlet velocity: {self.fluid_world.inlet_velocity:.2f}")
        elif key == ord(","):
            if self.fluid_world:
                self.fluid_world.inlet_velocity = max(0.01, self.fluid_world.inlet_velocity - 0.01)
                self._set_message(f"Inlet velocity: {self.fluid_world.inlet_velocity:.2f}")
        # Adjust viscosity
        elif key == ord(">"):
            if self.fluid_world:
                self.fluid_world.viscosity = min(0.3, self.fluid_world.viscosity + 0.005)
                self.fluid_world.tau = 3.0 * self.fluid_world.viscosity + 0.5
                self.fluid_world.omega = 1.0 / self.fluid_world.tau
                self._set_message(f"Viscosity: {self.fluid_world.viscosity:.3f}")
        elif key == ord("<"):
            if self.fluid_world:
                self.fluid_world.viscosity = max(0.005, self.fluid_world.viscosity - 0.005)
                self.fluid_world.tau = 3.0 * self.fluid_world.viscosity + 0.5
                self.fluid_world.omega = 1.0 / self.fluid_world.tau
                self._set_message(f"Viscosity: {self.fluid_world.viscosity:.3f}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Fluid mode
        elif key == ord("D") or key == 27:
            self._stop_fluid()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_fluid(self) -> None:
        """Enter Fluid Dynamics (LBM) mode."""
        self.running = False
        self.fluid_mode = True
        self.fluid_gen = 0
        self.fluid_painting = False
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = FLUID_PRESET_NAMES[self.fluid_preset_idx]
        self.fluid_world = FluidWorld(w, h, preset=preset)
        self.fluid_cursor_x = w // 2
        self.fluid_cursor_y = h // 2
        self._set_message(
            "Fluid Dynamics (LBM) — [Space]Run [Enter]Obstacle [Shift+D]Exit"
        )

    def _stop_fluid(self) -> None:
        """Exit Fluid Dynamics mode."""
        self.fluid_mode = False
        self.running = False
        self.fluid_world = None
        self.fluid_gen = 0
        self.fluid_painting = False
        self._set_message("Fluid Dynamics mode ended")

    def _fluid_tick(self) -> None:
        """Advance one LBM step."""
        if self.fluid_world:
            self.fluid_world.tick()
            self.fluid_gen += 1

    def _draw_fluid(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the fluid field with color-coded visualization."""
        if not self.fluid_world:
            return
        fw = self.fluid_world
        shades = FLUID_SHADES
        n_shades = len(shades)
        viz = self.fluid_viz

        # Velocity color tiers: blue → cyan → green → yellow → red
        vel_colors = [0, 52, 53, 54, 55, 56, 56]
        # Vorticity: negative (blue) → zero → positive (red)
        vort_colors_neg = [52, 52, 53]   # blue/cyan for negative
        vort_colors_pos = [55, 56, 56]   # yellow/red for positive

        # Find normalization values
        max_val = 0.001
        rmin = 0.0  # used only for density viz
        if viz == 0:  # velocity
            max_val = max(0.001, fw.max_velocity())
        elif viz == 1:  # vorticity
            for y in range(fw.height):
                for x in range(fw.width):
                    if not fw.obstacle[y][x]:
                        v = abs(fw.curl(y, x))
                        if v > max_val:
                            max_val = v
        elif viz == 2:  # density
            rmin = 1e9
            rmax = -1e9
            for y in range(fw.height):
                for x in range(fw.width):
                    if not fw.obstacle[y][x]:
                        r = fw.rho[y][x]
                        if r < rmin:
                            rmin = r
                        if r > rmax:
                            rmax = r
            max_val = max(0.001, rmax - rmin)

        for r in range(min(grid_rows, fw.height)):
            for c in range(min(grid_cols, fw.width)):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                # Cursor highlight
                is_cursor = (c == self.fluid_cursor_x and r == self.fluid_cursor_y)

                # Obstacle
                if fw.obstacle[r][c]:
                    attr = curses.color_pair(57) | curses.A_BOLD if self.use_color else curses.A_REVERSE
                    if is_cursor:
                        attr = curses.color_pair(58) | curses.A_BOLD if self.use_color else curses.A_REVERSE
                    try:
                        self.stdscr.addstr(r, sc, "██", attr)
                    except curses.error:
                        pass
                    continue

                # Compute value and color based on visualization
                if viz == 0:  # velocity magnitude
                    val = fw.velocity_magnitude(r, c)
                    norm = val / max_val
                    norm = max(0.0, min(1.0, norm))
                    idx = int(norm * (n_shades - 1))
                    idx = max(0, min(n_shades - 1, idx))
                    pair = vel_colors[idx]
                elif viz == 1:  # vorticity
                    val = fw.curl(r, c)
                    norm = val / max_val  # -1 to 1
                    norm = max(-1.0, min(1.0, norm))
                    abs_norm = abs(norm)
                    idx = int(abs_norm * (n_shades - 1))
                    idx = max(0, min(n_shades - 1, idx))
                    if norm < 0:
                        pair = vort_colors_neg[min(2, int(abs_norm * 3))]
                    else:
                        pair = vort_colors_pos[min(2, int(abs_norm * 3))]
                else:  # density
                    val = fw.rho[r][c] - rmin
                    norm = val / max_val
                    norm = max(0.0, min(1.0, norm))
                    idx = int(norm * (n_shades - 1))
                    idx = max(0, min(n_shades - 1, idx))
                    pair = vel_colors[idx]

                ch = shades[idx]
                if idx == 0 and not is_cursor:
                    continue

                if is_cursor:
                    attr = curses.color_pair(58) | curses.A_BOLD if self.use_color else curses.A_REVERSE
                    ch = ch if idx > 0 else "+"
                else:
                    attr = curses.color_pair(pair) if self.use_color and pair > 0 else 0
                    if idx >= n_shades - 2:
                        attr |= curses.A_BOLD

                try:
                    self.stdscr.addstr(r, sc, ch * 2 if len(ch) == 1 else ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            viz_names = ["velocity", "vorticity", "density"]
            preset_name = FLUID_PRESET_NAMES[fw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            re_num = fw.reynolds_number()
            status = (
                f" Fluid LBM | Gen: {self.fluid_gen} | "
                f"Preset: {preset_name} | "
                f"Viz: {viz_names[self.fluid_viz]} | "
                f"Re≈{re_num:.0f} | "
                f"ν={fw.viscosity:.3f} U={fw.inlet_velocity:.2f} | "
                f"Speed: {self.speed} | {state_str} "
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
            help_text = (
                " [Space]Run [S]tep [R]eset | "
                "[Arrows]Move [Enter]Wall [B]rush | "
                "[P/N]Preset [V]iz [,/.]Vel [</>]Visc | "
                "[C]lear [O]bstacle | [Shift+D]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Ising Model (statistical mechanics) mode ---

    def _handle_ising_input(self, key: int) -> bool:
        """Handle input while in Ising Model mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._ising_tick()
        elif key == ord("r"):
            # Reset to random spins
            if self.ising_world:
                self.ising_world.reset_random()
                self.ising_gen = 0
                self._set_message("Reset to random spins")
        elif key == ord("a"):
            # Reset to all aligned up
            if self.ising_world:
                self.ising_world.reset_aligned(1)
                self.ising_gen = 0
                self._set_message("Reset to all spin-up")
        elif key == ord("z"):
            # Reset to all aligned down
            if self.ising_world:
                self.ising_world.reset_aligned(-1)
                self.ising_gen = 0
                self._set_message("Reset to all spin-down")
        # Temperature control: +/- fine, </> coarse
        elif key == ord(".") or key == ord("=") or key == ord("+"):
            if self.ising_world:
                self.ising_world.set_temperature(self.ising_world.temperature + 0.1)
                self._set_message(f"T = {self.ising_world.temperature:.2f}")
        elif key == ord(",") or key == ord("-") or key == ord("_"):
            if self.ising_world:
                self.ising_world.set_temperature(self.ising_world.temperature - 0.1)
                self._set_message(f"T = {self.ising_world.temperature:.2f}")
        elif key == ord(">"):
            if self.ising_world:
                self.ising_world.set_temperature(self.ising_world.temperature + 0.5)
                self._set_message(f"T = {self.ising_world.temperature:.2f}")
        elif key == ord("<"):
            if self.ising_world:
                self.ising_world.set_temperature(self.ising_world.temperature - 0.5)
                self._set_message(f"T = {self.ising_world.temperature:.2f}")
        # Cycle preset forward/back
        elif key == ord("p") or key == ord("n"):
            if self.ising_world:
                direction = 1 if key == ord("n") else -1
                name = self.ising_world.cycle_preset(direction)
                self.ising_preset_idx = self.ising_world.preset_idx
                self.ising_gen = 0
                self._set_message(f"Preset: {name} (T={self.ising_world.temperature:.3f})")
        # Sweeps per tick
        elif key == ord("]"):
            if self.ising_world:
                self.ising_world.sweeps_per_tick = min(20, self.ising_world.sweeps_per_tick + 1)
                self._set_message(f"Sweeps/tick: {self.ising_world.sweeps_per_tick}")
        elif key == ord("["):
            if self.ising_world:
                self.ising_world.sweeps_per_tick = max(1, self.ising_world.sweeps_per_tick - 1)
                self._set_message(f"Sweeps/tick: {self.ising_world.sweeps_per_tick}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Ising mode
        elif key == ord("I") or key == 27:
            self._stop_ising()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_ising(self) -> None:
        """Enter Ising Model mode."""
        self.running = False
        self.ising_mode = True
        self.ising_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = ISING_PRESET_NAMES[self.ising_preset_idx]
        self.ising_world = IsingWorld(w, h, preset=preset)
        self._set_message(
            "Ising Model — [Space]Run [,/.]Temp [P/N]Preset [Shift+I]Exit"
        )

    def _stop_ising(self) -> None:
        """Exit Ising Model mode."""
        self.ising_mode = False
        self.running = False
        self.ising_world = None
        self.ising_gen = 0
        self._set_message("Ising Model mode ended")

    def _ising_tick(self) -> None:
        """Advance one Ising Monte Carlo sweep."""
        if self.ising_world:
            self.ising_world.tick()
            self.ising_gen += 1

    def _draw_ising(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Ising spin lattice with color-coded spins."""
        if not self.ising_world:
            return
        iw = self.ising_world

        for r in range(min(grid_rows, iw.height)):
            for c in range(min(grid_cols, iw.width)):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                s = iw.spin[r][c]
                if s > 0:
                    # Spin up: cyan block
                    attr = curses.color_pair(59) | curses.A_BOLD if self.use_color else curses.A_BOLD
                    ch = "██"
                else:
                    # Spin down: red block
                    attr = curses.color_pair(60) if self.use_color else 0
                    ch = "░░"

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = ISING_PRESET_NAMES[iw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            mag = iw.magnetization
            eng = iw.energy
            Tc = 2.0 * abs(iw.J) / math.log(1.0 + math.sqrt(2.0))
            phase = "FERRO" if iw.temperature < Tc else "PARA"
            status = (
                f" Ising Model | Gen: {self.ising_gen} | "
                f"T={iw.temperature:.2f} (Tc≈{Tc:.2f}) {phase} | "
                f"M={mag:+.3f} E={eng:.3f} | "
                f"J={iw.J:+.1f} Sweeps:{iw.sweeps_per_tick} | "
                f"Speed: {self.speed} | {state_str} "
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
            help_text = (
                " [Space]Run [S]tep [R]andom [A]ll-up [Z]all-down | "
                "[,/.]Temp±0.1 [</>]±0.5 [P/N]Preset [[]Sweeps | "
                "[F]aster [D]slower | [Shift+I]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

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

    # --- evolve (genetic algorithm) mode ---

    def _start_evolve(self) -> None:
        """Prompt for fitness criterion and launch the genetic algorithm."""
        self.running = False
        choice = self._menu_prompt(
            "Evolve — select fitness goal:",
            ["1) Longevity (survive longest)",
             "2) Max Population (peak cells)",
             "3) Symmetry (bilateral balance)"],
        )
        if choice < 0:
            self._set_message("Evolve cancelled")
            return

        criteria = ["longevity", "max_population", "symmetry"]
        criterion = criteria[choice]

        # Determine region size (~1/4 of grid, clamped)
        rw = max(10, min(30, self.grid.width // 2))
        rh = max(10, min(30, self.grid.height // 2))

        evolver = PatternEvolver(
            region_w=rw,
            region_h=rh,
            pop_size=20,
            sim_steps=200,
            mutation_rate=0.05,
            density=0.25,
            birth=set(self.grid.birth),
            survival=set(self.grid.survival),
        )
        evolver.criterion = criterion
        evolver.initialize()

        self.evolver = evolver
        self.evolve_mode = True
        self.grid.clear()
        self.generation = 0
        self.history.clear()
        self.history_pos = -1
        self.pop_history.clear()
        self.heatmap.clear()

        # Place the first individual on the grid for visualization
        self._place_evolver_pattern(evolver.get_current_pattern())
        self._set_message(
            f"EVOLVING for {PatternEvolver.FITNESS_LABELS[criterion]} — [A] stop, [1/2/3] change goal"
        )

    def _stop_evolve(self) -> None:
        """Stop evolve mode, keeping the best pattern on the grid."""
        if self.evolver and self.evolver.best_ever_pattern:
            self.grid.clear()
            self._place_evolver_pattern(self.evolver.best_ever_pattern)
            self._set_message(
                f"Evolve stopped — best pattern placed (fitness: {self.evolver.best_ever_fitness:.0f})"
            )
        else:
            self._set_message("Evolve stopped")
        self.evolve_mode = False
        self.evolver = None

    def _evolve_tick(self) -> None:
        """Advance one step of the genetic algorithm per frame."""
        if not self.evolver:
            return

        if self.evolver.phase == "evaluating":
            idx, fitness = self.evolver.evaluate_one()
            # Show the pattern being evaluated on the grid
            self.grid.clear()
            self._place_evolver_pattern(self.evolver.population[idx])

            # Check if we finished evaluating all individuals
            if self.evolver.phase == "breeding":
                self.evolver.breed_next_generation()
                # Show the best pattern from the completed generation
                self.grid.clear()
                self._place_evolver_pattern(self.evolver.best_pattern)
        elif self.evolver.phase == "breeding":
            # Shouldn't normally reach here, but handle it
            self.evolver.breed_next_generation()

    def _place_evolver_pattern(self, pattern: set[tuple[int, int]]) -> None:
        """Place an evolver pattern centered on the grid."""
        if not pattern:
            return
        # Center the pattern on the grid
        min_r = min(r for r, _ in pattern)
        min_c = min(c for _, c in pattern)
        max_r = max(r for r, _ in pattern)
        max_c = max(c for _, c in pattern)
        pat_h = max_r - min_r + 1
        pat_w = max_c - min_c + 1
        offset_r = (self.grid.height - pat_h) // 2 - min_r
        offset_c = (self.grid.width - pat_w) // 2 - min_c
        for r, c in pattern:
            nr, nc = r + offset_r, c + offset_c
            if 0 <= nr < self.grid.height and 0 <= nc < self.grid.width:
                self.grid.cells.add((nr, nc))
                self.grid.ages[(nr, nc)] = 1
        # Center cursor on pattern
        self.cursor_r = self.grid.height // 2
        self.cursor_c = self.grid.width // 2

    def _menu_prompt(self, title: str, options: list[str]) -> int:
        """Show a numbered menu and return the selected index (0-based), or -1 on cancel."""
        curses.curs_set(0)
        self.stdscr.nodelay(False)
        max_h, max_w = self.stdscr.getmaxyx()

        while True:
            # Draw the menu at the bottom of the screen
            start_y = max(0, max_h - len(options) - 3)
            try:
                self.stdscr.move(start_y, 0)
                self.stdscr.clrtoeol()
                self.stdscr.addstr(
                    start_y, 0, f" {title}"[:max_w - 1],
                    curses.A_BOLD | (curses.color_pair(3) if self.use_color else curses.A_REVERSE),
                )
                for i, opt in enumerate(options):
                    y = start_y + 1 + i
                    if y < max_h:
                        self.stdscr.move(y, 0)
                        self.stdscr.clrtoeol()
                        self.stdscr.addstr(y, 0, f"  {opt}"[:max_w - 1])
                esc_y = start_y + 1 + len(options)
                if esc_y < max_h:
                    self.stdscr.move(esc_y, 0)
                    self.stdscr.clrtoeol()
                    self.stdscr.addstr(esc_y, 0, "  [Esc] Cancel"[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass
            self.stdscr.refresh()

            ch = self.stdscr.getch()
            if ch == 27:  # Escape
                self.stdscr.nodelay(True)
                self._update_timeout()
                return -1
            if ord("1") <= ch <= ord("9"):
                idx = ch - ord("1")
                if idx < len(options):
                    self.stdscr.nodelay(True)
                    self._update_timeout()
                    return idx

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

        if self.lenia_mode:
            self._draw_lenia(max_h, max_w, grid_rows, grid_cols)
        elif self.wolfram_mode:
            self._draw_wolfram(max_h, max_w, grid_rows, grid_cols)
        elif self.multistate_mode:
            self._draw_multistate(max_h, max_w, grid_rows, grid_cols)
        elif self.sand_mode:
            self._draw_sand(max_h, max_w, grid_rows, grid_cols)
        elif self.rd_mode:
            self._draw_rd(max_h, max_w, grid_rows, grid_cols)
        elif self.pl_mode:
            self._draw_pl(max_h, max_w, grid_rows, grid_cols)
        elif self.eco_mode:
            self._draw_eco(max_h, max_w, grid_rows, grid_cols)
        elif self.physarum_mode:
            self._draw_physarum(max_h, max_w, grid_rows, grid_cols)
        elif self.fluid_mode:
            self._draw_fluid(max_h, max_w, grid_rows, grid_cols)
        elif self.ising_mode:
            self._draw_ising(max_h, max_w, grid_rows, grid_cols)
        elif self.split_mode:
            self._draw_split(max_h, max_w, grid_rows, grid_cols)
        elif self.blueprint_mode:
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

        # Precompute heatmap max for normalization
        heatmap_max = max(self.heatmap.values()) if (self.heatmap_mode and self.heatmap) else 0

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
                heat = self.heatmap.get((r, c), 0) if self.heatmap_mode else 0

                if is_cursor:
                    attr = curses.A_REVERSE
                    if self.use_color:
                        attr |= curses.color_pair(2)
                    ch = "██" if is_alive else "▒▒"
                elif self.heatmap_mode and heat > 0 and self.use_color:
                    # Heatmap rendering — show heat gradient for any cell that was ever alive
                    pair, extra = self._heatmap_color_pair(heat, heatmap_max)
                    attr = curses.color_pair(pair) | extra
                    ch = "██" if is_alive else "░░"
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
            heat_section = f" | HEATMAP({len(self.heatmap)} cells)" if self.heatmap_mode else ""
            evolve_section = f" | {self.evolver.status_text()}" if self.evolve_mode and self.evolver else ""
            status = (
                f" Gen: {self.generation} | Cells: {len(self.grid.cells)}{spark_section} | "
                f"Rule: {rule_info} | Speed: {self.speed} | {topo} | {hist_info} | {state}{brush_section}{heat_section}{evolve_section} "
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
                f"[F/G]Rule [D]ash [H]eat [A]Evolve [M]Split [W]olfram [Shift+X]Multi [B]lue [x]Del [L]RLE [+/-]Spd [T]orus [</>]Rew [w]Save [O]Load"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    def _multistate_cell_attr(self, state: int, automaton_type: str) -> tuple[str, int]:
        """Return (character, curses attr) for a multi-state cell."""
        if automaton_type == "Brian's Brain":
            if state == BB_ON:
                attr = (curses.color_pair(17) | curses.A_BOLD) if self.use_color else curses.A_BOLD
                return "██", attr
            elif state == BB_DYING:
                attr = curses.color_pair(18) if self.use_color else curses.A_DIM
                return "▒▒", attr
        elif automaton_type == "Wireworld":
            if state == WW_HEAD:
                attr = (curses.color_pair(19) | curses.A_BOLD) if self.use_color else curses.A_BOLD
                return "██", attr
            elif state == WW_TAIL:
                attr = curses.color_pair(20) if self.use_color else curses.A_DIM
                return "██", attr
            elif state == WW_CONDUCTOR:
                attr = curses.color_pair(21) if self.use_color else curses.A_NORMAL
                return "░░", attr
        elif automaton_type == "Langton's Ant":
            if state == LA_BLACK:
                attr = (curses.color_pair(22) | curses.A_BOLD) if self.use_color else curses.A_BOLD
                return "██", attr
        return "  ", 0

    def _draw_multistate(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the multi-state automaton grid."""
        if not self.multistate_grid:
            return
        atype = MULTISTATE_TYPES[self.multistate_type_idx]
        mg = self.multistate_grid

        # Build ant position set for fast lookup during rendering
        ant_positions: set[tuple[int, int]] = set()
        if atype == "Langton's Ant" and hasattr(mg, "ants"):
            for ar, ac, _ad in mg.ants:
                ant_positions.add((ar, ac))

        for screen_r in range(min(grid_rows, mg.height)):
            r = screen_r + self.view_r
            if r >= mg.height:
                break
            for screen_c in range(min(grid_cols, mg.width)):
                c = screen_c + self.view_c
                if c >= mg.width:
                    break
                x = screen_c * 2
                if x + 1 >= max_w:
                    break

                state = mg.cells.get((r, c), 0)
                is_cursor = (r == self.cursor_r and c == self.cursor_c)
                is_ant = (r, c) in ant_positions

                if is_cursor:
                    attr = curses.A_REVERSE
                    if self.use_color:
                        attr |= curses.color_pair(2)
                    ch = "██" if (state != 0 or is_ant) else "▒▒"
                elif is_ant:
                    attr = (curses.color_pair(23) | curses.A_BOLD) if self.use_color else curses.A_BOLD
                    ch = "▓▓"
                elif state != 0:
                    ch, attr = self._multistate_cell_attr(state, atype)
                else:
                    ch, attr = "  ", 0

                try:
                    self.stdscr.addstr(screen_r, x, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            state_str = "RUNNING" if self.running else "PAUSED"
            topo = "Torus" if mg.toroidal else "Bounded"
            cell_count = len(mg.cells)
            # State breakdown
            if atype == "Brian's Brain":
                on = sum(1 for s in mg.cells.values() if s == BB_ON)
                dying = sum(1 for s in mg.cells.values() if s == BB_DYING)
                breakdown = f"ON:{on} DYING:{dying}"
            elif atype == "Wireworld":
                heads = sum(1 for s in mg.cells.values() if s == WW_HEAD)
                tails = sum(1 for s in mg.cells.values() if s == WW_TAIL)
                conds = sum(1 for s in mg.cells.values() if s == WW_CONDUCTOR)
                breakdown = f"HEAD:{heads} TAIL:{tails} WIRE:{conds}"
            elif atype == "Langton's Ant":
                black = sum(1 for s in mg.cells.values() if s == LA_BLACK)
                num_ants = len(mg.ants) if hasattr(mg, "ants") else 0
                breakdown = f"BLACK:{black} ANTS:{num_ants}"
            else:
                breakdown = ""
            status = (
                f" {atype} | Gen: {self.multistate_gen} | Cells: {cell_count} ({breakdown}) | "
                f"Speed: {self.speed} | {topo} | {state_str} "
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
            if atype == "Brian's Brain":
                legend = "ON=██ DYING=▒▒"
            elif atype == "Wireworld":
                legend = "HEAD=██ TAIL=██ WIRE=░░"
            elif atype == "Langton's Ant":
                legend = "ANT=▓▓ BLACK=██"
            else:
                legend = ""
            help_text = (
                f" [Space]Run [S]tep [R]and [C]lear [Enter]Cycle cell | "
                f"[F/G]Type:{atype} | {legend} | "
                f"[+/-]Spd [T]orus [X]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    def _draw_split(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw side-by-side comparison of two grids under different rulesets."""
        if not self.split_grid_left or not self.split_grid_right:
            return

        # Each panel gets half the screen width, with a 1-char divider
        divider_x = max_w // 2
        panel_w = divider_x // 2  # cells per panel (each cell = 2 chars)

        # Compute viewport centered on the grid
        vr = max(0, min(self.grid.height // 2 - grid_rows // 2, self.grid.height - grid_rows))
        vc = max(0, min(self.grid.width // 2 - panel_w // 2, self.grid.width - panel_w))
        vr = max(0, vr)
        vc = max(0, vc)

        def draw_panel(grid: Grid, x_offset: int, panel_cells: int) -> None:
            for screen_r in range(min(grid_rows, grid.height)):
                r = screen_r + vr
                if r >= grid.height:
                    break
                for screen_c in range(panel_cells):
                    c = screen_c + vc
                    if c >= grid.width:
                        break
                    x = x_offset + screen_c * 2
                    if x + 1 >= max_w:
                        break
                    is_alive = (r, c) in grid.cells
                    if is_alive:
                        if self.use_color:
                            age = grid.ages.get((r, c), 1)
                            attr = curses.color_pair(self._age_color_pair(age))
                        else:
                            attr = curses.A_BOLD
                        ch = "██"
                    else:
                        attr = 0
                        ch = "  "
                    try:
                        self.stdscr.addstr(screen_r, x, ch, attr)
                    except curses.error:
                        pass

        # Draw left panel
        left_cells = min(panel_w, (divider_x - 1) // 2)
        draw_panel(self.split_grid_left, 0, left_cells)

        # Draw divider
        div_attr = curses.color_pair(3) if self.use_color else curses.A_DIM
        for screen_r in range(min(grid_rows, self.grid.height)):
            try:
                self.stdscr.addstr(screen_r, divider_x, "│", div_attr)
            except curses.error:
                pass

        # Draw right panel
        right_x = divider_x + 1
        right_cells = min(panel_w, (max_w - right_x) // 2)
        draw_panel(self.split_grid_right, right_x, right_cells)

        # Panel headers (ruleset names)
        name_l = RULESETS[self.split_rule_left][0]
        rs_l = rule_string(self.split_grid_left.birth, self.split_grid_left.survival)
        name_r = RULESETS[self.split_rule_right][0]
        rs_r = rule_string(self.split_grid_right.birth, self.split_grid_right.survival)
        header_attr = curses.color_pair(3) | curses.A_BOLD if self.use_color else curses.A_REVERSE
        left_header = f" {name_l} ({rs_l}) "
        right_header = f" {name_r} ({rs_r}) "
        try:
            self.stdscr.addstr(0, 1, left_header[:divider_x - 2], header_attr)
            self.stdscr.addstr(0, right_x + 1, right_header[:max_w - right_x - 2], header_attr)
        except curses.error:
            pass

        # Status bar with independent population counters
        status_y = max_h - 2
        if status_y > 0:
            state = "RUNNING" if self.running else "PAUSED"
            pop_l = len(self.split_grid_left.cells)
            pop_r = len(self.split_grid_right.cells)
            spark_l = self._split_sparkline(self.split_pop_left)
            spark_r = self._split_sparkline(self.split_pop_right)
            spark_l_sec = f"|{spark_l}|" if spark_l else ""
            spark_r_sec = f"|{spark_r}|" if spark_r else ""
            status = (
                f" Gen: {self.split_gen} | "
                f"L: {pop_l} {spark_l_sec} | "
                f"R: {pop_r} {spark_r_sec} | "
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
            help_text = (
                f" SPLIT COMPARE: {name_l} vs {name_r} | "
                f"[Space]Run/Pause [+/-]Speed [M]Exit split [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    def _draw_wolfram(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Wolfram 1D elementary CA cascading rows."""
        # Draw the rule diagram at the top-right corner
        rule_diagram_w = 35
        rule_y = 0

        # Draw the cascading rows
        for screen_r, row in enumerate(self.wolfram_rows[-grid_rows:]):
            if screen_r >= grid_rows:
                break
            for screen_c in range(min(grid_cols, len(row))):
                x = screen_c * 2
                if x + 1 >= max_w:
                    break
                if row[screen_c]:
                    # Color based on row age (newer rows at bottom are greener)
                    total_rows = len(self.wolfram_rows)
                    visible_start = max(0, total_rows - grid_rows)
                    row_idx = visible_start + screen_r
                    if self.use_color:
                        # Gradient: green (new) -> cyan -> yellow -> red (old)
                        if total_rows <= 1:
                            pair = 1
                        else:
                            ratio = row_idx / max(total_rows - 1, 1)
                            if ratio < 0.25:
                                pair = 1   # green
                            elif ratio < 0.5:
                                pair = 5   # cyan
                            elif ratio < 0.75:
                                pair = 6   # yellow
                            else:
                                pair = 7   # red
                        attr = curses.color_pair(pair)
                    else:
                        attr = curses.A_BOLD
                    try:
                        self.stdscr.addstr(screen_r, x, "██", attr)
                    except curses.error:
                        pass
                # Dead cells are left as blank (erased background)

        # Draw rule number badge in top-right
        if max_w > rule_diagram_w + 2:
            badge = f" Rule {self.wolfram_rule} "
            badge_x = max_w - len(badge) - 1
            badge_attr = curses.color_pair(3) | curses.A_BOLD if self.use_color else curses.A_REVERSE
            try:
                self.stdscr.addstr(0, badge_x, badge, badge_attr)
            except curses.error:
                pass

            # Draw the 8 neighborhood outcomes for this rule
            # Each outcome: 3 input cells -> 1 output cell
            if max_w > 40 and grid_rows > 3:
                outcomes_y = 1
                outcomes_x = max_w - 34
                label_attr = curses.color_pair(11) if self.use_color else curses.A_DIM
                for bit in range(7, -1, -1):
                    # The 3-bit input pattern
                    left = bool(bit & 4)
                    center = bool(bit & 2)
                    right = bool(bit & 1)
                    output = bool(self.wolfram_rule & (1 << bit))
                    # Draw input pattern
                    col_offset = (7 - bit) * 4
                    cx = outcomes_x + col_offset
                    if cx + 3 >= max_w:
                        break
                    inp = ("█" if left else "·") + ("█" if center else "·") + ("█" if right else "·")
                    out = " " + ("█" if output else "·") + " "
                    try:
                        self.stdscr.addstr(outcomes_y, cx, inp, label_attr)
                        self.stdscr.addstr(outcomes_y + 1, cx, out, label_attr)
                    except curses.error:
                        pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            state = "RUNNING" if self.running else "PAUSED"
            alive = sum(1 for c in self.wolfram_rows[-1] if c) if self.wolfram_rows else 0
            width = len(self.wolfram_rows[0]) if self.wolfram_rows else 0
            rule_bin = format(self.wolfram_rule, "08b")
            # Classify the rule
            classification = ""
            if self.wolfram_rule in (0, 8, 32, 40, 128, 136, 160, 168):
                classification = " [Class I: uniform]"
            elif self.wolfram_rule in (4, 12, 36, 44, 76, 108, 132, 140, 164, 172, 204, 232):
                classification = " [Class II: periodic]"
            elif self.wolfram_rule in (30, 45, 75, 86, 89, 101, 135, 149):
                classification = " [Class III: chaotic]"
            elif self.wolfram_rule in (54, 110, 124, 137, 193):
                classification = " [Class IV: complex]"
            status = (
                f" WOLFRAM 1D | Rule {self.wolfram_rule} ({rule_bin}){classification} | "
                f"Row: {self.wolfram_generation} | Alive: {alive}/{width} | "
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
            notable_str = ",".join(str(r) for r in self.wolfram_notable)
            help_text = (
                f" [Space]Run [S]tep [F/G]Cycle rule ({notable_str}) "
                f"[#]Enter rule [R]andom seed [C]enter seed [+/-]Speed [W/Esc]Exit [Q]uit"
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

    def _import_rle(self) -> None:
        """Import an RLE pattern file and add it to the pattern library."""
        path = self._text_prompt("RLE file path: ")
        if not path:
            self._set_message("Import cancelled")
            return
        # Expand ~ and resolve relative paths
        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        try:
            cells, name, rule = load_rle_file(path)
        except (OSError, ValueError) as e:
            self._set_message(f"RLE import error: {e}")
            return
        # Normalize offsets so the pattern starts at (0, 0)
        min_r = min(r for r, _ in cells)
        min_c = min(c for _, c in cells)
        offsets = [(r - min_r, c - min_c) for r, c in cells]
        # Avoid name collisions
        base_name = name
        suffix = 1
        while name in self.all_patterns:
            suffix += 1
            name = f"{base_name} ({suffix})"
        # Save as a custom pattern so it persists
        custom = load_custom_patterns()
        custom[name] = offsets
        try:
            save_custom_patterns(custom)
        except OSError as e:
            self._set_message(f"Save error: {e}")
            return
        self._refresh_patterns()
        # Select the newly imported pattern
        if name in self.all_pattern_names:
            self.pattern_idx = self.all_pattern_names.index(name)
        self._set_message(f"Imported '{name}' ({len(offsets)} cells) — [Enter] to place")

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

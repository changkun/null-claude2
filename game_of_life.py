#!/usr/bin/env python3
"""Terminal-based cellular automaton simulator using curses."""

import argparse
import curses
import json
import os
import random
import math
import re
import time
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
# ---------------------------------------------------------------------------
# Boids flocking simulation
# ---------------------------------------------------------------------------

BOIDS_PRESETS = {
    "classic":    (0.02, 0.05, 0.005, 2.0, 4.0, 8.0, "Classic Reynolds flocking"),
    "tight":      (0.04, 0.08, 0.008, 1.5, 3.0, 6.0, "Tight cohesive flocks"),
    "loose":      (0.01, 0.03, 0.003, 3.0, 6.0, 12.0, "Loose swarm behavior"),
    "predator":   (0.05, 0.10, 0.002, 2.5, 5.0, 10.0, "Strong separation, weak cohesion"),
    "murmur":     (0.02, 0.12, 0.010, 2.0, 5.0, 10.0, "Starling murmuration-like"),
    "school":     (0.03, 0.06, 0.010, 1.5, 3.5, 7.0, "Fish schooling behavior"),
}
BOIDS_PRESET_NAMES = list(BOIDS_PRESETS.keys())

# Direction arrows for rendering boids based on heading
BOIDS_ARROWS = "→↗↑↖←↙↓↘"


class BoidsWorld:
    """Craig Reynolds' Boids flocking simulation.

    Each boid follows three simple rules:
    1. Separation: steer away from nearby boids to avoid crowding
    2. Alignment: steer towards average heading of nearby boids
    3. Cohesion: steer towards average position of nearby boids

    These produce emergent flocking, schooling, and swarming behavior.
    """

    def __init__(self, width: int, height: int, num_boids: int = 150,
                 preset: str = "classic"):
        self.width = width
        self.height = height
        self.num_boids = num_boids
        self.preset_idx = BOIDS_PRESET_NAMES.index(preset)

        # Per-boid state: x, y, vx, vy
        self.x: list[float] = []
        self.y: list[float] = []
        self.vx: list[float] = []
        self.vy: list[float] = []

        # Max speed
        self.max_speed = 1.5
        self.min_speed = 0.3

        # Rule weights (set by preset)
        self.sep_weight = 0.02
        self.ali_weight = 0.05
        self.coh_weight = 0.005

        # Perception radii
        self.sep_radius = 2.0
        self.ali_radius = 4.0
        self.coh_radius = 8.0

        self._apply_preset(preset)
        self.seed()

    def _apply_preset(self, name: str) -> None:
        if name not in BOIDS_PRESETS:
            name = "classic"
        sep_w, ali_w, coh_w, sep_r, ali_r, coh_r, _desc = BOIDS_PRESETS[name]
        self.sep_weight = sep_w
        self.ali_weight = ali_w
        self.coh_weight = coh_w
        self.sep_radius = sep_r
        self.ali_radius = ali_r
        self.coh_radius = coh_r

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(BOIDS_PRESET_NAMES)
        name = BOIDS_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def seed(self) -> None:
        """Initialize boids with random positions and velocities."""
        self.x = [random.uniform(0, self.width) for _ in range(self.num_boids)]
        self.y = [random.uniform(0, self.height) for _ in range(self.num_boids)]
        self.vx = [random.uniform(-1, 1) for _ in range(self.num_boids)]
        self.vy = [random.uniform(-1, 1) for _ in range(self.num_boids)]
        # Normalize initial velocities
        for i in range(self.num_boids):
            speed = math.sqrt(self.vx[i] ** 2 + self.vy[i] ** 2)
            if speed > 0:
                self.vx[i] = self.vx[i] / speed * self.max_speed * 0.5
                self.vy[i] = self.vy[i] / speed * self.max_speed * 0.5

    def set_num_boids(self, n: int) -> None:
        """Change number of boids, adding or removing as needed."""
        n = max(5, min(1000, n))
        while len(self.x) < n:
            self.x.append(random.uniform(0, self.width))
            self.y.append(random.uniform(0, self.height))
            self.vx.append(random.uniform(-1, 1))
            self.vy.append(random.uniform(-1, 1))
        if len(self.x) > n:
            self.x = self.x[:n]
            self.y = self.y[:n]
            self.vx = self.vx[:n]
            self.vy = self.vy[:n]
        self.num_boids = n

    def tick(self) -> None:
        """Advance simulation by one time step."""
        n = self.num_boids
        w, h = float(self.width), float(self.height)
        sep_r2 = self.sep_radius ** 2
        ali_r2 = self.ali_radius ** 2
        coh_r2 = self.coh_radius ** 2
        max_r2 = max(sep_r2, ali_r2, coh_r2)

        new_vx = list(self.vx)
        new_vy = list(self.vy)

        for i in range(n):
            # Separation accumulators
            sep_dx = 0.0
            sep_dy = 0.0
            sep_count = 0
            # Alignment accumulators
            ali_vx = 0.0
            ali_vy = 0.0
            ali_count = 0
            # Cohesion accumulators
            coh_x = 0.0
            coh_y = 0.0
            coh_count = 0

            xi, yi = self.x[i], self.y[i]

            for j in range(n):
                if i == j:
                    continue
                # Toroidal distance
                dx = self.x[j] - xi
                dy = self.y[j] - yi
                # Wrap around
                if dx > w * 0.5:
                    dx -= w
                elif dx < -w * 0.5:
                    dx += w
                if dy > h * 0.5:
                    dy -= h
                elif dy < -h * 0.5:
                    dy += h

                dist2 = dx * dx + dy * dy
                if dist2 > max_r2 or dist2 < 1e-9:
                    continue

                # Separation
                if dist2 < sep_r2:
                    # Steer away, weighted by inverse distance
                    sep_dx -= dx / dist2
                    sep_dy -= dy / dist2
                    sep_count += 1

                # Alignment
                if dist2 < ali_r2:
                    ali_vx += self.vx[j]
                    ali_vy += self.vy[j]
                    ali_count += 1

                # Cohesion
                if dist2 < coh_r2:
                    coh_x += dx  # relative position
                    coh_y += dy
                    coh_count += 1

            # Apply forces
            if sep_count > 0:
                new_vx[i] += sep_dx * self.sep_weight
                new_vy[i] += sep_dy * self.sep_weight

            if ali_count > 0:
                avg_vx = ali_vx / ali_count
                avg_vy = ali_vy / ali_count
                new_vx[i] += (avg_vx - self.vx[i]) * self.ali_weight
                new_vy[i] += (avg_vy - self.vy[i]) * self.ali_weight

            if coh_count > 0:
                avg_dx = coh_x / coh_count
                avg_dy = coh_y / coh_count
                new_vx[i] += avg_dx * self.coh_weight
                new_vy[i] += avg_dy * self.coh_weight

        # Update velocities and positions
        for i in range(n):
            self.vx[i] = new_vx[i]
            self.vy[i] = new_vy[i]

            # Clamp speed
            speed = math.sqrt(self.vx[i] ** 2 + self.vy[i] ** 2)
            if speed > self.max_speed:
                self.vx[i] = self.vx[i] / speed * self.max_speed
                self.vy[i] = self.vy[i] / speed * self.max_speed
            elif speed < self.min_speed and speed > 1e-9:
                self.vx[i] = self.vx[i] / speed * self.min_speed
                self.vy[i] = self.vy[i] / speed * self.min_speed

            # Move
            self.x[i] = (self.x[i] + self.vx[i]) % w
            self.y[i] = (self.y[i] + self.vy[i]) % h


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
# Neural Cellular Automata (NCA) — learned update rules
# ---------------------------------------------------------------------------

NCA_PRESETS = {
    "grow": (
        0.15, 0.05, 3, "sigmoid", True,
        "Grow — pattern expands from a central seed",
    ),
    "persist": (
        0.10, 0.02, 4, "tanh", False,
        "Persist — stable pattern maintains shape",
    ),
    "morphogenesis": (
        0.08, 0.12, 3, "relu", False,
        "Morphogenesis — Turing-like emergent structure",
    ),
    "regenerate": (
        0.12, 0.04, 4, "sigmoid", True,
        "Regenerate — self-repairs when cells are erased",
    ),
}
NCA_PRESET_NAMES = list(NCA_PRESETS.keys())

# Sobel perception kernels (3x3) — dx and dy
_SOBEL_X = [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]]
_SOBEL_Y = [[-1, -2, -1], [0, 0, 0], [1, 2, 1]]
# Identity kernel for self-perception
_IDENTITY = [[0, 0, 0], [0, 1, 0], [0, 0, 0]]


class NCAWorld:
    """Neural Cellular Automata simulation.

    Each cell has multiple continuous state channels updated by a small MLP
    operating on Sobel-filtered perception vectors.  This produces
    self-organising, self-repairing patterns from simple learned rules.

    Based on the 'Growing Neural Cellular Automata' paradigm (Mordvintsev
    et al.), but using hand-tuned pseudo-learned weights for compelling
    terminal visualisation without requiring actual training.
    """

    def __init__(self, width: int, height: int, n_channels: int = 4,
                 preset: str = "grow"):
        self.width = width
        self.height = height
        self.n_channels = n_channels
        self.preset_idx = NCA_PRESET_NAMES.index(preset)

        # State grid: height × width × n_channels (channel 0 = alpha/alive)
        self.state: list[list[list[float]]] = [
            [[0.0] * n_channels for _ in range(width)]
            for _ in range(height)
        ]

        # MLP weights (randomly initialised per preset seed)
        self.hidden_size = 16
        self.w1: list[list[float]] = []  # perception_dim × hidden_size
        self.b1: list[float] = []
        self.w2: list[list[float]] = []  # hidden_size × n_channels
        self.b2: list[float] = []

        # Parameters
        self.update_rate = 0.15   # fraction of cells updated per step
        self.noise_amp = 0.05    # noise amplitude
        self.mlp_layers = 3
        self.activation = "sigmoid"
        self.use_seed = True
        self.alive_threshold = 0.1

        self._apply_preset(preset)
        self._init_weights()
        self.seed_center()

    def _apply_preset(self, name: str) -> None:
        if name not in NCA_PRESETS:
            name = "grow"
        update_rate, noise_amp, mlp_layers, activation, use_seed, _desc = NCA_PRESETS[name]
        self.update_rate = update_rate
        self.noise_amp = noise_amp
        self.mlp_layers = mlp_layers
        self.activation = activation
        self.use_seed = use_seed

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(NCA_PRESET_NAMES)
        name = NCA_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        self._init_weights()
        self.reset()
        return name

    def _init_weights(self) -> None:
        """Initialise MLP weights with deterministic seed per preset."""
        rng = random.Random(42 + self.preset_idx * 137)
        nc = self.n_channels
        # Perception produces 3*nc features (identity + sobel_x + sobel_y)
        perc_dim = 3 * nc
        hs = self.hidden_size

        # Xavier-like init scaled by layer count
        scale1 = (2.0 / (perc_dim + hs)) ** 0.5
        scale2 = (2.0 / (hs + nc)) ** 0.5

        self.w1 = [[rng.gauss(0, scale1) for _ in range(hs)] for _ in range(perc_dim)]
        self.b1 = [rng.gauss(0, 0.1) for _ in range(hs)]
        self.w2 = [[rng.gauss(0, scale2) for _ in range(nc)] for _ in range(hs)]
        self.b2 = [rng.gauss(0, 0.01) for _ in range(nc)]

    def _activate(self, x: float) -> float:
        """Apply activation function."""
        if self.activation == "sigmoid":
            ex = max(-20.0, min(20.0, x))
            return 1.0 / (1.0 + math.exp(-ex))
        elif self.activation == "tanh":
            return math.tanh(x)
        else:  # relu
            return max(0.0, x)

    def _perceive(self, y: int, x: int) -> list[float]:
        """Compute Sobel-filtered perception vector for cell (y, x)."""
        w, h, nc = self.width, self.height, self.n_channels
        result: list[float] = []
        for c in range(nc):
            ident = 0.0
            sx = 0.0
            sy = 0.0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    ny = (y + dy) % h
                    nx = (x + dx) % w
                    val = self.state[ny][nx][c]
                    ky = dy + 1
                    kx = dx + 1
                    ident += val * _IDENTITY[ky][kx]
                    sx += val * _SOBEL_X[ky][kx]
                    sy += val * _SOBEL_Y[ky][kx]
            result.append(ident)
            result.append(sx / 8.0)  # normalise Sobel
            result.append(sy / 8.0)
        return result

    def _mlp_forward(self, perception: list[float]) -> list[float]:
        """Run perception through the MLP to get state update delta."""
        nc = self.n_channels
        hs = self.hidden_size

        # Hidden layer
        hidden = [0.0] * hs
        for j in range(hs):
            s = self.b1[j]
            for i in range(len(perception)):
                s += perception[i] * self.w1[i][j]
            hidden[j] = self._activate(s)

        # Output layer (produces delta for each channel)
        delta = [0.0] * nc
        for j in range(nc):
            s = self.b2[j]
            for i in range(hs):
                s += hidden[i] * self.w2[i][j]
            # Output through tanh to keep updates bounded
            delta[j] = math.tanh(s)
        return delta

    def seed_center(self) -> None:
        """Place a seed pattern at the centre of the grid."""
        cy, cx = self.height // 2, self.width // 2
        nc = self.n_channels
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                y = (cy + dy) % self.height
                x = (cx + dx) % self.width
                dist = (dy * dy + dx * dx) ** 0.5
                val = max(0.0, 1.0 - dist / 3.0)
                self.state[y][x][0] = val  # alpha channel
                for c in range(1, nc):
                    self.state[y][x][c] = val * (0.5 + 0.5 * math.sin(c * 1.5 + dist))

    def reset(self) -> None:
        """Clear grid and re-seed."""
        for y in range(self.height):
            for x in range(self.width):
                for c in range(self.n_channels):
                    self.state[y][x][c] = 0.0
        if self.use_seed:
            self.seed_center()
        else:
            # Morphogenesis / persist: start with low random noise
            rng = random.Random()
            for y in range(self.height):
                for x in range(self.width):
                    self.state[y][x][0] = rng.uniform(0.05, 0.15)
                    for c in range(1, self.n_channels):
                        self.state[y][x][c] = rng.uniform(-0.1, 0.1)

    def erase_circle(self, cy: int, cx: int, radius: int = 3) -> None:
        """Erase cells in a circle around (cy, cx) for interactive perturbation."""
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dy * dy + dx * dx <= radius * radius:
                    y = (cy + dy) % self.height
                    x = (cx + dx) % self.width
                    for c in range(self.n_channels):
                        self.state[y][x][c] = 0.0

    def paint_circle(self, cy: int, cx: int, radius: int = 2) -> None:
        """Paint alive cells in a circle around (cy, cx)."""
        nc = self.n_channels
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dy * dy + dx * dx <= radius * radius:
                    y = (cy + dy) % self.height
                    x = (cx + dx) % self.width
                    dist = (dy * dy + dx * dx) ** 0.5
                    val = max(0.0, 1.0 - dist / (radius + 0.5))
                    self.state[y][x][0] = max(self.state[y][x][0], val)
                    for c in range(1, nc):
                        self.state[y][x][c] = val * 0.5

    def tick(self) -> None:
        """Advance NCA by one step with stochastic cell updates."""
        w, h, nc = self.width, self.height, self.n_channels
        rand = random.random

        # Compute updates for all cells, apply stochastically
        # Pre-compute which cells to update (stochastic masking)
        updates: list[tuple[int, int, list[float]]] = []
        for y in range(h):
            for x in range(w):
                if rand() > self.update_rate:
                    continue
                # Perceive neighbourhood
                perc = self._perceive(y, x)
                # MLP forward pass
                delta = self._mlp_forward(perc)
                updates.append((y, x, delta))

        # Apply updates
        for y, x, delta in updates:
            for c in range(nc):
                noise = (rand() - 0.5) * self.noise_amp
                self.state[y][x][c] += delta[c] * 0.1 + noise
                # Clamp
                self.state[y][x][c] = max(-1.0, min(1.0, self.state[y][x][c]))

        # Alive masking: cells with alpha < threshold die
        for y in range(h):
            for x in range(w):
                if self.state[y][x][0] < self.alive_threshold:
                    # Check if any neighbour is alive
                    has_alive_neighbour = False
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            if dy == 0 and dx == 0:
                                continue
                            ny = (y + dy) % h
                            nx = (x + dx) % w
                            if self.state[ny][nx][0] >= self.alive_threshold:
                                has_alive_neighbour = True
                                break
                        if has_alive_neighbour:
                            break
                    if not has_alive_neighbour:
                        for c in range(nc):
                            self.state[y][x][c] = 0.0

    @property
    def alive_count(self) -> int:
        """Count cells with alpha above threshold."""
        count = 0
        for y in range(self.height):
            for x in range(self.width):
                if self.state[y][x][0] >= self.alive_threshold:
                    count += 1
        return count

    @property
    def mean_alpha(self) -> float:
        """Average alpha channel value."""
        total = 0.0
        for y in range(self.height):
            for x in range(self.width):
                total += max(0.0, self.state[y][x][0])
        return total / max(1, self.width * self.height)


# ---------------------------------------------------------------------------
# Wave Function Collapse (WFC) terrain generation
# ---------------------------------------------------------------------------

# Tile definitions: each tile has a character, color, and allowed adjacencies
# Tiles: water, sand, grass, forest, mountain, snow
WFC_TILES = {
    0: {"name": "water",    "char": "≈≈", "color_id": 80},
    1: {"name": "sand",     "char": "··", "color_id": 81},
    2: {"name": "grass",    "char": "░░", "color_id": 82},
    3: {"name": "forest",   "char": "▓▓", "color_id": 83},
    4: {"name": "mountain", "char": "▲▲", "color_id": 84},
    5: {"name": "snow",     "char": "██", "color_id": 85},
}
NUM_WFC_TILES = len(WFC_TILES)

# Adjacency rules: which tiles can be next to each other
# Format: tile_id -> set of allowed neighbor tile_ids
WFC_ADJACENCY = {
    0: {0, 1},          # water: water, sand
    1: {0, 1, 2},       # sand: water, sand, grass
    2: {1, 2, 3},       # grass: sand, grass, forest
    3: {2, 3, 4},       # forest: grass, forest, mountain
    4: {3, 4, 5},       # mountain: forest, mountain, snow
    5: {4, 5},          # snow: mountain, snow
}

WFC_PRESETS = {
    "terrain": (
        WFC_ADJACENCY,
        None,  # no weight bias
        "Terrain — water/sand/grass/forest/mountain/snow",
    ),
    "islands": (
        {
            0: {0, 1},
            1: {0, 1, 2},
            2: {1, 2, 3},
            3: {2, 3, 4},
            4: {3, 4, 5},
            5: {4, 5},
        },
        {0: 3.0, 1: 1.5, 2: 1.0, 3: 0.8, 4: 0.5, 5: 0.3},
        "Islands — mostly water with scattered land",
    ),
    "highlands": (
        {
            0: {0, 1},
            1: {0, 1, 2},
            2: {1, 2, 3},
            3: {2, 3, 4},
            4: {3, 4, 5},
            5: {4, 5},
        },
        {0: 0.3, 1: 0.5, 2: 1.0, 3: 1.5, 4: 2.5, 5: 2.0},
        "Highlands — mountainous terrain with snow peaks",
    ),
    "coastal": (
        {
            0: {0, 1},
            1: {0, 1, 2},
            2: {1, 2, 3},
            3: {2, 3, 4},
            4: {3, 4, 5},
            5: {4, 5},
        },
        {0: 2.0, 1: 2.0, 2: 2.0, 3: 1.0, 4: 0.3, 5: 0.1},
        "Coastal — beaches and shallow waters",
    ),
    "checkerboard": (
        {
            0: {2, 4},
            1: {3, 5},
            2: {0, 4},
            3: {1, 5},
            4: {0, 2},
            5: {1, 3},
        },
        None,
        "Checkerboard — non-adjacent constraint pattern",
    ),
}
WFC_PRESET_NAMES = list(WFC_PRESETS.keys())


class WFCWorld:
    """Wave Function Collapse procedural terrain generator.

    Each cell starts in a superposition of all possible tile types.
    The algorithm repeatedly:
      1. Finds the cell with the lowest entropy (fewest possibilities).
      2. Collapses it to a single tile (weighted random).
      3. Propagates constraints to neighbors.

    When run step-by-step, the user sees the terrain emerge progressively.
    """

    def __init__(self, width: int, height: int, preset: str = "terrain") -> None:
        self.width = width
        self.height = height
        self.preset_idx = WFC_PRESET_NAMES.index(preset)
        self._apply_preset(preset)
        self.collapsed = 0
        self.total_cells = width * height
        self.contradiction = False
        self.complete = False
        self.steps_per_tick = 1  # how many cells to collapse per tick
        self._reset_grid()

    def _apply_preset(self, name: str) -> None:
        adj, weights, self.description = WFC_PRESETS[name]
        self.adjacency = adj
        # Tile weights for biased generation
        if weights is None:
            self.weights = {i: 1.0 for i in range(NUM_WFC_TILES)}
        else:
            self.weights = dict(weights)

    def _reset_grid(self) -> None:
        """Initialize all cells to full superposition."""
        all_tiles = frozenset(range(NUM_WFC_TILES))
        self.grid: list[list[frozenset[int] | int]] = [
            [all_tiles for _ in range(self.width)]
            for _ in range(self.height)
        ]
        self.collapsed = 0
        self.contradiction = False
        self.complete = False

    def reset(self) -> None:
        self._reset_grid()

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(WFC_PRESET_NAMES)
        name = WFC_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        self._reset_grid()
        return name

    def _entropy(self, y: int, x: int) -> float:
        """Return entropy of a cell (number of possibilities). Collapsed = inf."""
        cell = self.grid[y][x]
        if isinstance(cell, int):
            return float("inf")
        n = len(cell)
        if n == 0:
            return float("inf")
        return float(n)

    def _find_min_entropy(self) -> tuple[int, int] | None:
        """Find uncollapsed cell with minimum entropy (+ random tiebreak)."""
        min_ent = float("inf")
        candidates: list[tuple[int, int]] = []
        for y in range(self.height):
            for x in range(self.width):
                cell = self.grid[y][x]
                if isinstance(cell, int):
                    continue
                n = len(cell)
                if n == 0:
                    continue
                # Add small noise for tiebreaking
                ent = n + random.random() * 0.1
                if ent < min_ent:
                    min_ent = ent
                    candidates = [(y, x)]
                elif abs(ent - min_ent) < 0.5:
                    candidates.append((y, x))
        if not candidates:
            return None
        return random.choice(candidates)

    def _collapse(self, y: int, x: int) -> bool:
        """Collapse a cell to a single tile, weighted by tile weights."""
        cell = self.grid[y][x]
        if isinstance(cell, int):
            return True
        options = list(cell)
        if not options:
            self.contradiction = True
            return False
        # Weighted random selection
        w = [self.weights.get(t, 1.0) for t in options]
        total = sum(w)
        if total <= 0:
            chosen = random.choice(options)
        else:
            r = random.random() * total
            cumulative = 0.0
            chosen = options[-1]
            for i, opt in enumerate(options):
                cumulative += w[i]
                if r <= cumulative:
                    chosen = opt
                    break
        self.grid[y][x] = chosen
        self.collapsed += 1
        if self.collapsed >= self.total_cells:
            self.complete = True
        return True

    def _propagate(self, start_y: int, start_x: int) -> bool:
        """Propagate constraints from a collapsed cell using BFS."""
        stack = [(start_y, start_x)]
        visited = set()
        while stack:
            cy, cx = stack.pop()
            if (cy, cx) in visited:
                continue
            visited.add((cy, cx))
            cell = self.grid[cy][cx]
            if isinstance(cell, int):
                allowed_from_here = self.adjacency.get(cell, set())
            else:
                # Union of all adjacencies from possible tiles
                allowed_from_here: set[int] = set()
                for t in cell:
                    allowed_from_here |= self.adjacency.get(t, set())

            # Check 4 neighbors
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < self.height and 0 <= nx < self.width:
                    ncell = self.grid[ny][nx]
                    if isinstance(ncell, int):
                        continue  # already collapsed
                    # Also consider what neighbor allows back
                    new_options = frozenset(
                        t for t in ncell
                        if t in allowed_from_here
                        and cell_val_in_adj(self.adjacency, t, cell)
                    )
                    if new_options != ncell:
                        if len(new_options) == 0:
                            self.contradiction = True
                            return False
                        self.grid[ny][nx] = new_options
                        stack.append((ny, nx))
        return True

    def tick(self) -> None:
        """Perform one or more collapse steps."""
        if self.complete or self.contradiction:
            return
        for _ in range(self.steps_per_tick):
            if self.complete or self.contradiction:
                break
            pos = self._find_min_entropy()
            if pos is None:
                self.complete = True
                break
            y, x = pos
            if not self._collapse(y, x):
                break
            if not self._propagate(y, x):
                break

    @property
    def progress(self) -> float:
        return self.collapsed / max(1, self.total_cells)


def cell_val_in_adj(adjacency: dict, tile: int, cell) -> bool:
    """Check if tile is allowed adjacent to cell value."""
    allowed = adjacency.get(tile, set())
    if isinstance(cell, int):
        return cell in allowed
    # cell is a frozenset — tile must be adjacent to at least one option
    return bool(allowed & (cell if isinstance(cell, frozenset) else set(cell)))


# ---------------------------------------------------------------------------
# Langton's Turmites — generalized 2D Turing machines on a grid
# ---------------------------------------------------------------------------
# A turmite is defined by a transition table:
#   (state, color) -> (new_color, turn, new_state)
# where turn is: 0=none, 1=right, 2=u-turn, 3=left (or -1=left for convenience)
# Directions: 0=up, 1=right, 2=down, 3=left

TURMITE_PRESETS: dict[str, tuple[list[list[tuple[int, int, int]]], int, str]] = {
    # table[state][color] = (new_color, turn, new_state)
    # turn: 0=none, 1=right, 2=u-turn, 3=left
    "langton-ant": (
        [[(1, 1, 0), (0, 3, 0)]],  # 1 state, 2 colors: classic RL
        2, "Classic Langton's Ant — builds highway after ~10k steps",
    ),
    "fibonacci": (
        [[(1, 1, 1), (1, 3, 0)],
         [(1, 1, 0), (0, 0, 0)]],  # 2 states, 2 colors
        2, "Fibonacci spiral — grows a spiral pattern",
    ),
    "square-builder": (
        [[(1, 1, 1), (0, 0, 0)],
         [(1, 0, 1), (0, 0, 0)]],
        2, "Draws nested square patterns",
    ),
    "highway": (
        [[(1, 1, 1), (1, 3, 0)],
         [(1, 3, 0), (0, 1, 1)]],
        2, "Fast highway builder — diagonal roads",
    ),
    "chaotic": (
        [[(1, 1, 1), (0, 3, 1)],
         [(0, 1, 0), (0, 3, 0)]],
        2, "Chaotic wanderer — never settles",
    ),
    "snowflake": (
        [[(1, 1, 1), (1, 3, 1)],
         [(0, 3, 0), (0, 1, 0)]],
        2, "Grows symmetric snowflake-like structure",
    ),
    "striped": (
        [[(1, 3, 0), (1, 1, 1)],
         [(0, 1, 0), (1, 3, 0)]],
        2, "Produces striped highway patterns",
    ),
    "spiral-4c": (
        [[(1, 1, 0), (2, 3, 0), (3, 1, 0), (0, 3, 0)]],  # 1 state, 4 colors
        4, "4-color spiral — rich symmetric growth",
    ),
    "counter": (
        [[(1, 1, 1), (0, 3, 0)],
         [(0, 3, 1), (1, 1, 0)]],
        2, "Binary counter — orderly rectangular growth",
    ),
    "worm": (
        [[(1, 1, 0), (0, 1, 1)],
         [(1, 0, 0), (0, 0, 1)]],
        2, "Worm-like straight-line explorer",
    ),
}
TURMITE_PRESET_NAMES = list(TURMITE_PRESETS.keys())

# Direction deltas: UP, RIGHT, DOWN, LEFT
TURMITE_DELTAS = [(-1, 0), (0, 1), (1, 0), (0, -1)]

# Characters for turmite head by direction
TURMITE_HEAD_CHARS = ["▲▲", "►►", "▼▼", "◄◄"]

# Color characters for different cell states
TURMITE_CELL_CHARS = [
    "  ",   # color 0 (empty)
    "██",   # color 1
    "▓▓",   # color 2
    "░░",   # color 3
]


class TurmiteWorld:
    """2D Turing Machine (Turmite) simulation.

    Each turmite has an internal state and sits on a colored grid cell.
    The transition table maps (state, color) to (new_color, turn, new_state).
    Multiple turmites can run simultaneously on the same grid.
    """

    def __init__(self, width: int, height: int, preset: str = "langton-ant"):
        self.width = width
        self.height = height
        self.preset_idx = TURMITE_PRESET_NAMES.index(preset)

        # Grid of colors (integers)
        self.grid: list[list[int]] = [
            [0] * width for _ in range(height)
        ]

        # Turmite agents: list of [row, col, direction, state]
        self.turmites: list[list[int]] = []

        # Steps per tick
        self.steps_per_tick = 1

        # Apply preset (sets transition table and num_colors)
        self._apply_preset(preset)

        # Place initial turmite at center
        self._add_turmite(height // 2, width // 2)

    def _apply_preset(self, name: str) -> None:
        table, num_colors, _desc = TURMITE_PRESETS[name]
        self.table = table  # table[state][color] = (new_color, turn, new_state)
        self.num_colors = num_colors
        self.num_states = len(table)

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(TURMITE_PRESET_NAMES)
        name = TURMITE_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        self.reset()
        return name

    def _add_turmite(self, r: int, c: int, direction: int = 0, state: int = 0) -> None:
        self.turmites.append([r, c, direction, state])

    def add_turmite_center(self) -> None:
        """Add a new turmite at a random position near center."""
        r = self.height // 2 + random.randint(-self.height // 4, self.height // 4)
        c = self.width // 2 + random.randint(-self.width // 4, self.width // 4)
        d = random.randint(0, 3)
        self._add_turmite(r, c, d)

    def remove_turmite(self) -> None:
        """Remove the last turmite (keep at least one)."""
        if len(self.turmites) > 1:
            self.turmites.pop()

    def reset(self) -> None:
        """Clear grid and reset to single centered turmite."""
        for y in range(self.height):
            for x in range(self.width):
                self.grid[y][x] = 0
        self.turmites = []
        self._add_turmite(self.height // 2, self.width // 2)

    def tick(self) -> None:
        """Advance simulation by steps_per_tick steps."""
        table = self.table
        grid = self.grid
        w, h = self.width, self.height
        nc = self.num_colors

        for _ in range(self.steps_per_tick):
            for t in self.turmites:
                r, c, d, s = t
                color = grid[r][c]
                # Clamp color to valid range for this table
                if color >= len(table[s]):
                    color = color % len(table[s])

                new_color, turn, new_state = table[s][color]

                # Write new color
                grid[r][c] = new_color % nc

                # Turn: 0=none, 1=right, 2=u-turn, 3=left
                d = (d + turn) % 4

                # Move forward
                dr, dc = TURMITE_DELTAS[d]
                r = (r + dr) % h
                c = (c + dc) % w

                # Update turmite
                t[0] = r
                t[1] = c
                t[2] = d
                t[3] = new_state

    @property
    def colored_cells(self) -> int:
        """Count non-zero cells."""
        count = 0
        for row in self.grid:
            for c in row:
                if c != 0:
                    count += 1
        return count


# ---------------------------------------------------------------------------
# Hydraulic Erosion simulation
# ---------------------------------------------------------------------------

EROSION_PRESETS = {
    "gentle-hills": {
        "desc": "Gentle rolling hills with light rainfall",
        "rain_rate": 0.002,
        "evaporation": 0.02,
        "erosion_rate": 0.3,
        "deposition_rate": 0.3,
        "sediment_capacity": 0.05,
        "min_slope": 0.01,
        "gravity": 4.0,
        "terrain": "hills",
    },
    "mountain-range": {
        "desc": "Tall mountain range with heavy erosion",
        "rain_rate": 0.005,
        "evaporation": 0.015,
        "erosion_rate": 0.5,
        "deposition_rate": 0.2,
        "sediment_capacity": 0.08,
        "min_slope": 0.01,
        "gravity": 6.0,
        "terrain": "mountains",
    },
    "canyon-carver": {
        "desc": "Concentrated rainfall carves deep canyons",
        "rain_rate": 0.008,
        "evaporation": 0.01,
        "erosion_rate": 0.7,
        "deposition_rate": 0.15,
        "sediment_capacity": 0.12,
        "min_slope": 0.005,
        "gravity": 8.0,
        "terrain": "plateau",
    },
    "river-delta": {
        "desc": "Wide flat terrain forming river deltas",
        "rain_rate": 0.004,
        "evaporation": 0.025,
        "erosion_rate": 0.2,
        "deposition_rate": 0.5,
        "sediment_capacity": 0.04,
        "min_slope": 0.002,
        "gravity": 3.0,
        "terrain": "flat",
    },
    "volcanic": {
        "desc": "Volcanic cone eroded by intense rain",
        "rain_rate": 0.006,
        "evaporation": 0.02,
        "erosion_rate": 0.6,
        "deposition_rate": 0.25,
        "sediment_capacity": 0.1,
        "min_slope": 0.01,
        "gravity": 7.0,
        "terrain": "volcano",
    },
}

EROSION_PRESET_NAMES = list(EROSION_PRESETS.keys())


class ErosionWorld:
    """Hydraulic erosion simulation on a heightmap.

    Simulates rainfall, water flow, sediment transport, erosion, and
    deposition to carve realistic river valleys and terrain features.
    """

    def __init__(self, width: int, height: int, preset: str = "gentle-hills"):
        self.width = width
        self.height = height
        self.preset_idx = EROSION_PRESET_NAMES.index(preset)
        self.steps_per_tick = 1

        # Heightmap, water, sediment, velocity grids
        self.terrain: list[list[float]] = [[0.0] * width for _ in range(height)]
        self.water: list[list[float]] = [[0.0] * width for _ in range(height)]
        self.sediment: list[list[float]] = [[0.0] * width for _ in range(height)]
        self.velocity: list[list[float]] = [[0.0] * width for _ in range(height)]
        # Track cumulative erosion for visualization
        self.erosion_map: list[list[float]] = [[0.0] * width for _ in range(height)]

        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        p = EROSION_PRESETS[name]
        self.rain_rate = p["rain_rate"]
        self.evaporation = p["evaporation"]
        self.erosion_rate = p["erosion_rate"]
        self.deposition_rate = p["deposition_rate"]
        self.sediment_capacity = p["sediment_capacity"]
        self.min_slope = p["min_slope"]
        self.gravity = p["gravity"]
        self._generate_terrain(p["terrain"])

    def _generate_terrain(self, style: str) -> None:
        """Generate initial heightmap."""
        w, h = self.width, self.height
        for r in range(h):
            for c in range(w):
                self.water[r][c] = 0.0
                self.sediment[r][c] = 0.0
                self.velocity[r][c] = 0.0
                self.erosion_map[r][c] = 0.0

        if style == "hills":
            # Multiple overlapping sine hills
            for r in range(h):
                for c in range(w):
                    v = 0.0
                    v += 0.3 * math.sin(r * math.pi / h) * math.sin(c * math.pi / w)
                    v += 0.15 * math.sin(r * 3.7 * math.pi / h) * math.cos(c * 2.3 * math.pi / w)
                    v += 0.1 * math.cos(r * 5.1 * math.pi / h) * math.sin(c * 4.7 * math.pi / w)
                    v += random.uniform(0, 0.02)
                    self.terrain[r][c] = max(0.0, v)
        elif style == "mountains":
            # Ridge-like formation
            cx, cy = w / 2, h / 2
            for r in range(h):
                for c in range(w):
                    dx = (c - cx) / (w / 2)
                    ridge = max(0, 1.0 - abs(dx) * 2.0)
                    ridge *= 0.5 + 0.5 * math.sin(r * math.pi / h)
                    noise = 0.08 * math.sin(r * 7.3 / h * math.pi) * math.cos(c * 5.9 / w * math.pi)
                    noise += 0.04 * math.sin(r * 13.1 / h * math.pi + c * 9.7 / w * math.pi)
                    v = ridge * 0.8 + noise + random.uniform(0, 0.02)
                    self.terrain[r][c] = max(0.0, v)
        elif style == "plateau":
            # Flat plateau with edge dropoffs
            for r in range(h):
                for c in range(w):
                    edge_r = min(r, h - 1 - r) / (h / 3)
                    edge_c = min(c, w - 1 - c) / (w / 3)
                    edge = min(1.0, min(edge_r, edge_c))
                    v = 0.6 * edge + 0.05 * math.sin(r * 4.3 / h * math.pi) * math.cos(c * 3.7 / w * math.pi)
                    v += random.uniform(0, 0.015)
                    self.terrain[r][c] = max(0.0, v)
        elif style == "flat":
            # Gently sloped plain
            for r in range(h):
                for c in range(w):
                    slope = 0.2 * (1.0 - r / h)
                    noise = 0.03 * math.sin(r * 5.1 / h * math.pi) * math.sin(c * 3.3 / w * math.pi)
                    noise += 0.02 * math.cos(r * 8.7 / h * math.pi + c * 6.1 / w * math.pi)
                    v = slope + noise + random.uniform(0, 0.01)
                    self.terrain[r][c] = max(0.0, v)
        elif style == "volcano":
            # Conical volcano
            cx, cy = w / 2, h / 2
            max_dist = math.sqrt(cx * cx + cy * cy)
            for r in range(h):
                for c in range(w):
                    dx, dy = c - cx, r - cy
                    dist = math.sqrt(dx * dx + dy * dy) / max_dist
                    # Cone shape with crater
                    v = max(0, 0.9 - dist * 1.2)
                    if dist < 0.1:
                        v = max(0, v - 0.15 * (1 - dist / 0.1))
                    noise = 0.04 * math.sin(math.atan2(dy, dx) * 7) * (1 - dist)
                    v += noise + random.uniform(0, 0.015)
                    self.terrain[r][c] = max(0.0, v)

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(EROSION_PRESET_NAMES)
        name = EROSION_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        """Reset to initial terrain for current preset."""
        name = EROSION_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)

    def tick(self) -> None:
        """Advance simulation by steps_per_tick steps."""
        for _ in range(self.steps_per_tick):
            self._step()

    def _step(self) -> None:
        """Single erosion simulation step."""
        w, h = self.width, self.height
        terrain = self.terrain
        water = self.water
        sediment = self.sediment
        velocity = self.velocity
        erosion_map = self.erosion_map

        # 1. Rainfall — add water uniformly with some randomness
        rain = self.rain_rate
        for r in range(h):
            for c in range(w):
                if random.random() < 0.3:
                    water[r][c] += rain * (1.0 + random.uniform(0, 1.0))

        # 2. Water flow and erosion — each cell flows to lowest neighbor
        new_terrain = [row[:] for row in terrain]
        new_water = [row[:] for row in water]
        new_sediment = [row[:] for row in sediment]
        new_velocity = [[0.0] * w for _ in range(h)]

        for r in range(h):
            for c in range(w):
                if water[r][c] < 1e-6:
                    continue

                cur_height = terrain[r][c] + water[r][c]

                # Find lowest neighbor
                best_r, best_c = r, c
                best_h = cur_height
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < h and 0 <= nc < w:
                        nh = terrain[nr][nc] + water[nr][nc]
                        if nh < best_h:
                            best_h = nh
                            best_r, best_c = nr, nc

                if best_r == r and best_c == c:
                    # No lower neighbor — just deposit sediment
                    deposit = sediment[r][c] * self.deposition_rate
                    new_terrain[r][c] += deposit
                    new_sediment[r][c] -= deposit
                    continue

                # Height difference determines flow
                dh = cur_height - best_h
                # Flow amount — limited by available water and height diff
                flow = min(water[r][c], dh * 0.5)
                if flow < 1e-7:
                    continue

                # Update velocity
                new_vel = math.sqrt(velocity[r][c] ** 2 + dh * self.gravity)
                new_vel = min(new_vel, 3.0)  # cap velocity

                # Sediment capacity based on velocity and slope
                slope = max(dh, self.min_slope)
                capacity = slope * new_vel * self.sediment_capacity * flow

                # Erosion or deposition
                cur_sed = sediment[r][c]
                if cur_sed < capacity:
                    # Erode terrain
                    erode = min((capacity - cur_sed) * self.erosion_rate, terrain[r][c] * 0.5)
                    new_terrain[r][c] -= erode
                    new_sediment[r][c] += erode
                    erosion_map[r][c] += erode
                else:
                    # Deposit sediment
                    deposit = (cur_sed - capacity) * self.deposition_rate
                    new_terrain[r][c] += deposit
                    new_sediment[r][c] -= deposit

                # Transfer water and sediment to lowest neighbor
                sed_ratio = new_sediment[r][c] / (water[r][c] + 1e-9)
                flow_sed = flow * sed_ratio

                new_water[r][c] -= flow
                new_water[best_r][best_c] += flow
                new_sediment[r][c] -= flow_sed
                new_sediment[best_r][best_c] += flow_sed
                new_velocity[best_r][best_c] = new_vel

        # 3. Evaporation
        evap = self.evaporation
        for r in range(h):
            for c in range(w):
                new_water[r][c] *= (1.0 - evap)
                if new_water[r][c] < 1e-6:
                    # Deposit remaining sediment when water evaporates
                    new_terrain[r][c] += new_sediment[r][c]
                    new_sediment[r][c] = 0.0
                    new_water[r][c] = 0.0

        # Clamp values
        for r in range(h):
            for c in range(w):
                new_terrain[r][c] = max(0.0, new_terrain[r][c])
                new_water[r][c] = max(0.0, new_water[r][c])
                new_sediment[r][c] = max(0.0, new_sediment[r][c])

        self.terrain = new_terrain
        self.water = new_water
        self.sediment = new_sediment
        self.velocity = new_velocity

    @property
    def stats(self) -> dict:
        """Return simulation statistics."""
        total_water = 0.0
        total_sediment = 0.0
        max_height = 0.0
        max_water = 0.0
        for r in range(self.height):
            for c in range(self.width):
                total_water += self.water[r][c]
                total_sediment += self.sediment[r][c]
                if self.terrain[r][c] > max_height:
                    max_height = self.terrain[r][c]
                if self.water[r][c] > max_water:
                    max_water = self.water[r][c]
        return {
            "total_water": total_water,
            "total_sediment": total_sediment,
            "max_height": max_height,
            "max_water": max_water,
        }


# ---------------------------------------------------------------------------
# Magnetic Field / Electromagnetic Particle Simulation
# ---------------------------------------------------------------------------

MAGFIELD_PRESETS = {
    "cyclotron": {
        "desc": "Circular orbits in uniform B-field",
        "B": (0.0, 0.0, 1.0),       # B-field (Bx, By, Bz) — z-component curves in XY plane
        "E": (0.0, 0.0, 0.0),       # E-field (Ex, Ey, Ez)
        "num_particles": 30,
        "charge_ratio": 0.5,         # fraction of positive charges
        "speed_range": (0.3, 1.5),
        "spawn": "center-burst",
    },
    "magnetic-bottle": {
        "desc": "Converging B-field traps particles",
        "B": (0.0, 0.0, 0.8),
        "E": (0.0, 0.0, 0.0),
        "num_particles": 40,
        "charge_ratio": 0.5,
        "speed_range": (0.5, 2.0),
        "spawn": "line-horizontal",
        "mirror": True,
    },
    "exb-drift": {
        "desc": "E x B drift — particles drift perpendicular to E and B",
        "B": (0.0, 0.0, 1.2),
        "E": (0.0, 0.3, 0.0),
        "num_particles": 25,
        "charge_ratio": 0.5,
        "speed_range": (0.2, 1.0),
        "spawn": "left-column",
    },
    "hall-effect": {
        "desc": "Charge separation in crossed E and B fields",
        "B": (0.0, 0.0, 0.6),
        "E": (0.4, 0.0, 0.0),
        "num_particles": 50,
        "charge_ratio": 0.5,
        "speed_range": (0.1, 0.8),
        "spawn": "uniform",
    },
    "aurora": {
        "desc": "Particles spiralling along converging field lines",
        "B": (0.0, 0.0, 1.5),
        "E": (0.0, 0.0, 0.0),
        "num_particles": 60,
        "charge_ratio": 0.6,
        "speed_range": (0.5, 2.5),
        "spawn": "top-scatter",
        "mirror": True,
    },
}

MAGFIELD_PRESET_NAMES = list(MAGFIELD_PRESETS.keys())


class MagFieldWorld:
    """Electromagnetic particle simulation under Lorentz force.

    Charged particles move through configurable B and E fields.
    F = q(v x B) + qE  (Lorentz force, integrated with velocity-Verlet).
    """

    def __init__(self, width: int, height: int, preset: str = "cyclotron"):
        self.width = width
        self.height = height
        self.preset_idx = MAGFIELD_PRESET_NAMES.index(preset)
        self.steps_per_tick = 1
        self.dt = 0.15  # integration timestep
        self.trail_len = 8  # number of trail positions to remember

        # Particles: list of dicts with keys x, y, vx, vy, charge, trail
        self.particles: list[dict] = []
        # Field parameters
        self.Bx = 0.0
        self.By = 0.0
        self.Bz = 1.0
        self.Ex = 0.0
        self.Ey = 0.0
        self.Ez = 0.0
        self.mirror_mode = False  # magnetic bottle mirror effect

        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        p = MAGFIELD_PRESETS[name]
        self.Bx, self.By, self.Bz = p["B"]
        self.Ex, self.Ey, self.Ez = p["E"]
        self.mirror_mode = p.get("mirror", False)
        self._spawn_particles(
            p["num_particles"],
            p["charge_ratio"],
            p["speed_range"],
            p["spawn"],
        )

    def _spawn_particles(
        self,
        n: int,
        charge_ratio: float,
        speed_range: tuple[float, float],
        spawn: str,
    ) -> None:
        """Create initial particles."""
        self.particles = []
        w, h = self.width, self.height
        cx, cy = w / 2.0, h / 2.0
        slo, shi = speed_range

        for i in range(n):
            q = 1.0 if random.random() < charge_ratio else -1.0
            speed = random.uniform(slo, shi)
            angle = random.uniform(0, 2 * math.pi)
            vx = speed * math.cos(angle)
            vy = speed * math.sin(angle)

            if spawn == "center-burst":
                x = cx + random.uniform(-3, 3)
                y = cy + random.uniform(-3, 3)
            elif spawn == "line-horizontal":
                x = random.uniform(w * 0.2, w * 0.8)
                y = cy + random.uniform(-1, 1)
            elif spawn == "left-column":
                x = w * 0.1 + random.uniform(-2, 2)
                y = random.uniform(h * 0.2, h * 0.8)
                vx = abs(vx)  # start moving right
            elif spawn == "top-scatter":
                x = random.uniform(w * 0.1, w * 0.9)
                y = h * 0.1 + random.uniform(-2, 2)
                vy = abs(vy)  # start moving downward
            else:  # uniform
                x = random.uniform(1, w - 2)
                y = random.uniform(1, h - 2)

            self.particles.append({
                "x": x, "y": y,
                "vx": vx, "vy": vy,
                "q": q,
                "trail": [],
            })

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(MAGFIELD_PRESET_NAMES)
        name = MAGFIELD_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        """Reset to initial state for current preset."""
        name = MAGFIELD_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)

    def tick(self) -> None:
        for _ in range(self.steps_per_tick):
            self._step()

    def _effective_B(self, x: float, y: float) -> tuple[float, float, float]:
        """Return the B-field at position (x, y).

        In mirror mode, Bz increases near top/bottom edges to simulate
        a magnetic bottle (converging field lines).
        """
        bx, by, bz = self.Bx, self.By, self.Bz
        if self.mirror_mode:
            # Strengthen B near top/bottom to create mirror effect
            norm_y = y / self.height
            mirror_factor = 1.0 + 3.0 * (2.0 * norm_y - 1.0) ** 4
            bz *= mirror_factor
            # Add radial component for convergence
            norm_x = (x / self.width - 0.5) * 2.0
            bx += 0.3 * norm_x * ((2.0 * norm_y - 1.0) ** 2)
        return bx, by, bz

    def _step(self) -> None:
        """Boris integrator for Lorentz force: F = q(v x B + E)."""
        dt = self.dt
        w, h = self.width, self.height

        for p in self.particles:
            q = p["q"]
            x, y = p["x"], p["y"]
            vx, vy = p["vx"], p["vy"]

            # Get local B-field
            bx, by, bz = self._effective_B(x, y)

            # Boris push (half-step E, rotate via B, half-step E)
            # Half acceleration from E
            half_dt_q = 0.5 * dt * q
            vx += half_dt_q * self.Ex
            vy += half_dt_q * self.Ey

            # Rotation from B using Boris method
            # t = q*B*dt/2
            tx = half_dt_q * bx
            ty = half_dt_q * by
            tz = half_dt_q * bz

            # v' = v + v x t
            vpx = vx + (vy * tz - 0.0 * ty)  # vz=0 for 2D
            vpy = vy + (0.0 * tx - vx * tz)

            # s = 2t / (1 + |t|^2)
            t_mag2 = tx * tx + ty * ty + tz * tz
            s_factor = 2.0 / (1.0 + t_mag2)
            sx = s_factor * tx
            sy = s_factor * ty
            sz = s_factor * tz

            # v = v + v' x s
            vx += (vpy * sz - 0.0 * sy)
            vy += (0.0 * sx - vpx * sz)

            # Second half acceleration from E
            vx += half_dt_q * self.Ex
            vy += half_dt_q * self.Ey

            # Speed cap to keep things visible
            speed = math.sqrt(vx * vx + vy * vy)
            max_speed = 4.0
            if speed > max_speed:
                vx *= max_speed / speed
                vy *= max_speed / speed

            # Save trail
            p["trail"].append((x, y))
            if len(p["trail"]) > self.trail_len:
                p["trail"] = p["trail"][-self.trail_len:]

            # Update position
            nx = x + vx * dt
            ny = y + vy * dt

            # Boundary: reflect
            if nx < 0:
                nx = -nx
                vx = -vx
            elif nx >= w:
                nx = 2 * w - nx - 1
                vx = -vx
            if ny < 0:
                ny = -ny
                vy = -vy
            elif ny >= h:
                ny = 2 * h - ny - 1
                vy = -vy

            # Clamp to bounds
            nx = max(0.0, min(w - 0.01, nx))
            ny = max(0.0, min(h - 0.01, ny))

            p["x"] = nx
            p["y"] = ny
            p["vx"] = vx
            p["vy"] = vy

    @property
    def stats(self) -> dict:
        """Return simulation statistics."""
        if not self.particles:
            return {"n": 0, "pos": 0, "neg": 0, "avg_speed": 0.0, "max_speed": 0.0}
        pos = sum(1 for p in self.particles if p["q"] > 0)
        neg = len(self.particles) - pos
        speeds = [math.sqrt(p["vx"] ** 2 + p["vy"] ** 2) for p in self.particles]
        return {
            "n": len(self.particles),
            "pos": pos,
            "neg": neg,
            "avg_speed": sum(speeds) / len(speeds),
            "max_speed": max(speeds),
        }


# ---------------------------------------------------------------------------
# Gravity N-Body simulation
# ---------------------------------------------------------------------------

NBODY_PRESETS = {
    "binary-star": {
        "desc": "Two massive stars orbiting each other",
        "bodies": [
            {"x_frac": 0.4, "y_frac": 0.5, "vx": 0.0, "vy": -0.4, "mass": 80.0, "kind": "star"},
            {"x_frac": 0.6, "y_frac": 0.5, "vx": 0.0, "vy": 0.4, "mass": 80.0, "kind": "star"},
        ],
    },
    "solar-system": {
        "desc": "Central star with orbiting planets",
        "bodies": [
            {"x_frac": 0.5, "y_frac": 0.5, "vx": 0.0, "vy": 0.0, "mass": 200.0, "kind": "star"},
            {"x_frac": 0.65, "y_frac": 0.5, "vx": 0.0, "vy": 1.3, "mass": 5.0, "kind": "planet"},
            {"x_frac": 0.75, "y_frac": 0.5, "vx": 0.0, "vy": 1.0, "mass": 8.0, "kind": "planet"},
            {"x_frac": 0.85, "y_frac": 0.5, "vx": 0.0, "vy": 0.8, "mass": 3.0, "kind": "planet"},
            {"x_frac": 0.35, "y_frac": 0.5, "vx": 0.0, "vy": -1.3, "mass": 4.0, "kind": "planet"},
        ],
    },
    "three-body": {
        "desc": "Chaotic three-body problem",
        "bodies": [
            {"x_frac": 0.35, "y_frac": 0.35, "vx": 0.3, "vy": 0.0, "mass": 60.0, "kind": "star"},
            {"x_frac": 0.65, "y_frac": 0.35, "vx": -0.15, "vy": 0.25, "mass": 60.0, "kind": "star"},
            {"x_frac": 0.5, "y_frac": 0.7, "vx": -0.15, "vy": -0.25, "mass": 60.0, "kind": "star"},
        ],
    },
    "asteroid-belt": {
        "desc": "Star with many small orbiting bodies",
        "bodies": "procedural-belt",
    },
    "figure-eight": {
        "desc": "Three equal masses in a figure-eight orbit",
        "bodies": [
            {"x_frac": 0.5, "y_frac": 0.38, "vx": 0.52, "vy": 0.30, "mass": 50.0, "kind": "star"},
            {"x_frac": 0.5, "y_frac": 0.62, "vx": 0.52, "vy": 0.30, "mass": 50.0, "kind": "star"},
            {"x_frac": 0.5, "y_frac": 0.5, "vx": -1.04, "vy": -0.60, "mass": 50.0, "kind": "star"},
        ],
    },
}

NBODY_PRESET_NAMES = list(NBODY_PRESETS.keys())


class NBodyWorld:
    """N-body gravitational simulation.

    Bodies interact via F = G*m1*m2/r^2, with collision merging
    and orbital trail rendering.
    """

    def __init__(self, width: int, height: int, preset: str = "binary-star"):
        self.width = width
        self.height = height
        self.preset_idx = NBODY_PRESET_NAMES.index(preset)
        self.steps_per_tick = 2
        self.dt = 0.08
        self.G = 0.5  # gravitational constant
        self.trail_len = 20
        self.softening = 1.5  # softening length to prevent singularities
        self.merge_dist = 1.0  # collision/merge distance factor
        self.bodies: list[dict] = []
        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        p = NBODY_PRESETS[name]
        self.bodies = []
        w, h = self.width, self.height

        if p["bodies"] == "procedural-belt":
            # Central star + ring of small bodies
            self.bodies.append({
                "x": w * 0.5, "y": h * 0.5,
                "vx": 0.0, "vy": 0.0,
                "mass": 200.0, "kind": "star", "trail": [],
            })
            for i in range(30):
                angle = random.uniform(0, 2 * math.pi)
                r = random.uniform(min(w, h) * 0.2, min(w, h) * 0.4)
                x = w * 0.5 + r * math.cos(angle)
                y = h * 0.5 + r * math.sin(angle)
                # Orbital velocity: v = sqrt(GM/r)
                v = math.sqrt(self.G * 200.0 / max(r, 1.0))
                vx = -v * math.sin(angle) + random.uniform(-0.05, 0.05)
                vy = v * math.cos(angle) + random.uniform(-0.05, 0.05)
                self.bodies.append({
                    "x": x, "y": y, "vx": vx, "vy": vy,
                    "mass": random.uniform(0.5, 3.0), "kind": "asteroid",
                    "trail": [],
                })
        else:
            for b in p["bodies"]:
                self.bodies.append({
                    "x": w * b["x_frac"], "y": h * b["y_frac"],
                    "vx": b["vx"], "vy": b["vy"],
                    "mass": b["mass"], "kind": b["kind"],
                    "trail": [],
                })

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(NBODY_PRESET_NAMES)
        name = NBODY_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        name = NBODY_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)

    def tick(self) -> None:
        for _ in range(self.steps_per_tick):
            self._step()

    def _step(self) -> None:
        """Velocity-Verlet integration with pairwise gravity."""
        dt = self.dt
        bodies = self.bodies
        n = len(bodies)
        if n == 0:
            return

        # Compute accelerations
        ax = [0.0] * n
        ay = [0.0] * n
        for i in range(n):
            for j in range(i + 1, n):
                dx = bodies[j]["x"] - bodies[i]["x"]
                dy = bodies[j]["y"] - bodies[i]["y"]
                r2 = dx * dx + dy * dy + self.softening * self.softening
                r = math.sqrt(r2)
                f = self.G * bodies[i]["mass"] * bodies[j]["mass"] / r2
                fx = f * dx / r
                fy = f * dy / r
                ax[i] += fx / bodies[i]["mass"]
                ay[i] += fy / bodies[i]["mass"]
                ax[j] -= fx / bodies[j]["mass"]
                ay[j] -= fy / bodies[j]["mass"]

        # Update velocities and positions
        for i in range(n):
            b = bodies[i]
            # Save trail
            b["trail"].append((b["x"], b["y"]))
            if len(b["trail"]) > self.trail_len:
                b["trail"] = b["trail"][-self.trail_len:]

            b["vx"] += ax[i] * dt
            b["vy"] += ay[i] * dt
            b["x"] += b["vx"] * dt
            b["y"] += b["vy"] * dt

        # Speed cap
        max_speed = 5.0
        for b in bodies:
            speed = math.sqrt(b["vx"] ** 2 + b["vy"] ** 2)
            if speed > max_speed:
                b["vx"] *= max_speed / speed
                b["vy"] *= max_speed / speed

        # Collision detection & merging
        merged: set[int] = set()
        new_bodies: list[dict] = []
        for i in range(n):
            if i in merged:
                continue
            bi = bodies[i]
            for j in range(i + 1, n):
                if j in merged:
                    continue
                bj = bodies[j]
                dx = bi["x"] - bj["x"]
                dy = bi["y"] - bj["y"]
                dist = math.sqrt(dx * dx + dy * dy)
                # Merge threshold based on sum of "radii" (proportional to mass)
                ri = max(0.3, bi["mass"] ** 0.33 * 0.3)
                rj = max(0.3, bj["mass"] ** 0.33 * 0.3)
                if dist < (ri + rj) * self.merge_dist:
                    # Merge j into i (conserve momentum)
                    total_m = bi["mass"] + bj["mass"]
                    bi["vx"] = (bi["mass"] * bi["vx"] + bj["mass"] * bj["vx"]) / total_m
                    bi["vy"] = (bi["mass"] * bi["vy"] + bj["mass"] * bj["vy"]) / total_m
                    bi["x"] = (bi["mass"] * bi["x"] + bj["mass"] * bj["x"]) / total_m
                    bi["y"] = (bi["mass"] * bi["y"] + bj["mass"] * bj["y"]) / total_m
                    bi["mass"] = total_m
                    # Promote kind if large enough
                    if bi["mass"] >= 30.0:
                        bi["kind"] = "star"
                    elif bi["mass"] >= 8.0:
                        bi["kind"] = "planet"
                    merged.add(j)
            new_bodies.append(bi)
        self.bodies = new_bodies

        # Soft boundary: wrap or reflect bodies that leave the arena
        w, h = self.width, self.height
        for b in self.bodies:
            if b["x"] < 0:
                b["x"] = 0.0
                b["vx"] = abs(b["vx"]) * 0.5
            elif b["x"] >= w:
                b["x"] = w - 0.01
                b["vx"] = -abs(b["vx"]) * 0.5
            if b["y"] < 0:
                b["y"] = 0.0
                b["vy"] = abs(b["vy"]) * 0.5
            elif b["y"] >= h:
                b["y"] = h - 0.01
                b["vy"] = -abs(b["vy"]) * 0.5

    @property
    def stats(self) -> dict:
        if not self.bodies:
            return {"n": 0, "stars": 0, "planets": 0, "asteroids": 0,
                    "total_mass": 0.0, "avg_speed": 0.0}
        stars = sum(1 for b in self.bodies if b["kind"] == "star")
        planets = sum(1 for b in self.bodies if b["kind"] == "planet")
        asteroids = sum(1 for b in self.bodies if b["kind"] == "asteroid")
        total_mass = sum(b["mass"] for b in self.bodies)
        speeds = [math.sqrt(b["vx"] ** 2 + b["vy"] ** 2) for b in self.bodies]
        return {
            "n": len(self.bodies),
            "stars": stars,
            "planets": planets,
            "asteroids": asteroids,
            "total_mass": total_mass,
            "avg_speed": sum(speeds) / len(speeds),
        }


# ---------------------------------------------------------------------------
# Forest Fire simulation — percolation dynamics & self-organized criticality
# ---------------------------------------------------------------------------

FIRE_EMPTY = 0
FIRE_TREE = 1
FIRE_BURNING = 2
FIRE_CHARRED = 3

# ── DLA (Diffusion-Limited Aggregation) ──────────────────────────────────────

DLA_EMPTY = 0
DLA_CRYSTAL = 1
DLA_WALKER = 2

DLA_PRESETS = {
    "center-seed": {
        "desc": "Single seed at center — classic snowflake growth",
        "num_walkers": 800,
        "stickiness": 1.0,
        "spawn_mode": "boundary",
        "seed_mode": "center",
        "walkers_per_tick": 50,
    },
    "line-seed": {
        "desc": "Bottom line seed — upward dendritic growth",
        "num_walkers": 600,
        "stickiness": 1.0,
        "spawn_mode": "top",
        "seed_mode": "bottom-line",
        "walkers_per_tick": 40,
    },
    "multi-seed": {
        "desc": "Multiple random seeds — competing crystal fronts",
        "num_walkers": 1000,
        "stickiness": 1.0,
        "spawn_mode": "boundary",
        "seed_mode": "multi",
        "walkers_per_tick": 60,
    },
    "sparse-tendrils": {
        "desc": "Low stickiness — long wispy tendrils",
        "num_walkers": 600,
        "stickiness": 0.3,
        "spawn_mode": "boundary",
        "seed_mode": "center",
        "walkers_per_tick": 40,
    },
    "coral": {
        "desc": "Dense coral-like growth from bottom",
        "num_walkers": 1200,
        "stickiness": 0.7,
        "spawn_mode": "top",
        "seed_mode": "bottom-line",
        "walkers_per_tick": 80,
    },
    "lightning": {
        "desc": "Top seed, bottom walkers — lightning bolt pattern",
        "num_walkers": 800,
        "stickiness": 0.5,
        "spawn_mode": "bottom",
        "seed_mode": "top-point",
        "walkers_per_tick": 50,
    },
}
DLA_PRESET_NAMES = list(DLA_PRESETS.keys())


class DLAWorld:
    """Diffusion-Limited Aggregation — fractal crystal growth via random walkers."""

    def __init__(self, width: int, height: int, preset: str = "center-seed"):
        self.width = width
        self.height = height
        self.preset_idx = DLA_PRESET_NAMES.index(preset)
        self.stickiness = 1.0
        self.walkers_per_tick = 50
        self.num_walkers = 800
        self.spawn_mode = "boundary"
        # Grid: 0=empty, positive=crystal (value = order of attachment)
        self.grid = [[0] * width for _ in range(height)]
        self.walkers: list[tuple[int, int]] = []
        self.crystal_count = 0
        self.max_crystal_order = 0
        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        import random as _rng
        cfg = DLA_PRESETS[name]
        self.stickiness = cfg["stickiness"]
        self.walkers_per_tick = cfg["walkers_per_tick"]
        self.num_walkers = cfg["num_walkers"]
        self.spawn_mode = cfg["spawn_mode"]
        self.grid = [[0] * self.width for _ in range(self.height)]
        self.walkers = []
        self.crystal_count = 0
        self.max_crystal_order = 0

        seed_mode = cfg["seed_mode"]
        if seed_mode == "center":
            cx, cy = self.width // 2, self.height // 2
            self._place_seed(cy, cx)
        elif seed_mode == "bottom-line":
            for c in range(self.width):
                self._place_seed(self.height - 1, c)
        elif seed_mode == "multi":
            count = max(3, (self.width * self.height) // 400)
            for _ in range(count):
                r = _rng.randint(self.height // 4, 3 * self.height // 4)
                c = _rng.randint(self.width // 4, 3 * self.width // 4)
                self._place_seed(r, c)
        elif seed_mode == "top-point":
            cx = self.width // 2
            self._place_seed(0, cx)

        # Spawn initial walkers
        for _ in range(self.num_walkers):
            self._spawn_walker(_rng)

    def _place_seed(self, r: int, c: int) -> None:
        if 0 <= r < self.height and 0 <= c < self.width and self.grid[r][c] == 0:
            self.crystal_count += 1
            self.max_crystal_order = self.crystal_count
            self.grid[r][c] = self.crystal_count

    def _spawn_walker(self, _rng) -> None:
        w, h = self.width, self.height
        mode = self.spawn_mode
        if mode == "boundary":
            side = _rng.randint(0, 3)
            if side == 0:
                pos = (0, _rng.randint(0, w - 1))
            elif side == 1:
                pos = (h - 1, _rng.randint(0, w - 1))
            elif side == 2:
                pos = (_rng.randint(0, h - 1), 0)
            else:
                pos = (_rng.randint(0, h - 1), w - 1)
        elif mode == "top":
            pos = (0, _rng.randint(0, w - 1))
        elif mode == "bottom":
            pos = (h - 1, _rng.randint(0, w - 1))
        else:
            pos = (_rng.randint(0, h - 1), _rng.randint(0, w - 1))
        if self.grid[pos[0]][pos[1]] == 0:
            self.walkers.append(pos)

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(DLA_PRESET_NAMES)
        name = DLA_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        self._apply_preset(DLA_PRESET_NAMES[self.preset_idx])

    def add_seed(self, r: int, c: int) -> None:
        """Manually place a crystal seed."""
        self._place_seed(r, c)

    def tick(self) -> None:
        import random as _rng
        for _ in range(self.walkers_per_tick):
            self._step(_rng)

    def _has_crystal_neighbor(self, r: int, c: int) -> bool:
        w, h = self.width, self.height
        if r > 0 and self.grid[r - 1][c] > 0:
            return True
        if r < h - 1 and self.grid[r + 1][c] > 0:
            return True
        if c > 0 and self.grid[r][c - 1] > 0:
            return True
        if c < w - 1 and self.grid[r][c + 1] > 0:
            return True
        return False

    def _step(self, _rng) -> None:
        w, h = self.width, self.height
        new_walkers = []
        for r, c in self.walkers:
            # Random walk
            dr = _rng.choice((-1, 0, 1))
            dc = _rng.choice((-1, 0, 1))
            nr, nc = r + dr, c + dc
            # Boundary: wrap or clamp
            if nr < 0 or nr >= h or nc < 0 or nc >= w:
                # Re-spawn at boundary
                self._spawn_walker(_rng)
                continue
            if self.grid[nr][nc] > 0:
                # Walked into a crystal cell; stay put and check for sticking
                nr, nc = r, c
            if self._has_crystal_neighbor(nr, nc) and self.grid[nr][nc] == 0:
                if _rng.random() < self.stickiness:
                    # Stick!
                    self.crystal_count += 1
                    self.max_crystal_order = self.crystal_count
                    self.grid[nr][nc] = self.crystal_count
                    # Spawn a replacement walker
                    self._spawn_walker(_rng)
                else:
                    new_walkers.append((nr, nc))
            else:
                new_walkers.append((nr, nc))
        self.walkers = new_walkers

        # Top up walkers if below target
        while len(self.walkers) < self.num_walkers:
            self._spawn_walker(_rng)

    @property
    def stats(self) -> dict:
        total = self.width * self.height
        return {
            "crystals": self.crystal_count,
            "walkers": len(self.walkers),
            "coverage": self.crystal_count / total if total > 0 else 0,
        }

FORESTFIRE_PRESETS = {
    "classic": {
        "desc": "Classic forest fire — balanced growth and lightning",
        "p_grow": 0.05,
        "p_lightning": 0.0001,
        "charred_cooldown": 3,
        "init": "random",
        "init_density": 0.55,
    },
    "dense-forest": {
        "desc": "Dense canopy — rare lightning, massive cascading burns",
        "p_grow": 0.08,
        "p_lightning": 0.00003,
        "charred_cooldown": 5,
        "init": "random",
        "init_density": 0.75,
    },
    "sparse-dry": {
        "desc": "Sparse dry landscape — frequent small fires",
        "p_grow": 0.02,
        "p_lightning": 0.001,
        "charred_cooldown": 2,
        "init": "random",
        "init_density": 0.3,
    },
    "percolation-threshold": {
        "desc": "Near p_c ≈ 0.5927 — critical percolation cluster emergence",
        "p_grow": 0.03,
        "p_lightning": 0.0002,
        "charred_cooldown": 4,
        "init": "random",
        "init_density": 0.59,
    },
    "regrowth": {
        "desc": "Fast regrowth cycle — watch the forest recover",
        "p_grow": 0.12,
        "p_lightning": 0.0005,
        "charred_cooldown": 1,
        "init": "random",
        "init_density": 0.5,
    },
    "inferno": {
        "desc": "Full forest, single lightning strike — watch it all burn",
        "p_grow": 0.0,
        "p_lightning": 0.0,
        "charred_cooldown": 4,
        "init": "full",
        "init_density": 1.0,
    },
}
FORESTFIRE_PRESET_NAMES = list(FORESTFIRE_PRESETS.keys())


class ForestFireWorld:
    """Forest Fire cellular automaton — self-organized criticality via percolation."""

    def __init__(self, width: int, height: int, preset: str = "classic"):
        self.width = width
        self.height = height
        self.preset_idx = FORESTFIRE_PRESET_NAMES.index(preset)
        self.p_grow = 0.05
        self.p_lightning = 0.0001
        self.charred_cooldown = 3
        self.steps_per_tick = 1
        # Grid: 0=empty, 1=tree, 2=burning, 3=charred
        self.grid = [[FIRE_EMPTY] * width for _ in range(height)]
        # Cooldown counter for charred cells
        self.cooldown = [[0] * width for _ in range(height)]
        self.tree_count = 0
        self.burning_count = 0
        self.total_burned = 0
        self.fire_sizes: list[int] = []  # recent fire cascade sizes
        self.max_fire_history = 200
        self.current_fire_size = 0
        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        import random as _rng
        cfg = FORESTFIRE_PRESETS[name]
        self.p_grow = cfg["p_grow"]
        self.p_lightning = cfg["p_lightning"]
        self.charred_cooldown = cfg["charred_cooldown"]
        self.grid = [[FIRE_EMPTY] * self.width for _ in range(self.height)]
        self.cooldown = [[0] * self.width for _ in range(self.height)]
        self.tree_count = 0
        self.burning_count = 0
        self.total_burned = 0
        self.fire_sizes = []
        self.current_fire_size = 0
        if cfg["init"] == "random":
            density = cfg["init_density"]
            for r in range(self.height):
                for c in range(self.width):
                    if _rng.random() < density:
                        self.grid[r][c] = FIRE_TREE
                        self.tree_count += 1
        elif cfg["init"] == "full":
            for r in range(self.height):
                for c in range(self.width):
                    self.grid[r][c] = FIRE_TREE
                    self.tree_count += 1

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(FORESTFIRE_PRESET_NAMES)
        name = FORESTFIRE_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        self._apply_preset(FORESTFIRE_PRESET_NAMES[self.preset_idx])

    def strike_at(self, r: int, c: int) -> None:
        """Manually ignite a tree at (r, c)."""
        if 0 <= r < self.height and 0 <= c < self.width:
            if self.grid[r][c] == FIRE_TREE:
                self.grid[r][c] = FIRE_BURNING
                self.tree_count -= 1
                self.burning_count += 1

    def tick(self) -> None:
        import random as _rng
        for _ in range(self.steps_per_tick):
            self._step(_rng)

    def _step(self, _rng) -> None:
        w, h = self.width, self.height
        new_grid = [row[:] for row in self.grid]
        new_cooldown = [row[:] for row in self.cooldown]
        new_burning = 0
        new_trees = 0
        fires_this_step = 0

        for r in range(h):
            grow = self.grid[r]
            for c in range(w):
                cell = grow[c]
                if cell == FIRE_BURNING:
                    # Burning → charred
                    new_grid[r][c] = FIRE_CHARRED
                    new_cooldown[r][c] = self.charred_cooldown
                    self.total_burned += 1
                    fires_this_step += 1
                elif cell == FIRE_TREE:
                    # Check if any von Neumann neighbor is burning
                    ignited = False
                    if r > 0 and self.grid[r - 1][c] == FIRE_BURNING:
                        ignited = True
                    elif r < h - 1 and self.grid[r + 1][c] == FIRE_BURNING:
                        ignited = True
                    elif c > 0 and self.grid[r][c - 1] == FIRE_BURNING:
                        ignited = True
                    elif c < w - 1 and self.grid[r][c + 1] == FIRE_BURNING:
                        ignited = True
                    if ignited:
                        new_grid[r][c] = FIRE_BURNING
                        new_burning += 1
                    elif self.p_lightning > 0 and _rng.random() < self.p_lightning:
                        # Lightning strike
                        new_grid[r][c] = FIRE_BURNING
                        new_burning += 1
                    else:
                        new_trees += 1
                elif cell == FIRE_CHARRED:
                    if new_cooldown[r][c] > 0:
                        new_cooldown[r][c] -= 1
                    else:
                        new_grid[r][c] = FIRE_EMPTY
                elif cell == FIRE_EMPTY:
                    if self.p_grow > 0 and _rng.random() < self.p_grow:
                        new_grid[r][c] = FIRE_TREE
                        new_trees += 1

        self.grid = new_grid
        self.cooldown = new_cooldown
        self.tree_count = new_trees + new_burning  # burning were trees
        self.burning_count = new_burning
        self.current_fire_size = fires_this_step
        if fires_this_step > 0:
            self.fire_sizes.append(fires_this_step)
            if len(self.fire_sizes) > self.max_fire_history:
                self.fire_sizes.pop(0)

    @property
    def stats(self) -> dict:
        total_cells = self.width * self.height
        tree_ct = 0
        burn_ct = 0
        char_ct = 0
        for row in self.grid:
            for v in row:
                if v == FIRE_TREE:
                    tree_ct += 1
                elif v == FIRE_BURNING:
                    burn_ct += 1
                elif v == FIRE_CHARRED:
                    char_ct += 1
        density = tree_ct / max(total_cells, 1)
        avg_fire = 0.0
        if self.fire_sizes:
            avg_fire = sum(self.fire_sizes) / len(self.fire_sizes)
        return {
            "trees": tree_ct,
            "burning": burn_ct,
            "charred": char_ct,
            "density": density,
            "total_burned": self.total_burned,
            "current_fire": self.current_fire_size,
            "avg_fire": avg_fire,
            "max_fire": max(self.fire_sizes) if self.fire_sizes else 0,
        }

    def sparkline(self, width: int = 30) -> str:
        """Return a unicode sparkline of recent fire sizes."""
        if not self.fire_sizes:
            return ""
        data = self.fire_sizes[-width:]
        mx = max(data) if data else 1
        if mx == 0:
            mx = 1
        bars = "▁▂▃▄▅▆▇█"
        return "".join(bars[min(int(v / mx * (len(bars) - 1)), len(bars) - 1)] for v in data)


# ---------------------------------------------------------------------------
# Epidemic SIR (Susceptible-Infected-Recovered) simulation
# ---------------------------------------------------------------------------

SIR_SUSCEPTIBLE = 0
SIR_INFECTED = 1
SIR_RECOVERED = 2
SIR_DEAD = 3

SIR_PRESETS = {
    "classic": {
        "desc": "Classic SIR — moderate transmission and recovery",
        "beta": 0.3,
        "gamma": 0.05,
        "mortality": 0.0,
        "init_infected": 0.01,
        "init_density": 1.0,
    },
    "highly-contagious": {
        "desc": "Fast-spreading pathogen with high transmission",
        "beta": 0.6,
        "gamma": 0.03,
        "mortality": 0.0,
        "init_infected": 0.005,
        "init_density": 1.0,
    },
    "deadly-plague": {
        "desc": "High mortality — watch the population decline",
        "beta": 0.4,
        "gamma": 0.04,
        "mortality": 0.02,
        "init_infected": 0.005,
        "init_density": 1.0,
    },
    "slow-burn": {
        "desc": "Low transmission, slow recovery — long epidemic curve",
        "beta": 0.15,
        "gamma": 0.02,
        "mortality": 0.0,
        "init_infected": 0.02,
        "init_density": 1.0,
    },
    "sparse-population": {
        "desc": "Sparse population — natural social distancing",
        "beta": 0.4,
        "gamma": 0.05,
        "mortality": 0.0,
        "init_infected": 0.02,
        "init_density": 0.5,
    },
    "pandemic": {
        "desc": "Dense population, high mortality — worst case scenario",
        "beta": 0.5,
        "gamma": 0.03,
        "mortality": 0.03,
        "init_infected": 0.002,
        "init_density": 1.0,
    },
}
SIR_PRESET_NAMES = list(SIR_PRESETS.keys())

# ── Maze Generator & Solver constants ─────────────────────────────────────

MAZE_WALL = 0
MAZE_PATH = 1
MAZE_START = 2
MAZE_END = 3
MAZE_VISITED = 4      # A* explored
MAZE_SOLUTION = 5     # final solution path
MAZE_FRONTIER = 6     # A* frontier (open set)
MAZE_CARVING = 7      # cell being carved during generation

MAZE_PRESETS = {
    "classic": {
        "desc": "Classic recursive-backtracker maze",
        "algorithm": "backtracker",
        "solve_speed": 3,
        "gen_speed": 5,
        "loop_chance": 0.0,
    },
    "braided": {
        "desc": "Maze with extra loops — multiple solution paths",
        "algorithm": "backtracker",
        "solve_speed": 3,
        "gen_speed": 5,
        "loop_chance": 0.15,
    },
    "sparse": {
        "desc": "Sparse maze with many open areas",
        "algorithm": "backtracker",
        "solve_speed": 5,
        "gen_speed": 8,
        "loop_chance": 0.35,
    },
    "dense": {
        "desc": "Dense corridors with slow solving",
        "algorithm": "backtracker",
        "solve_speed": 1,
        "gen_speed": 3,
        "loop_chance": 0.0,
    },
    "speed-run": {
        "desc": "Fast generation and blazing solver",
        "algorithm": "backtracker",
        "solve_speed": 20,
        "gen_speed": 40,
        "loop_chance": 0.0,
    },
}
MAZE_PRESET_NAMES = list(MAZE_PRESETS.keys())


class MazeWorld:
    """Maze generator (recursive backtracker) + A* solver with step-by-step viz."""

    def __init__(self, width: int, height: int, preset: str = "classic"):
        # Maze dimensions must be odd for clean walls
        self.width = width if width % 2 == 1 else width - 1
        self.height = height if height % 2 == 1 else height - 1
        self.width = max(5, self.width)
        self.height = max(5, self.height)
        self.preset_idx = MAZE_PRESET_NAMES.index(preset)
        self.solve_speed = 3
        self.gen_speed = 5
        self.loop_chance = 0.0

        # Grid state
        self.grid: list[list[int]] = []

        # Generation state
        self.gen_stack: list[tuple[int, int]] = []
        self.generating = False
        self.gen_done = False

        # Solver state
        self.solving = False
        self.solve_done = False
        self.open_set: list[tuple[float, int, int]] = []  # (f_score, r, c)
        self.came_from: dict[tuple[int, int], tuple[int, int]] = {}
        self.g_score: dict[tuple[int, int], float] = {}
        self.start: tuple[int, int] = (1, 1)
        self.end: tuple[int, int] = (1, 1)
        self.solution_path: list[tuple[int, int]] = []
        self.solution_draw_idx = 0
        self.drawing_solution = False

        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        cfg = MAZE_PRESETS[name]
        self.solve_speed = cfg["solve_speed"]
        self.gen_speed = cfg["gen_speed"]
        self.loop_chance = cfg["loop_chance"]
        self._init_grid()
        self._start_generation()

    def _init_grid(self) -> None:
        """Fill grid with walls."""
        self.grid = [[MAZE_WALL] * self.width for _ in range(self.height)]
        self.gen_done = False
        self.solving = False
        self.solve_done = False
        self.open_set = []
        self.came_from = {}
        self.g_score = {}
        self.solution_path = []
        self.solution_draw_idx = 0
        self.drawing_solution = False

    def _start_generation(self) -> None:
        """Begin recursive-backtracker maze generation."""
        import random as _rng
        self._init_grid()
        # Start carving from (1,1)
        sr, sc = 1, 1
        self.grid[sr][sc] = MAZE_CARVING
        self.gen_stack = [(sr, sc)]
        self.generating = True
        self.gen_done = False

    def _gen_step(self) -> None:
        """One step of recursive-backtracker generation."""
        import random as _rng
        if not self.gen_stack:
            self.generating = False
            self.gen_done = True
            self._finalize_generation()
            return

        r, c = self.gen_stack[-1]
        # Convert current carving to path
        if self.grid[r][c] == MAZE_CARVING:
            self.grid[r][c] = MAZE_PATH

        # Find unvisited neighbors (2 cells away)
        neighbors = []
        for dr, dc in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            nr, nc = r + dr, c + dc
            if 0 < nr < self.height - 1 and 0 < nc < self.width - 1:
                if self.grid[nr][nc] == MAZE_WALL:
                    neighbors.append((nr, nc, r + dr // 2, c + dc // 2))

        if neighbors:
            _rng.shuffle(neighbors)
            nr, nc, wr, wc = neighbors[0]
            self.grid[wr][wc] = MAZE_PATH  # carve wall between
            self.grid[nr][nc] = MAZE_CARVING
            self.gen_stack.append((nr, nc))
        else:
            self.gen_stack.pop()

    def _finalize_generation(self) -> None:
        """Post-generation: add loops, set start/end."""
        import random as _rng

        # Optionally add loops (braid the maze)
        if self.loop_chance > 0:
            for r in range(1, self.height - 1):
                for c in range(1, self.width - 1):
                    if self.grid[r][c] == MAZE_WALL:
                        # Count adjacent path cells
                        adj_paths = 0
                        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < self.height and 0 <= nc < self.width:
                                if self.grid[nr][nc] == MAZE_PATH:
                                    adj_paths += 1
                        if adj_paths >= 2 and _rng.random() < self.loop_chance:
                            self.grid[r][c] = MAZE_PATH

        # Set start and end
        self.start = (1, 1)
        # End at bottom-right path cell
        er = self.height - 2 if (self.height - 2) % 2 == 1 else self.height - 3
        ec = self.width - 2 if (self.width - 2) % 2 == 1 else self.width - 3
        self.end = (er, ec)
        self.grid[self.start[0]][self.start[1]] = MAZE_START
        self.grid[self.end[0]][self.end[1]] = MAZE_END

    def start_solve(self) -> None:
        """Begin A* pathfinding from start to end."""
        import heapq
        self.solving = True
        self.solve_done = False
        self.drawing_solution = False
        self.solution_path = []
        self.solution_draw_idx = 0

        # Clear previous solve visuals
        for r in range(self.height):
            for c in range(self.width):
                if self.grid[r][c] in (MAZE_VISITED, MAZE_SOLUTION, MAZE_FRONTIER):
                    self.grid[r][c] = MAZE_PATH

        sr, sc = self.start
        er, ec = self.end
        self.grid[sr][sc] = MAZE_START
        self.grid[er][ec] = MAZE_END

        self.g_score = {(sr, sc): 0.0}
        f = self._heuristic(sr, sc, er, ec)
        self.open_set = [(f, sr, sc)]
        self.came_from = {}

    def _heuristic(self, r: int, c: int, er: int, ec: int) -> float:
        """Manhattan distance heuristic."""
        return float(abs(r - er) + abs(c - ec))

    def _solve_step(self) -> None:
        """One step of A* search."""
        import heapq
        if not self.open_set:
            self.solving = False
            self.solve_done = True
            return

        _, cr, cc = heapq.heappop(self.open_set)

        if (cr, cc) == self.end:
            self.solving = False
            self._reconstruct_path()
            return

        # Mark as visited
        if self.grid[cr][cc] not in (MAZE_START, MAZE_END):
            self.grid[cr][cc] = MAZE_VISITED

        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = cr + dr, cc + dc
            if 0 <= nr < self.height and 0 <= nc < self.width:
                cell = self.grid[nr][nc]
                if cell == MAZE_WALL:
                    continue
                tent_g = self.g_score.get((cr, cc), float('inf')) + 1.0
                if tent_g < self.g_score.get((nr, nc), float('inf')):
                    self.came_from[(nr, nc)] = (cr, cc)
                    self.g_score[(nr, nc)] = tent_g
                    f = tent_g + self._heuristic(nr, nc, self.end[0], self.end[1])
                    heapq.heappush(self.open_set, (f, nr, nc))
                    if cell not in (MAZE_START, MAZE_END, MAZE_VISITED):
                        self.grid[nr][nc] = MAZE_FRONTIER

    def _reconstruct_path(self) -> None:
        """Build solution path from came_from map."""
        path = []
        current = self.end
        while current in self.came_from:
            path.append(current)
            current = self.came_from[current]
        path.append(self.start)
        path.reverse()
        self.solution_path = path
        self.solution_draw_idx = 0
        self.drawing_solution = True

    def _draw_solution_step(self) -> None:
        """Animate drawing the solution path one cell at a time."""
        if self.solution_draw_idx < len(self.solution_path):
            r, c = self.solution_path[self.solution_draw_idx]
            if self.grid[r][c] not in (MAZE_START, MAZE_END):
                self.grid[r][c] = MAZE_SOLUTION
            self.solution_draw_idx += 1
        else:
            self.drawing_solution = False
            self.solve_done = True

    def tick(self) -> None:
        """Advance the simulation by one tick."""
        if self.generating:
            for _ in range(self.gen_speed):
                if self.generating:
                    self._gen_step()
            # Auto-start solving when generation finishes
            if self.gen_done and not self.solving and not self.solve_done:
                self.start_solve()
        elif self.solving:
            for _ in range(self.solve_speed):
                if self.solving:
                    self._solve_step()
        elif self.drawing_solution:
            for _ in range(max(1, self.solve_speed // 2)):
                if self.drawing_solution:
                    self._draw_solution_step()

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(MAZE_PRESET_NAMES)
        name = MAZE_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        self._apply_preset(MAZE_PRESET_NAMES[self.preset_idx])

    def toggle_wall(self, r: int, c: int) -> None:
        """Toggle a wall at grid position (r, c)."""
        if 0 < r < self.height - 1 and 0 < c < self.width - 1:
            if self.grid[r][c] == MAZE_WALL:
                self.grid[r][c] = MAZE_PATH
            elif self.grid[r][c] in (MAZE_PATH, MAZE_VISITED, MAZE_SOLUTION, MAZE_FRONTIER):
                self.grid[r][c] = MAZE_WALL

    @property
    def phase(self) -> str:
        if self.generating:
            return "GENERATING"
        elif self.solving:
            return "SOLVING"
        elif self.drawing_solution:
            return "TRACING"
        elif self.solve_done:
            return "DONE"
        elif self.gen_done:
            return "READY"
        else:
            return "IDLE"

    @property
    def stats(self) -> dict:
        walls = paths = visited = solution = frontier = 0
        for row in self.grid:
            for cell in row:
                if cell == MAZE_WALL:
                    walls += 1
                elif cell in (MAZE_PATH, MAZE_START, MAZE_END):
                    paths += 1
                elif cell == MAZE_VISITED:
                    visited += 1
                elif cell == MAZE_SOLUTION:
                    solution += 1
                elif cell == MAZE_FRONTIER:
                    frontier += 1
        return {
            "walls": walls,
            "paths": paths,
            "visited": visited,
            "solution": solution,
            "frontier": frontier,
            "sol_len": len(self.solution_path) if self.solution_path else 0,
        }


# ---------------------------------------------------------------------------
# Mandelbrot & Julia Set Fractal Explorer
# ---------------------------------------------------------------------------

FRACTAL_PRESETS = {
    "classic": {
        "center_re": -0.5,
        "center_im": 0.0,
        "zoom": 1.0,
        "max_iter": 80,
        "julia_mode": False,
        "julia_re": -0.7,
        "julia_im": 0.27015,
    },
    "seahorse-valley": {
        "center_re": -0.745,
        "center_im": 0.186,
        "zoom": 200.0,
        "max_iter": 150,
        "julia_mode": False,
        "julia_re": -0.745,
        "julia_im": 0.186,
    },
    "spiral": {
        "center_re": -0.761574,
        "center_im": -0.0847596,
        "zoom": 500.0,
        "max_iter": 200,
        "julia_mode": False,
        "julia_re": -0.761574,
        "julia_im": -0.0847596,
    },
    "julia-dendrite": {
        "center_re": 0.0,
        "center_im": 0.0,
        "zoom": 1.0,
        "max_iter": 100,
        "julia_mode": True,
        "julia_re": 0.0,
        "julia_im": 1.0,
    },
    "julia-rabbit": {
        "center_re": 0.0,
        "center_im": 0.0,
        "zoom": 1.0,
        "max_iter": 100,
        "julia_mode": True,
        "julia_re": -0.123,
        "julia_im": 0.745,
    },
    "julia-galaxy": {
        "center_re": 0.0,
        "center_im": 0.0,
        "zoom": 1.0,
        "max_iter": 120,
        "julia_mode": True,
        "julia_re": -0.8,
        "julia_im": 0.156,
    },
}
FRACTAL_PRESET_NAMES = list(FRACTAL_PRESETS.keys())

FRACTAL_PALETTES = [
    "classic",
    "fire",
    "ocean",
    "neon",
    "grayscale",
]


class FractalWorld:
    """Interactive Mandelbrot & Julia set fractal explorer."""

    def __init__(self, width: int, height: int, preset: str = "classic"):
        self.width = width
        self.height = height
        self.preset_idx = FRACTAL_PRESET_NAMES.index(preset)
        self.palette_idx = 0

        # View parameters
        self.center_re = -0.5
        self.center_im = 0.0
        self.zoom = 1.0
        self.max_iter = 80

        # Julia mode
        self.julia_mode = False
        self.julia_re = -0.7
        self.julia_im = 0.27015

        # Cursor position (grid coords for Julia c selection)
        self.cursor_r = height // 2
        self.cursor_c = width // 2

        # Pre-computed iteration grid
        self.grid: list[list[int]] = [[0] * width for _ in range(height)]
        self.dirty = True

        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        cfg = FRACTAL_PRESETS[name]
        self.center_re = cfg["center_re"]
        self.center_im = cfg["center_im"]
        self.zoom = cfg["zoom"]
        self.max_iter = cfg["max_iter"]
        self.julia_mode = cfg["julia_mode"]
        self.julia_re = cfg["julia_re"]
        self.julia_im = cfg["julia_im"]
        self.dirty = True

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(FRACTAL_PRESET_NAMES)
        name = FRACTAL_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def cycle_palette(self, direction: int = 1) -> str:
        self.palette_idx = (self.palette_idx + direction) % len(FRACTAL_PALETTES)
        self.dirty = True
        return FRACTAL_PALETTES[self.palette_idx]

    def reset(self) -> None:
        self._apply_preset(FRACTAL_PRESET_NAMES[self.preset_idx])

    def pan(self, dr: float, di: float) -> None:
        """Pan the view by (dr, di) in complex-plane units scaled by zoom."""
        scale = 3.0 / self.zoom
        self.center_re += dr * scale * 0.1
        self.center_im += di * scale * 0.1
        self.dirty = True

    def zoom_in(self, factor: float = 1.5) -> None:
        self.zoom *= factor
        self.dirty = True

    def zoom_out(self, factor: float = 1.5) -> None:
        self.zoom /= factor
        if self.zoom < 0.1:
            self.zoom = 0.1
        self.dirty = True

    def increase_iter(self, amount: int = 20) -> None:
        self.max_iter = min(1000, self.max_iter + amount)
        self.dirty = True

    def decrease_iter(self, amount: int = 20) -> None:
        self.max_iter = max(10, self.max_iter - amount)
        self.dirty = True

    def toggle_julia(self) -> None:
        """Toggle between Mandelbrot and Julia mode.

        When switching to Julia, use cursor position as c parameter.
        """
        if not self.julia_mode:
            # Compute the complex coordinate at cursor
            re, im = self._grid_to_complex(self.cursor_r, self.cursor_c)
            self.julia_re = re
            self.julia_im = im
            self.julia_mode = True
            # Reset view for Julia set
            self.center_re = 0.0
            self.center_im = 0.0
            self.zoom = 1.0
        else:
            self.julia_mode = False
            self.center_re = -0.5
            self.center_im = 0.0
            self.zoom = 1.0
        self.dirty = True

    def _grid_to_complex(self, row: int, col: int) -> tuple[float, float]:
        """Convert grid coordinates to complex plane coordinates."""
        aspect = self.width / max(1, self.height)
        scale = 3.0 / self.zoom
        re = self.center_re + (col - self.width / 2) / self.width * scale * aspect
        im = self.center_im + (row - self.height / 2) / self.height * scale
        return re, im

    def compute(self) -> None:
        """Recompute the fractal iteration counts for the current view."""
        if not self.dirty:
            return
        w, h = self.width, self.height
        aspect = w / max(1, h)
        scale = 3.0 / self.zoom
        cx = self.center_re
        cy = self.center_im
        mi = self.max_iter
        julia = self.julia_mode
        jre = self.julia_re
        jim = self.julia_im

        for r in range(h):
            row_data = self.grid[r]
            im = cy + (r - h / 2) / h * scale
            for c in range(w):
                re = cx + (c - w / 2) / w * scale * aspect

                if julia:
                    zr, zi = re, im
                    cr, ci = jre, jim
                else:
                    zr, zi = 0.0, 0.0
                    cr, ci = re, im

                n = 0
                while n < mi and zr * zr + zi * zi <= 4.0:
                    zr, zi = zr * zr - zi * zi + cr, 2.0 * zr * zi + ci
                    n += 1

                row_data[c] = n

        self.dirty = False

    def tick(self) -> None:
        """Recompute if dirty (called each frame)."""
        self.compute()

    def iter_to_char_attr(self, n: int, use_color: bool) -> tuple[str, int]:
        """Map iteration count to a display character and curses attribute."""
        if n >= self.max_iter:
            return "  ", curses.A_NORMAL  # inside set = black

        palette = FRACTAL_PALETTES[self.palette_idx]
        t = n / max(1, self.max_iter)

        # Shade characters from sparse to dense
        shades = " ░▒▓█"
        si = min(len(shades) - 1, int(t * len(shades)))
        ch = shades[si] * 2

        if not use_color:
            if n >= self.max_iter:
                return "  ", curses.A_NORMAL
            levels = [curses.A_DIM, curses.A_NORMAL, curses.A_BOLD]
            return ch, levels[min(2, int(t * 3))]

        # Map to color pairs 180-195 based on palette and iteration
        if palette == "classic":
            # Blue -> Cyan -> Green -> Yellow -> Red cycle
            colors = [180, 181, 182, 183, 184, 185, 186]
        elif palette == "fire":
            colors = [187, 188, 189, 183, 183, 189, 188]
        elif palette == "ocean":
            colors = [180, 181, 190, 181, 180, 190, 181]
        elif palette == "neon":
            colors = [191, 192, 193, 191, 192, 193, 191]
        else:  # grayscale
            colors = [194, 195, 194, 195, 194, 195, 194]

        ci = int(t * (len(colors) - 1))
        ci = min(ci, len(colors) - 1)
        pair = colors[ci]

        attr = curses.color_pair(pair)
        if t > 0.7:
            attr |= curses.A_BOLD

        return ch, attr

    @property
    def cursor_complex(self) -> tuple[float, float]:
        """Return the complex coordinate at the current cursor position."""
        return self._grid_to_complex(self.cursor_r, self.cursor_c)

    @property
    def stats(self) -> dict:
        mode = "Julia" if self.julia_mode else "Mandelbrot"
        re, im = self.cursor_complex
        return {
            "mode": mode,
            "center_re": self.center_re,
            "center_im": self.center_im,
            "zoom": self.zoom,
            "max_iter": self.max_iter,
            "cursor_re": re,
            "cursor_im": im,
            "julia_re": self.julia_re,
            "julia_im": self.julia_im,
            "palette": FRACTAL_PALETTES[self.palette_idx],
        }


ATTRACTOR_PRESETS = {
    "lorenz-classic": {
        "type": "lorenz",
        "sigma": 10.0,
        "rho": 28.0,
        "beta": 8.0 / 3.0,
        "dt": 0.005,
        "steps_per_tick": 50,
        "trail_len": 8000,
    },
    "lorenz-chaotic": {
        "type": "lorenz",
        "sigma": 10.0,
        "rho": 99.96,
        "beta": 8.0 / 3.0,
        "dt": 0.003,
        "steps_per_tick": 60,
        "trail_len": 10000,
    },
    "rossler-classic": {
        "type": "rossler",
        "a": 0.2,
        "b": 0.2,
        "c": 5.7,
        "dt": 0.01,
        "steps_per_tick": 40,
        "trail_len": 8000,
    },
    "rossler-funnel": {
        "type": "rossler",
        "a": 0.2,
        "b": 0.2,
        "c": 14.0,
        "dt": 0.005,
        "steps_per_tick": 50,
        "trail_len": 10000,
    },
    "henon": {
        "type": "henon",
        "a": 1.4,
        "b": 0.3,
        "dt": 1.0,
        "steps_per_tick": 200,
        "trail_len": 20000,
    },
    "henon-wide": {
        "type": "henon",
        "a": 1.2,
        "b": 0.3,
        "dt": 1.0,
        "steps_per_tick": 200,
        "trail_len": 25000,
    },
}
ATTRACTOR_PRESET_NAMES = list(ATTRACTOR_PRESETS.keys())

ATTRACTOR_PALETTES = ["heat", "electric", "ice", "grayscale"]


class AttractorWorld:
    """Strange Attractor visualization — Lorenz, Rössler, and Hénon attractors."""

    def __init__(self, width: int, height: int, preset: str = "lorenz-classic"):
        self.width = width
        self.height = height
        self.preset_idx = ATTRACTOR_PRESET_NAMES.index(preset)
        self.palette_idx = 0

        # Attractor type and parameters
        self.attractor_type = "lorenz"
        self.sigma = 10.0
        self.rho = 28.0
        self.beta = 8.0 / 3.0
        # Rössler params
        self.a = 0.2
        self.b = 0.2
        self.c = 5.7
        # Hénon params
        self.henon_a = 1.4
        self.henon_b = 0.3

        self.dt = 0.005
        self.steps_per_tick = 50
        self.trail_len = 8000

        # State
        self.x, self.y, self.z = 1.0, 1.0, 1.0
        self.trail: list[tuple[float, float, float]] = []
        self.density: list[list[int]] = [[0] * width for _ in range(height)]
        self.max_density = 1
        self.total_steps = 0

        # View rotation (for 3D attractors)
        self.rot_angle = 0.0  # radians around Y axis
        self.auto_rotate = True
        self.rot_speed = 0.02

        # Zoom / pan
        self.view_scale = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        cfg = ATTRACTOR_PRESETS[name]
        self.attractor_type = cfg["type"]
        self.dt = cfg["dt"]
        self.steps_per_tick = cfg["steps_per_tick"]
        self.trail_len = cfg["trail_len"]
        if self.attractor_type == "lorenz":
            self.sigma = cfg["sigma"]
            self.rho = cfg["rho"]
            self.beta = cfg["beta"]
            self.x, self.y, self.z = 1.0, 1.0, 1.0
        elif self.attractor_type == "rossler":
            self.a = cfg["a"]
            self.b = cfg["b"]
            self.c = cfg["c"]
            self.x, self.y, self.z = 1.0, 1.0, 1.0
        elif self.attractor_type == "henon":
            self.henon_a = cfg["a"]
            self.henon_b = cfg["b"]
            self.x, self.y = 0.1, 0.1
            self.z = 0.0
        self.trail.clear()
        self.total_steps = 0
        self.rot_angle = 0.0
        self._clear_density()

    def _clear_density(self) -> None:
        for r in range(self.height):
            for c in range(self.width):
                self.density[r][c] = 0
        self.max_density = 1

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(ATTRACTOR_PRESET_NAMES)
        name = ATTRACTOR_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def cycle_palette(self, direction: int = 1) -> str:
        self.palette_idx = (self.palette_idx + direction) % len(ATTRACTOR_PALETTES)
        return ATTRACTOR_PALETTES[self.palette_idx]

    def reset(self) -> None:
        self._apply_preset(ATTRACTOR_PRESET_NAMES[self.preset_idx])
        self.view_scale = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

    def _step_lorenz(self) -> None:
        dt = self.dt
        dx = self.sigma * (self.y - self.x) * dt
        dy = (self.x * (self.rho - self.z) - self.y) * dt
        dz = (self.x * self.y - self.beta * self.z) * dt
        self.x += dx
        self.y += dy
        self.z += dz

    def _step_rossler(self) -> None:
        dt = self.dt
        dx = (-self.y - self.z) * dt
        dy = (self.x + self.a * self.y) * dt
        dz = (self.b + self.z * (self.x - self.c)) * dt
        self.x += dx
        self.y += dy
        self.z += dz

    def _step_henon(self) -> None:
        xn = 1.0 - self.henon_a * self.x * self.x + self.y
        yn = self.henon_b * self.x
        self.x, self.y = xn, yn
        self.z = 0.0

    def _project(self, px: float, py: float, pz: float) -> tuple[int, int]:
        """Project a 3D point to 2D grid coordinates with rotation."""
        if self.attractor_type == "henon":
            # 2D attractor, just scale directly
            sx = px * self.view_scale + self.pan_x
            sy = py * self.view_scale + self.pan_y
        else:
            # Rotate around Y axis
            cos_a = math.cos(self.rot_angle)
            sin_a = math.sin(self.rot_angle)
            rx = px * cos_a + pz * sin_a
            ry = py
            sx = rx * self.view_scale + self.pan_x
            sy = ry * self.view_scale + self.pan_y

        # Map to grid
        if self.attractor_type == "lorenz":
            # Lorenz: x ~ [-20,20], y ~ [-30,30], z ~ [0,50]
            col = int(self.width / 2 + sx * self.width / 50)
            row = int(self.height - sy * self.height / 60)
        elif self.attractor_type == "rossler":
            # Rössler: x,y ~ [-15,15], z ~ [0,25]
            col = int(self.width / 2 + sx * self.width / 40)
            row = int(self.height / 2 - sy * self.height / 40)
        else:
            # Hénon: x ~ [-1.5,1.5], y ~ [-0.4,0.4]
            col = int(self.width / 2 + sx * self.width / 4)
            row = int(self.height / 2 - sy * self.height / 1.2)
        return row, col

    def tick(self) -> None:
        step_fn = {
            "lorenz": self._step_lorenz,
            "rossler": self._step_rossler,
            "henon": self._step_henon,
        }[self.attractor_type]

        for _ in range(self.steps_per_tick):
            step_fn()
            # Check for divergence
            if abs(self.x) > 1e6 or abs(self.y) > 1e6 or abs(self.z) > 1e6:
                self.x, self.y, self.z = 1.0, 1.0, 1.0
                self.trail.clear()
                self._clear_density()
                break
            self.trail.append((self.x, self.y, self.z))
            self.total_steps += 1

        # Trim trail
        if len(self.trail) > self.trail_len:
            self.trail = self.trail[-self.trail_len:]

        # Auto-rotate for 3D attractors
        if self.auto_rotate and self.attractor_type != "henon":
            self.rot_angle += self.rot_speed

        # Rebuild density map from trail
        self._clear_density()
        for px, py, pz in self.trail:
            r, c = self._project(px, py, pz)
            if 0 <= r < self.height and 0 <= c < self.width:
                self.density[r][c] += 1
                if self.density[r][c] > self.max_density:
                    self.max_density = self.density[r][c]

    def density_to_char_attr(self, val: int, use_color: bool) -> tuple[str, int]:
        """Map density value to display character and curses attribute."""
        if val == 0:
            return "  ", curses.A_NORMAL

        t = min(1.0, val / max(1, self.max_density * 0.6))

        shades = " ·∙░▒▓█"
        si = max(1, min(len(shades) - 1, int(t * (len(shades) - 1))))
        ch = shades[si]
        # Use double-width for denser shades
        if si >= 4:
            ch = shades[si] * 2
        else:
            ch = " " + shades[si]

        if not use_color:
            levels = [curses.A_DIM, curses.A_NORMAL, curses.A_BOLD]
            return ch, levels[min(2, int(t * 3))]

        palette = ATTRACTOR_PALETTES[self.palette_idx]
        # Color pairs 200-209
        if palette == "heat":
            colors = [200, 201, 202, 203, 204]
        elif palette == "electric":
            colors = [205, 206, 207, 205, 206]
        elif palette == "ice":
            colors = [208, 209, 208, 209, 208]
        else:  # grayscale
            colors = [194, 195, 194, 195, 194]

        ci = min(len(colors) - 1, int(t * (len(colors) - 1)))
        attr = curses.color_pair(colors[ci])
        if t > 0.5:
            attr |= curses.A_BOLD

        return ch, attr

    def adjust_param(self, param: str, delta: float) -> float:
        """Adjust an attractor parameter and return new value."""
        if self.attractor_type == "lorenz":
            if param == "sigma":
                self.sigma = max(0.1, self.sigma + delta)
                return self.sigma
            elif param == "rho":
                self.rho = max(0.1, self.rho + delta)
                return self.rho
            elif param == "beta":
                self.beta = max(0.1, self.beta + delta)
                return self.beta
        elif self.attractor_type == "rossler":
            if param == "a":
                self.a = max(0.01, self.a + delta)
                return self.a
            elif param == "b":
                self.b = max(0.01, self.b + delta)
                return self.b
            elif param == "c":
                self.c = max(0.1, self.c + delta)
                return self.c
        elif self.attractor_type == "henon":
            if param == "a":
                self.henon_a = max(0.1, self.henon_a + delta)
                return self.henon_a
            elif param == "b":
                self.henon_b = max(0.01, self.henon_b + delta)
                return self.henon_b
        return 0.0

    def toggle_rotate(self) -> bool:
        self.auto_rotate = not self.auto_rotate
        return self.auto_rotate

    @property
    def stats(self) -> dict:
        params: dict = {"type": self.attractor_type}
        if self.attractor_type == "lorenz":
            params.update({"σ": self.sigma, "ρ": self.rho, "β": round(self.beta, 3)})
        elif self.attractor_type == "rossler":
            params.update({"a": self.a, "b": self.b, "c": self.c})
        else:
            params.update({"a": self.henon_a, "b": self.henon_b})
        return {
            "attractor": self.attractor_type.capitalize(),
            "params": params,
            "steps": self.total_steps,
            "trail": len(self.trail),
            "max_density": self.max_density,
            "palette": ATTRACTOR_PALETTES[self.palette_idx],
            "rotate": self.auto_rotate,
        }


class SIRWorld:
    """Epidemic SIR (Susceptible-Infected-Recovered) grid simulation."""

    def __init__(self, width: int, height: int, preset: str = "classic"):
        self.width = width
        self.height = height
        self.preset_idx = SIR_PRESET_NAMES.index(preset)
        self.beta = 0.3        # transmission probability per infected neighbor
        self.gamma = 0.05      # recovery probability per tick
        self.mortality = 0.0   # death probability on recovery
        self.steps_per_tick = 1
        # Grid: 0=susceptible, 1=infected, 2=recovered, 3=dead
        self.grid = [[SIR_SUSCEPTIBLE] * width for _ in range(height)]
        # Infection age (ticks since infection)
        self.age = [[0] * width for _ in range(height)]
        # Statistics history
        self.s_history: list[int] = []
        self.i_history: list[int] = []
        self.r_history: list[int] = []
        self.d_history: list[int] = []
        self.max_history = 200
        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        import random as _rng
        cfg = SIR_PRESETS[name]
        self.beta = cfg["beta"]
        self.gamma = cfg["gamma"]
        self.mortality = cfg["mortality"]
        self.grid = [[SIR_SUSCEPTIBLE] * self.width for _ in range(self.height)]
        self.age = [[0] * self.width for _ in range(self.height)]
        self.s_history = []
        self.i_history = []
        self.r_history = []
        self.d_history = []
        density = cfg["init_density"]
        inf_rate = cfg["init_infected"]
        for r in range(self.height):
            for c in range(self.width):
                if _rng.random() < density:
                    if _rng.random() < inf_rate:
                        self.grid[r][c] = SIR_INFECTED
                        self.age[r][c] = 1
                    else:
                        self.grid[r][c] = SIR_SUSCEPTIBLE
                else:
                    # Empty cell (treated as recovered/immune for simplicity)
                    self.grid[r][c] = SIR_RECOVERED

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(SIR_PRESET_NAMES)
        name = SIR_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        self._apply_preset(SIR_PRESET_NAMES[self.preset_idx])

    def infect_at(self, r: int, c: int) -> None:
        """Manually infect a cell at (r, c)."""
        if 0 <= r < self.height and 0 <= c < self.width:
            if self.grid[r][c] == SIR_SUSCEPTIBLE:
                self.grid[r][c] = SIR_INFECTED
                self.age[r][c] = 1

    def tick(self) -> None:
        import random as _rng
        for _ in range(self.steps_per_tick):
            self._step(_rng)

    def _step(self, _rng) -> None:
        w, h = self.width, self.height
        new_grid = [row[:] for row in self.grid]
        new_age = [row[:] for row in self.age]

        for r in range(h):
            for c in range(w):
                cell = self.grid[r][c]
                if cell == SIR_SUSCEPTIBLE:
                    # Count infected neighbors (von Neumann)
                    inf_neighbors = 0
                    if r > 0 and self.grid[r - 1][c] == SIR_INFECTED:
                        inf_neighbors += 1
                    if r < h - 1 and self.grid[r + 1][c] == SIR_INFECTED:
                        inf_neighbors += 1
                    if c > 0 and self.grid[r][c - 1] == SIR_INFECTED:
                        inf_neighbors += 1
                    if c < w - 1 and self.grid[r][c + 1] == SIR_INFECTED:
                        inf_neighbors += 1
                    # Probability of infection: 1 - (1 - beta)^inf_neighbors
                    if inf_neighbors > 0:
                        p_infect = 1.0 - (1.0 - self.beta) ** inf_neighbors
                        if _rng.random() < p_infect:
                            new_grid[r][c] = SIR_INFECTED
                            new_age[r][c] = 1
                elif cell == SIR_INFECTED:
                    new_age[r][c] = self.age[r][c] + 1
                    if _rng.random() < self.gamma:
                        if self.mortality > 0 and _rng.random() < self.mortality:
                            new_grid[r][c] = SIR_DEAD
                        else:
                            new_grid[r][c] = SIR_RECOVERED
                        new_age[r][c] = 0

        self.grid = new_grid
        self.age = new_age
        # Record statistics
        s_ct, i_ct, r_ct, d_ct = self._count()
        self.s_history.append(s_ct)
        self.i_history.append(i_ct)
        self.r_history.append(r_ct)
        self.d_history.append(d_ct)
        if len(self.s_history) > self.max_history:
            self.s_history.pop(0)
            self.i_history.pop(0)
            self.r_history.pop(0)
            self.d_history.pop(0)

    def _count(self) -> tuple:
        s = i = r = d = 0
        for row in self.grid:
            for v in row:
                if v == SIR_SUSCEPTIBLE:
                    s += 1
                elif v == SIR_INFECTED:
                    i += 1
                elif v == SIR_RECOVERED:
                    r += 1
                elif v == SIR_DEAD:
                    d += 1
        return s, i, r, d

    @property
    def stats(self) -> dict:
        s, i, r, d = self._count()
        total = s + i + r + d
        return {
            "susceptible": s,
            "infected": i,
            "recovered": r,
            "dead": d,
            "total": total,
            "s_pct": s / max(total, 1),
            "i_pct": i / max(total, 1),
            "r_pct": r / max(total, 1),
        }

    def sparkline(self, width: int = 30) -> str:
        """Return a unicode sparkline of recent infected counts."""
        if not self.i_history:
            return ""
        data = self.i_history[-width:]
        mx = max(data) if data else 1
        if mx == 0:
            mx = 1
        bars = "▁▂▃▄▅▆▇█"
        return "".join(bars[min(int(v / mx * (len(bars) - 1)), len(bars) - 1)] for v in data)


# ---------------------------------------------------------------------------
# Abelian Sandpile simulation
# ---------------------------------------------------------------------------

SANDPILE_PRESETS = {
    "center-drop": {
        "desc": "Continuous drops at the center — classic sandpile",
        "drop_mode": "center",
        "threshold": 4,
        "drops_per_tick": 1,
        "init": "empty",
    },
    "random-rain": {
        "desc": "Random grains falling across the grid",
        "drop_mode": "random",
        "threshold": 4,
        "drops_per_tick": 3,
        "init": "empty",
    },
    "identity": {
        "desc": "Start from max and relax — beautiful fractal emerges",
        "drop_mode": "none",
        "threshold": 4,
        "drops_per_tick": 0,
        "init": "max",
    },
    "multi-source": {
        "desc": "Four simultaneous drop points",
        "drop_mode": "multi",
        "threshold": 4,
        "drops_per_tick": 1,
        "init": "empty",
    },
    "high-threshold": {
        "desc": "Threshold 8 — denser patterns, bigger avalanches",
        "drop_mode": "center",
        "threshold": 8,
        "drops_per_tick": 2,
        "init": "empty",
    },
}
SANDPILE_PRESET_NAMES = list(SANDPILE_PRESETS.keys())


class SandpileWorld:
    """Abelian Sandpile model — self-organized criticality."""

    def __init__(self, width: int, height: int, preset: str = "center-drop"):
        self.width = width
        self.height = height
        self.preset_idx = SANDPILE_PRESET_NAMES.index(preset)
        self.threshold = 4
        self.drop_mode = "center"
        self.drops_per_tick = 1
        self.steps_per_tick = 1
        self.grid = [[0] * width for _ in range(height)]
        self.total_grains = 0
        self.total_topplings = 0
        self.avalanche_sizes: list[int] = []  # recent avalanche sizes
        self.max_avalanche_history = 200
        self.current_avalanche = 0
        self._apply_preset(preset)

    def _apply_preset(self, name: str) -> None:
        cfg = SANDPILE_PRESETS[name]
        self.threshold = cfg["threshold"]
        self.drop_mode = cfg["drop_mode"]
        self.drops_per_tick = cfg["drops_per_tick"]
        self.grid = [[0] * self.width for _ in range(self.height)]
        self.total_grains = 0
        self.total_topplings = 0
        self.avalanche_sizes = []
        self.current_avalanche = 0
        if cfg["init"] == "max":
            # Fill every cell with 2 * threshold — will produce identity sandpile
            fill_val = 2 * self.threshold
            for r in range(self.height):
                for c in range(self.width):
                    self.grid[r][c] = fill_val
                    self.total_grains += fill_val

    def cycle_preset(self, direction: int = 1) -> str:
        self.preset_idx = (self.preset_idx + direction) % len(SANDPILE_PRESET_NAMES)
        name = SANDPILE_PRESET_NAMES[self.preset_idx]
        self._apply_preset(name)
        return name

    def reset(self) -> None:
        self._apply_preset(SANDPILE_PRESET_NAMES[self.preset_idx])

    def drop_at(self, r: int, c: int) -> None:
        """Drop a single grain at (r, c)."""
        if 0 <= r < self.height and 0 <= c < self.width:
            self.grid[r][c] += 1
            self.total_grains += 1

    def _drop_grains(self) -> None:
        """Add grains according to the current drop mode."""
        if self.drop_mode == "center":
            cr, cc = self.height // 2, self.width // 2
            for _ in range(self.drops_per_tick):
                self.grid[cr][cc] += 1
                self.total_grains += 1
        elif self.drop_mode == "random":
            import random as _rng
            for _ in range(self.drops_per_tick):
                r = _rng.randint(0, self.height - 1)
                c = _rng.randint(0, self.width - 1)
                self.grid[r][c] += 1
                self.total_grains += 1
        elif self.drop_mode == "multi":
            h4, w4 = self.height // 4, self.width // 4
            points = [
                (h4, w4), (h4, 3 * w4),
                (3 * h4, w4), (3 * h4, 3 * w4),
            ]
            for pr, pc in points:
                for _ in range(self.drops_per_tick):
                    self.grid[pr][pc] += 1
                    self.total_grains += 1
        # "none" — no drops (identity preset)

    def _topple(self) -> int:
        """Perform one full relaxation pass. Return total topplings."""
        threshold = self.threshold
        total = 0
        changed = True
        while changed:
            changed = False
            for r in range(self.height):
                row = self.grid[r]
                for c in range(self.width):
                    if row[c] >= threshold:
                        changed = True
                        excess = row[c] // threshold
                        row[c] -= excess * threshold
                        total += excess
                        # Distribute to neighbors; grains at edges fall off
                        if r > 0:
                            self.grid[r - 1][c] += excess
                        else:
                            self.total_grains -= excess
                        if r < self.height - 1:
                            self.grid[r + 1][c] += excess
                        else:
                            self.total_grains -= excess
                        if c > 0:
                            row[c - 1] += excess
                        else:
                            self.total_grains -= excess
                        if c < self.width - 1:
                            row[c + 1] += excess
                        else:
                            self.total_grains -= excess
        return total

    def tick(self) -> None:
        for _ in range(self.steps_per_tick):
            self._drop_grains()
            topplings = self._topple()
            self.total_topplings += topplings
            if topplings > 0:
                self.current_avalanche = topplings
                self.avalanche_sizes.append(topplings)
                if len(self.avalanche_sizes) > self.max_avalanche_history:
                    self.avalanche_sizes.pop(0)
            else:
                self.current_avalanche = 0

    @property
    def stats(self) -> dict:
        max_val = 0
        for row in self.grid:
            rm = max(row) if row else 0
            if rm > max_val:
                max_val = rm
        avg_aval = 0.0
        if self.avalanche_sizes:
            avg_aval = sum(self.avalanche_sizes) / len(self.avalanche_sizes)
        return {
            "total_grains": self.total_grains,
            "total_topplings": self.total_topplings,
            "max_height": max_val,
            "current_avalanche": self.current_avalanche,
            "avg_avalanche": avg_aval,
            "max_avalanche": max(self.avalanche_sizes) if self.avalanche_sizes else 0,
        }

    def sparkline(self, width: int = 30) -> str:
        """Return a unicode sparkline of recent avalanche sizes."""
        if not self.avalanche_sizes:
            return ""
        # Take last `width` entries
        data = self.avalanche_sizes[-width:]
        mx = max(data) if data else 1
        if mx == 0:
            mx = 1
        bars = "▁▂▃▄▅▆▇█"
        return "".join(bars[min(int(v / mx * (len(bars) - 1)), len(bars) - 1)] for v in data)


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
        # Boids flocking simulation mode
        self.boids_mode = False
        self.boids_world: BoidsWorld | None = None
        self.boids_gen = 0
        self.boids_preset_idx = 0
        # Neural Cellular Automata (NCA) mode
        self.nca_mode = False
        self.nca_world: NCAWorld | None = None
        self.nca_gen = 0
        self.nca_preset_idx = 0
        self.nca_cursor_x = 0
        self.nca_cursor_y = 0
        self.nca_painting = False   # True while painting cells
        self.nca_erasing = False    # True while erasing cells
        self.nca_brush_size = 2     # brush radius
        # Wave Function Collapse (WFC) terrain generation mode
        self.wfc_mode = False
        self.wfc_world: WFCWorld | None = None
        self.wfc_gen = 0
        self.wfc_preset_idx = 0
        # Langton's Turmites mode
        self.turmite_mode = False
        self.turmite_world: TurmiteWorld | None = None
        self.turmite_gen = 0
        self.turmite_preset_idx = 0
        # Hydraulic Erosion mode
        self.erosion_mode = False
        self.erosion_world: ErosionWorld | None = None
        self.erosion_gen = 0
        self.erosion_preset_idx = 0
        # Magnetic Field simulation mode
        self.magfield_mode = False
        self.magfield_world: MagFieldWorld | None = None
        self.magfield_gen = 0
        self.magfield_preset_idx = 0
        # Gravity N-Body simulation mode
        self.nbody_mode = False
        self.nbody_world: NBodyWorld | None = None
        self.nbody_gen = 0
        self.nbody_preset_idx = 0
        # Abelian Sandpile mode
        self.sandpile_mode = False
        self.sandpile_world: SandpileWorld | None = None
        self.sandpile_gen = 0
        self.sandpile_preset_idx = 0
        # Forest Fire mode
        self.forestfire_mode = False
        self.forestfire_world: ForestFireWorld | None = None
        self.forestfire_gen = 0
        self.forestfire_preset_idx = 0
        # DLA (Diffusion-Limited Aggregation) mode
        self.dla_mode = False
        self.dla_world: DLAWorld | None = None
        self.dla_gen = 0
        self.dla_preset_idx = 0
        # Epidemic SIR mode
        self.sir_mode = False
        self.sir_world: SIRWorld | None = None
        self.sir_gen = 0
        self.sir_preset_idx = 0
        # Maze Generator & Solver mode
        self.maze_mode = False
        self.maze_world: MazeWorld | None = None
        self.maze_gen = 0
        self.maze_preset_idx = 0
        # Fractal Explorer mode
        self.fractal_mode = False
        self.fractal_world: FractalWorld | None = None
        self.fractal_gen = 0
        self.fractal_preset_idx = 0
        # Strange Attractor mode
        self.attractor_mode = False
        self.attractor_world: AttractorWorld | None = None
        self.attractor_gen = 0
        self.attractor_preset_idx = 0
        # Demo Tour (screensaver) state
        self.demo_tour_mode = False
        self.demo_tour_idx = 0          # current index into MENU_MODES
        self.demo_tour_start_time = 0.0 # when the current mode started
        self.demo_tour_duration = 10.0  # seconds per mode
        self.demo_tour_paused = False
        # Mode picker menu state
        self.menu_mode = False
        self.menu_cursor = 0        # flat index into visible items
        self.menu_scroll = 0        # scroll offset for long lists
        # Menu catalog: (category, label, description, start_method_name)
        self.MENU_MODES: list[tuple[str, str, str, str]] = [
            # --- Cellular Automata ---
            ("Cellular Automata", "Conway's Game of Life", "Classic 2-state cellular automaton", "_menu_start_life"),
            ("Cellular Automata", "Wolfram 1D (W)", "Elementary 1D cellular automata (256 rules)", "_start_wolfram"),
            ("Cellular Automata", "Lenia (L)", "Continuous cellular automaton with smooth kernels", "_start_lenia"),
            ("Cellular Automata", "Multi-State (X)", "Brian's Brain / Wireworld / Langton's Ant", "_start_multistate"),
            ("Cellular Automata", "Neural CA (N)", "Neural cellular automata with learned update rules", "_start_nca"),
            ("Cellular Automata", "Abelian Sandpile (J)", "Self-organized criticality on a grid", "_start_sandpile"),
            # --- Physics ---
            ("Physics", "Falling Sand (F)", "Particle-based sandbox with multiple materials", "_start_sand"),
            ("Physics", "Reaction-Diffusion (R)", "Gray-Scott reaction-diffusion patterns", "_start_rd"),
            ("Physics", "Fluid Dynamics (D)", "Lattice Boltzmann fluid simulation", "_start_fluid"),
            ("Physics", "Ising Model (I)", "Statistical mechanics spin lattice", "_start_ising"),
            ("Physics", "Magnetic Field (G)", "Electromagnetic particle simulation", "_start_magfield"),
            ("Physics", "N-Body Gravity (K)", "Gravitational N-body simulation", "_start_nbody"),
            ("Physics", "Hydraulic Erosion (Y)", "Terrain erosion by water flow", "_start_erosion"),
            ("Physics", "DLA (L)", "Diffusion-limited aggregation crystal growth", "_start_dla"),
            # --- Biology ---
            ("Biology", "Particle Life (P)", "Emergent life-like behavior from simple attraction rules", "_start_pl"),
            ("Biology", "Wa-Tor Ecosystem (E)", "Predator-prey population dynamics", "_start_eco"),
            ("Biology", "Physarum Slime (S)", "Slime mold agent-based network formation", "_start_physarum"),
            ("Biology", "Boids Flocking (B)", "Reynolds flocking with separation/alignment/cohesion", "_start_boids"),
            ("Biology", "Forest Fire (F)", "Stochastic forest fire cellular automaton", "_start_forestfire"),
            ("Biology", "Epidemic SIR (H)", "Disease spread with susceptible/infected/recovered agents", "_start_sir"),
            # --- Procedural ---
            ("Procedural", "Wave Function Collapse (T)", "Constraint-based procedural terrain generation", "_start_wfc"),
            ("Procedural", "Turmites (U)", "2D Turing machines on a grid", "_start_turmite"),
            # --- Algorithms ---
            ("Algorithms", "Maze Solver (M)", "Procedural maze generation with A* pathfinding", "_start_maze"),
            # --- Mathematics ---
            ("Mathematics", "Fractal Explorer (Z)", "Interactive Mandelbrot & Julia set explorer with zoom/pan", "_start_fractal"),
            ("Mathematics", "Strange Attractors (A)", "Lorenz, Rössler & Hénon chaotic attractor visualization", "_start_attractor"),
        ]
        # Precompute category boundaries for menu rendering
        self._menu_categories: list[str] = []
        self._menu_cat_indices: list[int] = []  # flat index where each category starts
        seen: set[str] = set()
        for i, (cat, _, _, _) in enumerate(self.MENU_MODES):
            if cat not in seen:
                seen.add(cat)
                self._menu_categories.append(cat)
                self._menu_cat_indices.append(i)

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
            # Demo tour: auto-advance to next mode when timer expires
            if self.demo_tour_mode and not self.demo_tour_paused:
                elapsed = time.monotonic() - self.demo_tour_start_time
                if elapsed >= self.demo_tour_duration:
                    self._demo_tour_next()
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
            elif self.boids_mode:
                if self.running:
                    self._boids_tick()
            elif self.nca_mode:
                if self.running:
                    self._nca_tick()
            elif self.wfc_mode:
                if self.running:
                    self._wfc_tick()
            elif self.turmite_mode:
                if self.running:
                    self._turmite_tick()
            elif self.erosion_mode:
                if self.running:
                    self._erosion_tick()
            elif self.magfield_mode:
                if self.running:
                    self._magfield_tick()
            elif self.nbody_mode:
                if self.running:
                    self._nbody_tick()
            elif self.sandpile_mode:
                if self.running:
                    self._sandpile_tick()
            elif self.forestfire_mode:
                if self.running:
                    self._forestfire_tick()
            elif self.dla_mode:
                if self.running:
                    self._dla_tick()
            elif self.sir_mode:
                if self.running:
                    self._sir_tick()
            elif self.maze_mode:
                if self.running:
                    self._maze_tick()
            elif self.fractal_mode:
                self._fractal_tick()
            elif self.attractor_mode:
                self._attractor_tick()
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
            # Boids flocking colors (direction-based)
            curses.init_pair(61, curses.COLOR_CYAN, -1)    # Boids: default
            curses.init_pair(62, curses.COLOR_GREEN, -1)   # Boids: heading right
            curses.init_pair(63, curses.COLOR_YELLOW, -1)  # Boids: heading up
            curses.init_pair(64, curses.COLOR_RED, -1)     # Boids: heading left
            curses.init_pair(65, curses.COLOR_MAGENTA, -1) # Boids: heading down
            # NCA channel-based colors
            curses.init_pair(70, curses.COLOR_GREEN, -1)   # NCA: low alpha
            curses.init_pair(71, curses.COLOR_CYAN, -1)    # NCA: medium alpha
            curses.init_pair(72, curses.COLOR_YELLOW, -1)  # NCA: high alpha
            curses.init_pair(73, curses.COLOR_WHITE, -1)   # NCA: full alpha
            curses.init_pair(74, curses.COLOR_MAGENTA, -1) # NCA: channel highlight
            curses.init_pair(75, curses.COLOR_RED, -1)     # NCA: cursor
            # WFC terrain tile colors
            curses.init_pair(80, curses.COLOR_BLUE, -1)    # WFC: water
            curses.init_pair(81, curses.COLOR_YELLOW, -1)  # WFC: sand
            curses.init_pair(82, curses.COLOR_GREEN, -1)   # WFC: grass
            curses.init_pair(83, curses.COLOR_GREEN, -1)   # WFC: forest (bold)
            curses.init_pair(84, curses.COLOR_RED, -1)     # WFC: mountain
            curses.init_pair(85, curses.COLOR_WHITE, -1)   # WFC: snow
            curses.init_pair(86, curses.COLOR_CYAN, -1)    # WFC: uncollapsed
            # Turmite colors
            curses.init_pair(90, curses.COLOR_WHITE, -1)   # Turmite: color 1
            curses.init_pair(91, curses.COLOR_CYAN, -1)    # Turmite: color 2
            curses.init_pair(92, curses.COLOR_BLUE, -1)    # Turmite: color 3
            curses.init_pair(93, curses.COLOR_RED, -1)     # Turmite: head
            curses.init_pair(94, curses.COLOR_YELLOW, -1)  # Turmite: head alt
            curses.init_pair(95, curses.COLOR_GREEN, -1)   # Turmite: trail highlight
            # Hydraulic Erosion colors
            curses.init_pair(100, curses.COLOR_BLUE, -1)    # Erosion: deep water
            curses.init_pair(101, curses.COLOR_CYAN, -1)    # Erosion: shallow water
            curses.init_pair(102, curses.COLOR_GREEN, -1)   # Erosion: low terrain
            curses.init_pair(103, curses.COLOR_YELLOW, -1)  # Erosion: mid terrain
            curses.init_pair(104, curses.COLOR_RED, -1)     # Erosion: high terrain
            curses.init_pair(105, curses.COLOR_WHITE, -1)   # Erosion: peak/snow
            curses.init_pair(106, curses.COLOR_MAGENTA, -1) # Erosion: sediment
            # Magnetic Field mode color pairs
            curses.init_pair(110, curses.COLOR_RED, -1)      # MagField: positive trail
            curses.init_pair(111, curses.COLOR_BLUE, -1)     # MagField: negative trail
            curses.init_pair(112, curses.COLOR_RED, -1)      # MagField: fast positive
            curses.init_pair(113, curses.COLOR_YELLOW, -1)   # MagField: slow positive
            curses.init_pair(114, curses.COLOR_CYAN, -1)     # MagField: fast negative
            curses.init_pair(115, curses.COLOR_BLUE, -1)     # MagField: slow negative
            # N-Body gravity mode color pairs
            curses.init_pair(120, curses.COLOR_YELLOW, -1)   # NBody: star
            curses.init_pair(121, curses.COLOR_CYAN, -1)     # NBody: planet
            curses.init_pair(122, curses.COLOR_WHITE, -1)    # NBody: asteroid
            curses.init_pair(123, curses.COLOR_RED, -1)      # NBody: star trail
            curses.init_pair(124, curses.COLOR_BLUE, -1)     # NBody: planet trail
            curses.init_pair(125, curses.COLOR_GREEN, -1)    # NBody: asteroid trail
            curses.init_pair(126, curses.COLOR_MAGENTA, -1)  # NBody: large star
            # Abelian Sandpile mode color pairs
            curses.init_pair(130, curses.COLOR_BLACK, -1)    # Sandpile: 0 grains
            curses.init_pair(131, curses.COLOR_GREEN, -1)    # Sandpile: 1 grain
            curses.init_pair(132, curses.COLOR_CYAN, -1)     # Sandpile: 2 grains
            curses.init_pair(133, curses.COLOR_YELLOW, -1)   # Sandpile: 3 grains
            curses.init_pair(134, curses.COLOR_RED, -1)      # Sandpile: toppling (>=threshold)
            curses.init_pair(135, curses.COLOR_MAGENTA, -1)  # Sandpile: high pile
            curses.init_pair(136, curses.COLOR_WHITE, -1)    # Sandpile: very high
            # Forest Fire mode color pairs
            curses.init_pair(140, curses.COLOR_GREEN, -1)    # ForestFire: tree
            curses.init_pair(141, curses.COLOR_RED, -1)      # ForestFire: burning
            curses.init_pair(142, curses.COLOR_YELLOW, -1)   # ForestFire: burning bright
            curses.init_pair(143, curses.COLOR_WHITE, -1)    # ForestFire: charred (hot)
            curses.init_pair(144, curses.COLOR_BLACK, -1)    # ForestFire: charred (cool)
            curses.init_pair(145, curses.COLOR_GREEN, curses.COLOR_GREEN)  # ForestFire: dense tree
            # DLA mode color pairs
            curses.init_pair(150, curses.COLOR_WHITE, -1)    # DLA: crystal core
            curses.init_pair(151, curses.COLOR_CYAN, -1)     # DLA: crystal young
            curses.init_pair(152, curses.COLOR_BLUE, -1)     # DLA: crystal mid
            curses.init_pair(153, curses.COLOR_MAGENTA, -1)  # DLA: crystal old
            curses.init_pair(154, curses.COLOR_YELLOW, -1)   # DLA: walker
            curses.init_pair(155, curses.COLOR_GREEN, -1)    # DLA: crystal tip
            # SIR epidemic mode color pairs
            curses.init_pair(160, curses.COLOR_GREEN, -1)    # SIR: susceptible
            curses.init_pair(161, curses.COLOR_RED, -1)      # SIR: infected (early)
            curses.init_pair(162, curses.COLOR_YELLOW, -1)   # SIR: infected (mid)
            curses.init_pair(163, curses.COLOR_BLUE, -1)     # SIR: recovered
            curses.init_pair(164, curses.COLOR_WHITE, -1)    # SIR: dead
            curses.init_pair(165, curses.COLOR_MAGENTA, -1)  # SIR: infected (late)

            curses.init_pair(170, curses.COLOR_WHITE, -1)    # Maze: wall
            curses.init_pair(171, curses.COLOR_WHITE, -1)    # Maze: path
            curses.init_pair(172, curses.COLOR_GREEN, -1)     # Maze: start
            curses.init_pair(173, curses.COLOR_RED, -1)       # Maze: end
            curses.init_pair(174, curses.COLOR_BLUE, -1)      # Maze: visited
            curses.init_pair(175, curses.COLOR_YELLOW, -1)    # Maze: solution
            curses.init_pair(176, curses.COLOR_CYAN, -1)      # Maze: frontier
            curses.init_pair(177, curses.COLOR_MAGENTA, -1)   # Maze: carving
            # Fractal Explorer colors
            curses.init_pair(180, curses.COLOR_BLUE, -1)       # Fractal: classic blue
            curses.init_pair(181, curses.COLOR_CYAN, -1)       # Fractal: classic cyan
            curses.init_pair(182, curses.COLOR_GREEN, -1)      # Fractal: classic green
            curses.init_pair(183, curses.COLOR_YELLOW, -1)     # Fractal: classic yellow
            curses.init_pair(184, curses.COLOR_RED, -1)        # Fractal: classic red
            curses.init_pair(185, curses.COLOR_MAGENTA, -1)    # Fractal: classic magenta
            curses.init_pair(186, curses.COLOR_WHITE, -1)      # Fractal: classic white
            curses.init_pair(187, curses.COLOR_RED, -1)        # Fractal: fire red
            curses.init_pair(188, curses.COLOR_YELLOW, -1)     # Fractal: fire yellow
            curses.init_pair(189, curses.COLOR_WHITE, -1)      # Fractal: fire white
            curses.init_pair(190, curses.COLOR_BLUE, -1)       # Fractal: ocean deep
            curses.init_pair(191, curses.COLOR_MAGENTA, -1)    # Fractal: neon magenta
            curses.init_pair(192, curses.COLOR_CYAN, -1)       # Fractal: neon cyan
            curses.init_pair(193, curses.COLOR_GREEN, -1)      # Fractal: neon green
            curses.init_pair(194, curses.COLOR_WHITE, -1)      # Fractal: grayscale light
            curses.init_pair(195, curses.COLOR_WHITE, -1)      # Fractal: grayscale dim

            # Attractor color pairs (200-209)
            curses.init_pair(200, curses.COLOR_RED, -1)        # Attractor: heat cool
            curses.init_pair(201, curses.COLOR_YELLOW, -1)     # Attractor: heat warm
            curses.init_pair(202, curses.COLOR_WHITE, -1)      # Attractor: heat hot
            curses.init_pair(203, curses.COLOR_RED, -1)        # Attractor: heat bright
            curses.init_pair(204, curses.COLOR_MAGENTA, -1)    # Attractor: heat peak
            curses.init_pair(205, curses.COLOR_BLUE, -1)       # Attractor: electric blue
            curses.init_pair(206, curses.COLOR_CYAN, -1)       # Attractor: electric cyan
            curses.init_pair(207, curses.COLOR_WHITE, -1)      # Attractor: electric white
            curses.init_pair(208, curses.COLOR_CYAN, -1)       # Attractor: ice cyan
            curses.init_pair(209, curses.COLOR_BLUE, -1)       # Attractor: ice blue

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

        # Demo tour mode: most keys exit, a few control playback
        if self.demo_tour_mode:
            return self._handle_demo_tour_input(key)

        # Mode picker menu has its own input handler
        if self.menu_mode:
            return self._handle_menu_input(key)

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

        # Boids flocking mode has its own input handler
        if self.boids_mode:
            return self._handle_boids_input(key)

        # Neural Cellular Automata mode has its own input handler
        if self.nca_mode:
            return self._handle_nca_input(key)

        # Wave Function Collapse mode has its own input handler
        if self.wfc_mode:
            return self._handle_wfc_input(key)

        # Turmite mode has its own input handler
        if self.turmite_mode:
            return self._handle_turmite_input(key)

        # Erosion mode has its own input handler
        if self.erosion_mode:
            return self._handle_erosion_input(key)

        # Magnetic Field mode has its own input handler
        if self.magfield_mode:
            return self._handle_magfield_input(key)

        # N-Body gravity mode has its own input handler
        if self.nbody_mode:
            return self._handle_nbody_input(key)

        # Abelian Sandpile mode has its own input handler
        if self.sandpile_mode:
            return self._handle_sandpile_input(key)

        # Forest Fire mode has its own input handler
        if self.forestfire_mode:
            return self._handle_forestfire_input(key)

        # DLA mode has its own input handler
        if self.dla_mode:
            return self._handle_dla_input(key)

        # Epidemic SIR mode has its own input handler
        if self.sir_mode:
            return self._handle_sir_input(key)

        # Fractal Explorer mode has its own input handler
        if self.fractal_mode:
            return self._handle_fractal_input(key)

        # Strange Attractor mode has its own input handler
        if self.attractor_mode:
            return self._handle_attractor_input(key)

        # Maze mode has its own input handler
        if self.maze_mode:
            return self._handle_maze_input(key)

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

        # Boids flocking simulation mode
        elif key == ord("B"):
            self._start_boids()

        # Neural Cellular Automata mode
        elif key == ord("N"):
            self._start_nca()

        # Wave Function Collapse terrain generation mode
        elif key == ord("T"):
            self._start_wfc()

        # Langton's Turmites mode
        elif key == ord("U"):
            self._start_turmite()

        # Hydraulic Erosion mode
        elif key == ord("Y"):
            self._start_erosion()

        # Magnetic Field simulation mode
        elif key == ord("G"):
            self._start_magfield()

        # Gravity N-Body simulation mode
        elif key == ord("K"):
            self._start_nbody()

        # Abelian Sandpile simulation mode
        elif key == ord("J"):
            self._start_sandpile()

        # Forest Fire simulation mode
        elif key == ord("F"):
            self._start_forestfire()

        # DLA (Diffusion-Limited Aggregation) simulation mode
        elif key == ord("L"):
            self._start_dla()

        # Epidemic SIR simulation mode
        elif key == ord("H"):
            self._start_sir()

        # Maze Generator & Solver mode
        elif key == ord("M"):
            self._start_maze()

        # Fractal Explorer mode
        elif key == ord("Z"):
            self._start_fractal()

        # Strange Attractor mode
        elif key == ord("A"):
            self._start_attractor()

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

        # Demo Tour (screensaver) mode
        elif key == ord("!"):
            self._start_demo_tour()

        # Mode picker menu
        elif key in (ord("?"), ord("/")):
            self._open_menu()

        # Brush size with [z] key: z shrink
        elif key == ord("z"):
            self.brush_size = max(1, self.brush_size - 1)
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

    # --- Boids flocking simulation ---

    def _handle_boids_input(self, key: int) -> bool:
        """Handle input while in Boids flocking mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._boids_tick()
        elif key == ord("r"):
            if self.boids_world:
                self.boids_world.seed()
                self.boids_gen = 0
                self._set_message("Reset boids")
        # Cycle presets
        elif key == ord("p") or key == ord("n"):
            if self.boids_world:
                direction = 1 if key == ord("n") else -1
                name = self.boids_world.cycle_preset(direction)
                self.boids_preset_idx = self.boids_world.preset_idx
                self._set_message(f"Preset: {name}")
        # Adjust boid count
        elif key == ord("]"):
            if self.boids_world:
                self.boids_world.set_num_boids(self.boids_world.num_boids + 25)
                self._set_message(f"Boids: {self.boids_world.num_boids}")
        elif key == ord("["):
            if self.boids_world:
                self.boids_world.set_num_boids(self.boids_world.num_boids - 25)
                self._set_message(f"Boids: {self.boids_world.num_boids}")
        # Adjust separation weight
        elif key == ord("1"):
            if self.boids_world:
                self.boids_world.sep_weight = max(0.0, self.boids_world.sep_weight - 0.005)
                self._set_message(f"Separation: {self.boids_world.sep_weight:.3f}")
        elif key == ord("!"):
            if self.boids_world:
                self.boids_world.sep_weight = min(0.2, self.boids_world.sep_weight + 0.005)
                self._set_message(f"Separation: {self.boids_world.sep_weight:.3f}")
        # Adjust alignment weight
        elif key == ord("2"):
            if self.boids_world:
                self.boids_world.ali_weight = max(0.0, self.boids_world.ali_weight - 0.005)
                self._set_message(f"Alignment: {self.boids_world.ali_weight:.3f}")
        elif key == ord("@"):
            if self.boids_world:
                self.boids_world.ali_weight = min(0.3, self.boids_world.ali_weight + 0.005)
                self._set_message(f"Alignment: {self.boids_world.ali_weight:.3f}")
        # Adjust cohesion weight
        elif key == ord("3"):
            if self.boids_world:
                self.boids_world.coh_weight = max(0.0, self.boids_world.coh_weight - 0.002)
                self._set_message(f"Cohesion: {self.boids_world.coh_weight:.3f}")
        elif key == ord("#"):
            if self.boids_world:
                self.boids_world.coh_weight = min(0.1, self.boids_world.coh_weight + 0.002)
                self._set_message(f"Cohesion: {self.boids_world.coh_weight:.3f}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Boids mode
        elif key == ord("B") or key == 27:
            self._stop_boids()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_boids(self) -> None:
        """Enter Boids flocking mode."""
        self.running = False
        self.boids_mode = True
        self.boids_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(10, max_w)
        h = max(10, max_h - 3)
        preset = BOIDS_PRESET_NAMES[self.boids_preset_idx]
        self.boids_world = BoidsWorld(w, h, preset=preset)
        self._set_message(
            "Boids Flocking — [Space]Run [P/N]Preset [Shift+B]Exit"
        )

    def _stop_boids(self) -> None:
        """Exit Boids flocking mode."""
        self.boids_mode = False
        self.running = False
        self.boids_world = None
        self.boids_gen = 0
        self._set_message("Boids mode ended")

    def _boids_tick(self) -> None:
        """Advance one Boids generation."""
        if self.boids_world:
            self.boids_world.tick()
            self.boids_gen += 1

    def _draw_boids(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Boids flocking simulation."""
        if not self.boids_world:
            return
        bw = self.boids_world

        # Clear the grid area (boids are sparse)
        # Render each boid as a directional arrow
        for i in range(bw.num_boids):
            # Map continuous position to screen coordinates
            sc = int(bw.x[i]) % max_w
            sr = int(bw.y[i]) % grid_rows

            if sr < 0 or sr >= grid_rows or sc < 0 or sc >= max_w - 1:
                continue

            # Determine heading direction (8 directions)
            angle = math.atan2(-bw.vy[i], bw.vx[i])  # negative vy because screen y is inverted
            # Map angle to 0-7 index (0=right, going counterclockwise)
            idx = int((angle + math.pi) / (2 * math.pi) * 8 + 0.5) % 8
            ch = BOIDS_ARROWS[idx]

            # Color based on heading quadrant
            if self.use_color:
                if idx in (0, 1, 7):      # rightward
                    attr = curses.color_pair(62) | curses.A_BOLD
                elif idx in (2, 3):        # upward
                    attr = curses.color_pair(63) | curses.A_BOLD
                elif idx in (4, 5):        # leftward
                    attr = curses.color_pair(64) | curses.A_BOLD
                else:                      # downward
                    attr = curses.color_pair(65) | curses.A_BOLD
            else:
                attr = curses.A_BOLD

            try:
                self.stdscr.addstr(sr, sc, ch, attr)
            except curses.error:
                pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = BOIDS_PRESET_NAMES[bw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            status = (
                f" Boids | Gen: {self.boids_gen} | "
                f"N={bw.num_boids} | "
                f"Sep={bw.sep_weight:.3f} Ali={bw.ali_weight:.3f} Coh={bw.coh_weight:.3f} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str} "
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
                "[1/!]Sep [2/@]Ali [3/#]Coh [[]Boids | "
                "[P/N]Preset [F]aster [D]slower | [Shift+B]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- NCA (Neural Cellular Automata) mode ---

    def _handle_nca_input(self, key: int) -> bool:
        """Handle input while in NCA mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._nca_tick()
        elif key == ord("r"):
            if self.nca_world:
                self.nca_world.reset()
                self.nca_gen = 0
                self._set_message("Reset NCA")
        # Cycle presets
        elif key == ord("p") or key == ord("n"):
            if self.nca_world:
                direction = 1 if key == ord("n") else -1
                name = self.nca_world.cycle_preset(direction)
                self.nca_preset_idx = self.nca_world.preset_idx
                self.nca_gen = 0
                self._set_message(f"Preset: {name}")
        # Cursor movement for painting/erasing
        elif key in (curses.KEY_UP, ord("k")):
            self.nca_cursor_y = max(0, self.nca_cursor_y - 1)
            if self.nca_painting and self.nca_world:
                self.nca_world.paint_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
            elif self.nca_erasing and self.nca_world:
                self.nca_world.erase_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
        elif key in (curses.KEY_DOWN, ord("j")):
            max_h, _ = self.stdscr.getmaxyx()
            self.nca_cursor_y = min(max_h - 4, self.nca_cursor_y + 1)
            if self.nca_painting and self.nca_world:
                self.nca_world.paint_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
            elif self.nca_erasing and self.nca_world:
                self.nca_world.erase_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
        elif key in (curses.KEY_LEFT, ord("h")):
            self.nca_cursor_x = max(0, self.nca_cursor_x - 1)
            if self.nca_painting and self.nca_world:
                self.nca_world.paint_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
            elif self.nca_erasing and self.nca_world:
                self.nca_world.erase_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
        elif key in (curses.KEY_RIGHT, ord("l")):
            _, max_w = self.stdscr.getmaxyx()
            self.nca_cursor_x = min(max_w // 2 - 1, self.nca_cursor_x + 1)
            if self.nca_painting and self.nca_world:
                self.nca_world.paint_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
            elif self.nca_erasing and self.nca_world:
                self.nca_world.erase_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
        # Paint mode toggle
        elif key == ord("x"):
            self.nca_painting = not self.nca_painting
            self.nca_erasing = False
            if self.nca_painting and self.nca_world:
                self.nca_world.paint_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
            self._set_message("Paint ON" if self.nca_painting else "Paint OFF")
        # Erase mode toggle
        elif key == ord("e"):
            self.nca_erasing = not self.nca_erasing
            self.nca_painting = False
            if self.nca_erasing and self.nca_world:
                self.nca_world.erase_circle(self.nca_cursor_y, self.nca_cursor_x, self.nca_brush_size)
            self._set_message("Erase ON" if self.nca_erasing else "Erase OFF")
        # Brush size
        elif key == ord("]"):
            self.nca_brush_size = min(8, self.nca_brush_size + 1)
            self._set_message(f"Brush: {self.nca_brush_size}")
        elif key == ord("["):
            self.nca_brush_size = max(1, self.nca_brush_size - 1)
            self._set_message(f"Brush: {self.nca_brush_size}")
        # Adjust update rate
        elif key == ord(","):
            if self.nca_world:
                self.nca_world.update_rate = max(0.02, self.nca_world.update_rate - 0.02)
                self._set_message(f"Update rate: {self.nca_world.update_rate:.2f}")
        elif key == ord("."):
            if self.nca_world:
                self.nca_world.update_rate = min(1.0, self.nca_world.update_rate + 0.02)
                self._set_message(f"Update rate: {self.nca_world.update_rate:.2f}")
        # Adjust noise
        elif key == ord("-"):
            if self.nca_world:
                self.nca_world.noise_amp = max(0.0, self.nca_world.noise_amp - 0.01)
                self._set_message(f"Noise: {self.nca_world.noise_amp:.2f}")
        elif key == ord("="):
            if self.nca_world:
                self.nca_world.noise_amp = min(0.5, self.nca_world.noise_amp + 0.01)
                self._set_message(f"Noise: {self.nca_world.noise_amp:.2f}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit NCA mode
        elif key == ord("N") or key == 27:
            self._stop_nca()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_nca(self) -> None:
        """Enter Neural Cellular Automata mode."""
        self.running = False
        self.nca_mode = True
        self.nca_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(10, max_w // 2)
        h = max(10, max_h - 3)
        self.nca_cursor_x = w // 2
        self.nca_cursor_y = h // 2
        preset = NCA_PRESET_NAMES[self.nca_preset_idx]
        self.nca_world = NCAWorld(w, h, preset=preset)
        self._set_message(
            "Neural CA — [Space]Run [X]Paint [E]rase [P/N]Preset [Shift+N]Exit"
        )

    def _stop_nca(self) -> None:
        """Exit Neural Cellular Automata mode."""
        self.nca_mode = False
        self.running = False
        self.nca_world = None
        self.nca_gen = 0
        self.nca_painting = False
        self.nca_erasing = False
        self._set_message("NCA mode ended")

    def _nca_tick(self) -> None:
        """Advance one NCA generation."""
        if self.nca_world:
            self.nca_world.tick()
            self.nca_gen += 1

    def _draw_nca(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Neural Cellular Automata simulation."""
        if not self.nca_world:
            return
        nw = self.nca_world

        # Density characters from sparse to dense
        density_chars = " ·░▒▓█"

        for y in range(min(grid_rows, nw.height)):
            for x in range(min(grid_cols, nw.width)):
                alpha = nw.state[y][x][0]
                if alpha < 0.02:
                    continue

                # Map alpha to density character
                idx = int(max(0.0, min(1.0, alpha)) * (len(density_chars) - 1))
                ch = density_chars[idx]

                # Color based on channel values
                if self.use_color:
                    if alpha >= 0.8:
                        attr = curses.color_pair(73) | curses.A_BOLD
                    elif alpha >= 0.5:
                        attr = curses.color_pair(72)
                    elif alpha >= 0.25:
                        attr = curses.color_pair(71)
                    else:
                        attr = curses.color_pair(70)
                    # Use channel 1 for color variation
                    if nw.n_channels > 1 and abs(nw.state[y][x][1]) > 0.3:
                        attr = curses.color_pair(74)
                else:
                    attr = curses.A_BOLD if alpha > 0.5 else 0

                sc = x * 2  # each cell is 2 chars wide
                if sc + 1 < max_w and y < grid_rows:
                    try:
                        self.stdscr.addstr(y, sc, ch + ch, attr)
                    except curses.error:
                        pass

        # Draw cursor
        cx_screen = self.nca_cursor_x * 2
        cy_screen = self.nca_cursor_y
        if cy_screen < grid_rows and cx_screen + 1 < max_w:
            cursor_ch = "██" if self.nca_painting else ("░░" if self.nca_erasing else "[]")
            attr = curses.color_pair(75) | curses.A_BOLD if self.use_color else curses.A_REVERSE
            try:
                self.stdscr.addstr(cy_screen, cx_screen, cursor_ch, attr)
            except curses.error:
                pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = NCA_PRESET_NAMES[nw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            mode_str = ""
            if self.nca_painting:
                mode_str = " [PAINT]"
            elif self.nca_erasing:
                mode_str = " [ERASE]"
            status = (
                f" NCA | Gen: {self.nca_gen} | "
                f"Alive: {nw.alive_count} | "
                f"Rate={nw.update_rate:.2f} Noise={nw.noise_amp:.2f} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str}{mode_str} "
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
                "[X]Paint [E]rase [Arrows]Move [\\[/\\]]Brush | "
                "[,/.]Rate [-/=]Noise [P/N]Preset | [Shift+N]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Wave Function Collapse (WFC) terrain generation ---

    def _handle_wfc_input(self, key: int) -> bool:
        """Handle input while in WFC mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._wfc_tick()
        elif key == ord("r"):
            if self.wfc_world:
                self.wfc_world.reset()
                self.wfc_gen = 0
                self._set_message("Reset WFC grid")
        # Cycle presets
        elif key == ord("p") or key == ord("n"):
            if self.wfc_world:
                direction = 1 if key == ord("n") else -1
                name = self.wfc_world.cycle_preset(direction)
                self.wfc_preset_idx = self.wfc_world.preset_idx
                self.wfc_gen = 0
                self._set_message(f"Preset: {name}")
        # Adjust collapse speed
        elif key == ord("]"):
            if self.wfc_world:
                self.wfc_world.steps_per_tick = min(50, self.wfc_world.steps_per_tick + 1)
                self._set_message(f"Steps/tick: {self.wfc_world.steps_per_tick}")
        elif key == ord("["):
            if self.wfc_world:
                self.wfc_world.steps_per_tick = max(1, self.wfc_world.steps_per_tick - 1)
                self._set_message(f"Steps/tick: {self.wfc_world.steps_per_tick}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit WFC mode
        elif key == ord("T") or key == 27:
            self._stop_wfc()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_wfc(self) -> None:
        """Enter Wave Function Collapse terrain generation mode."""
        self.running = False
        self.wfc_mode = True
        self.wfc_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(10, max_w // 2)
        h = max(10, max_h - 3)
        preset = WFC_PRESET_NAMES[self.wfc_preset_idx]
        self.wfc_world = WFCWorld(w, h, preset=preset)
        self._set_message(
            "WFC Terrain — [Space]Run [S]tep [R]eset [P/N]Preset [Shift+T]Exit"
        )

    def _stop_wfc(self) -> None:
        """Exit Wave Function Collapse mode."""
        self.wfc_mode = False
        self.running = False
        self.wfc_world = None
        self.wfc_gen = 0
        self._set_message("WFC mode ended")

    def _wfc_tick(self) -> None:
        """Advance one WFC generation."""
        if self.wfc_world:
            self.wfc_world.tick()
            self.wfc_gen += 1

    def _draw_wfc(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Wave Function Collapse terrain."""
        if not self.wfc_world:
            return
        ww = self.wfc_world

        # Superposition display characters by count
        # More options = more uncertain visual
        sup_chars = "█▓▒░·"

        for y in range(min(grid_rows, ww.height)):
            for x in range(min(grid_cols, ww.width)):
                cell = ww.grid[y][x]
                sc = x * 2
                if sc + 1 >= max_w or y >= grid_rows:
                    continue

                if isinstance(cell, int):
                    # Collapsed — show the tile
                    tile = WFC_TILES[cell]
                    ch = tile["char"]
                    if self.use_color:
                        cid = tile["color_id"]
                        attr = curses.color_pair(cid)
                        # Bold for forest and snow
                        if cell in (3, 5):
                            attr |= curses.A_BOLD
                    else:
                        attr = curses.A_BOLD if cell >= 3 else 0
                else:
                    # Uncollapsed — show superposition
                    n = len(cell)
                    if n == 0:
                        # Contradiction
                        ch = "XX"
                        attr = curses.color_pair(84) | curses.A_BOLD if self.use_color else curses.A_REVERSE
                    else:
                        # Map possibility count to uncertainty visual
                        idx = min(len(sup_chars) - 1, (n - 1) * len(sup_chars) // NUM_WFC_TILES)
                        ch = sup_chars[idx] * 2
                        if self.use_color:
                            attr = curses.color_pair(86) | curses.A_DIM
                        else:
                            attr = curses.A_DIM

                try:
                    self.stdscr.addstr(y, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = WFC_PRESET_NAMES[ww.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            if ww.complete:
                state_str = "COMPLETE"
            elif ww.contradiction:
                state_str = "CONTRADICTION"
            progress_pct = ww.progress * 100
            status = (
                f" WFC Terrain | Gen: {self.wfc_gen} | "
                f"Progress: {progress_pct:.1f}% ({ww.collapsed}/{ww.total_cells}) | "
                f"Steps/tick: {ww.steps_per_tick} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str} "
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
                "[P/N]Preset [\\[/\\]]Steps/tick [F/D]Speed | [Shift+T]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Langton's Turmites simulation ---

    def _handle_turmite_input(self, key: int) -> bool:
        """Handle input while in Turmite mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._turmite_tick()
        elif key == ord("r"):
            if self.turmite_world:
                self.turmite_world.reset()
                self.turmite_gen = 0
                self._set_message("Reset")
        # Cycle preset forward/back
        elif key == ord("p") or key == ord("n"):
            if self.turmite_world:
                direction = 1 if key == ord("n") else -1
                name = self.turmite_world.cycle_preset(direction)
                self.turmite_preset_idx = self.turmite_world.preset_idx
                self.turmite_gen = 0
                self._set_message(f"Preset: {name}")
        # Steps per tick
        elif key == ord("]"):
            if self.turmite_world:
                self.turmite_world.steps_per_tick = min(500, self.turmite_world.steps_per_tick * 2)
                self._set_message(f"Steps/tick: {self.turmite_world.steps_per_tick}")
        elif key == ord("["):
            if self.turmite_world:
                self.turmite_world.steps_per_tick = max(1, self.turmite_world.steps_per_tick // 2)
                self._set_message(f"Steps/tick: {self.turmite_world.steps_per_tick}")
        # Add/remove turmites
        elif key == ord("+") or key == ord("="):
            if self.turmite_world:
                self.turmite_world.add_turmite_center()
                self._set_message(f"Turmites: {len(self.turmite_world.turmites)}")
        elif key == ord("-") or key == ord("_"):
            if self.turmite_world:
                self.turmite_world.remove_turmite()
                self._set_message(f"Turmites: {len(self.turmite_world.turmites)}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Turmite mode
        elif key == ord("U") or key == 27:
            self._stop_turmite()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_turmite(self) -> None:
        """Enter Turmite mode."""
        self.running = False
        self.turmite_mode = True
        self.turmite_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = TURMITE_PRESET_NAMES[self.turmite_preset_idx]
        self.turmite_world = TurmiteWorld(w, h, preset=preset)
        self._set_message(
            "Turmites — [Space]Run [P/N]Preset [+/-]Turmites [Shift+U]Exit"
        )

    def _stop_turmite(self) -> None:
        """Exit Turmite mode."""
        self.turmite_mode = False
        self.running = False
        self.turmite_world = None
        self.turmite_gen = 0
        self._set_message("Turmite mode ended")

    def _turmite_tick(self) -> None:
        """Advance one turmite step."""
        if self.turmite_world:
            self.turmite_world.tick()
            self.turmite_gen += 1

    def _draw_turmite(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the turmite grid with colored cells and turmite heads."""
        if not self.turmite_world:
            return
        tw = self.turmite_world

        # Build set of turmite positions for O(1) lookup
        head_map: dict[tuple[int, int], int] = {}
        for t in tw.turmites:
            head_map[(t[0], t[1])] = t[2]  # direction

        # Color pairs for cell colors
        cell_colors = [0, 90, 91, 92]  # color 0=default, 1-3 use pairs 90-92

        for r in range(min(grid_rows, tw.height)):
            for c in range(min(grid_cols, tw.width)):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                if (r, c) in head_map:
                    # Draw turmite head with direction
                    d = head_map[(r, c)]
                    ch = TURMITE_HEAD_CHARS[d] if d < len(TURMITE_HEAD_CHARS) else "◆◆"
                    attr = curses.color_pair(93) | curses.A_BOLD if self.use_color else curses.A_REVERSE
                else:
                    color = tw.grid[r][c]
                    if color == 0:
                        continue  # skip empty cells for performance
                    ci = min(color, len(TURMITE_CELL_CHARS) - 1)
                    ch = TURMITE_CELL_CHARS[ci]
                    cp = cell_colors[min(color, len(cell_colors) - 1)]
                    attr = curses.color_pair(cp) if self.use_color else curses.A_BOLD

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = TURMITE_PRESET_NAMES[tw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            desc = TURMITE_PRESETS[preset_name][2]
            n_turmites = len(tw.turmites)
            total_steps = self.turmite_gen * tw.steps_per_tick
            status = (
                f" Turmites | Gen: {self.turmite_gen} ({total_steps} steps) | "
                f"Agents: {n_turmites} | States: {tw.num_states} Colors: {tw.num_colors} | "
                f"Steps/tick: {tw.steps_per_tick} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str} "
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
                "[P/N]Preset [+/-]Add/Rm turmite [\\[/\\]]Steps/tick | "
                "[F]aster [D]slower | [Shift+U]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Hydraulic Erosion mode ---

    def _handle_erosion_input(self, key: int) -> bool:
        """Handle input while in Erosion mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._erosion_tick()
        elif key == ord("r"):
            if self.erosion_world:
                self.erosion_world.reset()
                self.erosion_gen = 0
                self._set_message("Reset")
        # Cycle preset forward/back
        elif key == ord("p") or key == ord("n"):
            if self.erosion_world:
                direction = 1 if key == ord("n") else -1
                name = self.erosion_world.cycle_preset(direction)
                self.erosion_preset_idx = self.erosion_world.preset_idx
                self.erosion_gen = 0
                self._set_message(f"Preset: {name}")
        # Steps per tick
        elif key == ord("]"):
            if self.erosion_world:
                self.erosion_world.steps_per_tick = min(50, self.erosion_world.steps_per_tick * 2)
                self._set_message(f"Steps/tick: {self.erosion_world.steps_per_tick}")
        elif key == ord("["):
            if self.erosion_world:
                self.erosion_world.steps_per_tick = max(1, self.erosion_world.steps_per_tick // 2)
                self._set_message(f"Steps/tick: {self.erosion_world.steps_per_tick}")
        # Rain intensity control
        elif key == ord("+") or key == ord("="):
            if self.erosion_world:
                self.erosion_world.rain_rate = min(0.05, self.erosion_world.rain_rate * 1.5)
                self._set_message(f"Rain: {self.erosion_world.rain_rate:.4f}")
        elif key == ord("-") or key == ord("_"):
            if self.erosion_world:
                self.erosion_world.rain_rate = max(0.0005, self.erosion_world.rain_rate / 1.5)
                self._set_message(f"Rain: {self.erosion_world.rain_rate:.4f}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Erosion mode
        elif key == ord("Y") or key == 27:
            self._stop_erosion()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_erosion(self) -> None:
        """Enter Erosion mode."""
        self.running = False
        self.erosion_mode = True
        self.erosion_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = EROSION_PRESET_NAMES[self.erosion_preset_idx]
        self.erosion_world = ErosionWorld(w, h, preset=preset)
        self._set_message(
            "Erosion — [Space]Run [P/N]Preset [+/-]Rain [Shift+Y]Exit"
        )

    def _stop_erosion(self) -> None:
        """Exit Erosion mode."""
        self.erosion_mode = False
        self.running = False
        self.erosion_world = None
        self.erosion_gen = 0
        self._set_message("Erosion mode ended")

    def _erosion_tick(self) -> None:
        """Advance one erosion step."""
        if self.erosion_world:
            self.erosion_world.tick()
            self.erosion_gen += 1

    def _draw_erosion(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the erosion simulation with terrain height and water visualization."""
        if not self.erosion_world:
            return
        ew = self.erosion_world

        # Height characters from low to high
        height_chars = ["  ", "░░", "▒▒", "▓▓", "██"]
        water_chars = ["~~", "≈≈", "██"]

        # Find height range for normalization
        max_terrain = 0.01
        for r in range(ew.height):
            for c in range(ew.width):
                if ew.terrain[r][c] > max_terrain:
                    max_terrain = ew.terrain[r][c]

        for r in range(min(grid_rows, ew.height)):
            for c in range(min(grid_cols, ew.width)):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                water_level = ew.water[r][c]
                terrain_h = ew.terrain[r][c]
                norm_h = terrain_h / max_terrain

                if water_level > 0.01:
                    # Draw water
                    if water_level > 0.05:
                        ch = water_chars[2]
                        cp = 100  # deep water (blue)
                    elif water_level > 0.02:
                        ch = water_chars[1]
                        cp = 100  # blue
                    else:
                        ch = water_chars[0]
                        cp = 101  # shallow (cyan)

                    attr = curses.color_pair(cp) | curses.A_BOLD if self.use_color else curses.A_REVERSE
                else:
                    # Draw terrain based on height
                    # Check erosion intensity
                    erosion_intensity = ew.erosion_map[r][c]

                    if norm_h > 0.85:
                        ch = height_chars[4]
                        cp = 105  # white (peaks)
                    elif norm_h > 0.65:
                        ch = height_chars[3]
                        cp = 104  # red (high)
                    elif norm_h > 0.4:
                        ch = height_chars[2]
                        cp = 103  # yellow (mid)
                    elif norm_h > 0.15:
                        ch = height_chars[1]
                        cp = 102  # green (low)
                    else:
                        continue  # very low terrain — skip

                    # Show sediment deposition areas with magenta tint
                    if erosion_intensity > 0.1:
                        cp = 106  # magenta for heavily eroded

                    attr = curses.color_pair(cp) if self.use_color else curses.A_DIM

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = EROSION_PRESET_NAMES[ew.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = ew.stats
            total_steps = self.erosion_gen * ew.steps_per_tick
            status = (
                f" Erosion | Gen: {self.erosion_gen} ({total_steps} steps) | "
                f"Rain: {ew.rain_rate:.4f} | "
                f"Water: {st['total_water']:.1f} Sed: {st['total_sediment']:.2f} | "
                f"Peak: {st['max_height']:.2f} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str} "
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
                "[P/N]Preset [+/-]Rain intensity [\\[/\\]]Steps/tick | "
                "[F]aster [D]slower | [Shift+Y]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Magnetic Field simulation ---

    def _handle_magfield_input(self, key: int) -> bool:
        """Handle input while in Magnetic Field mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._magfield_tick()
        elif key == ord("r"):
            if self.magfield_world:
                self.magfield_world.reset()
                self.magfield_gen = 0
                self._set_message("Reset")
        # Cycle preset forward/back
        elif key == ord("p") or key == ord("n"):
            if self.magfield_world:
                direction = 1 if key == ord("n") else -1
                name = self.magfield_world.cycle_preset(direction)
                self.magfield_preset_idx = self.magfield_world.preset_idx
                self.magfield_gen = 0
                self._set_message(f"Preset: {name}")
        # Steps per tick
        elif key == ord("]"):
            if self.magfield_world:
                self.magfield_world.steps_per_tick = min(50, self.magfield_world.steps_per_tick * 2)
                self._set_message(f"Steps/tick: {self.magfield_world.steps_per_tick}")
        elif key == ord("["):
            if self.magfield_world:
                self.magfield_world.steps_per_tick = max(1, self.magfield_world.steps_per_tick // 2)
                self._set_message(f"Steps/tick: {self.magfield_world.steps_per_tick}")
        # Adjust B-field strength
        elif key == ord("+") or key == ord("="):
            if self.magfield_world:
                mw = self.magfield_world
                scale = 1.25
                mw.Bx *= scale
                mw.By *= scale
                mw.Bz *= scale
                self._set_message(f"B-field: ({mw.Bx:.2f}, {mw.By:.2f}, {mw.Bz:.2f})")
        elif key == ord("-") or key == ord("_"):
            if self.magfield_world:
                mw = self.magfield_world
                scale = 0.8
                mw.Bx *= scale
                mw.By *= scale
                mw.Bz *= scale
                self._set_message(f"B-field: ({mw.Bx:.2f}, {mw.By:.2f}, {mw.Bz:.2f})")
        # Adjust E-field
        elif key == ord("e"):
            if self.magfield_world:
                mw = self.magfield_world
                # Cycle through E-field directions
                if abs(mw.Ex) > 0.01:
                    mw.Ex = 0.0
                    mw.Ey = abs(mw.Ex) + 0.3 if abs(mw.Ex) < 0.01 else mw.Ex
                    mw.Ey = 0.3
                elif abs(mw.Ey) > 0.01:
                    mw.Ey = 0.0
                else:
                    mw.Ex = 0.3
                self._set_message(f"E-field: ({mw.Ex:.2f}, {mw.Ey:.2f})")
        # Add more particles
        elif key == ord("a"):
            if self.magfield_world:
                mw = self.magfield_world
                preset = MAGFIELD_PRESETS[MAGFIELD_PRESET_NAMES[mw.preset_idx]]
                q = 1.0 if random.random() < 0.5 else -1.0
                speed = random.uniform(*preset["speed_range"])
                angle = random.uniform(0, 2 * math.pi)
                mw.particles.append({
                    "x": mw.width / 2.0 + random.uniform(-3, 3),
                    "y": mw.height / 2.0 + random.uniform(-3, 3),
                    "vx": speed * math.cos(angle),
                    "vy": speed * math.sin(angle),
                    "q": q,
                    "trail": [],
                })
                self._set_message(f"Added particle (n={len(mw.particles)})")
        # Toggle trail length
        elif key == ord("t"):
            if self.magfield_world:
                mw = self.magfield_world
                mw.trail_len = (mw.trail_len + 4) % 24
                if mw.trail_len == 0:
                    mw.trail_len = 4
                self._set_message(f"Trail length: {mw.trail_len}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit Magnetic Field mode
        elif key == ord("G") or key == 27:
            self._stop_magfield()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_magfield(self) -> None:
        """Enter Magnetic Field mode."""
        self.running = False
        self.magfield_mode = True
        self.magfield_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = MAGFIELD_PRESET_NAMES[self.magfield_preset_idx]
        self.magfield_world = MagFieldWorld(w, h, preset=preset)
        self._set_message(
            "MagField — [Space]Run [P/N]Preset [+/-]B-field [Shift+G]Exit"
        )

    def _stop_magfield(self) -> None:
        """Exit Magnetic Field mode."""
        self.magfield_mode = False
        self.running = False
        self.magfield_world = None
        self.magfield_gen = 0
        self._set_message("Magnetic Field mode ended")

    def _magfield_tick(self) -> None:
        """Advance one magnetic field simulation step."""
        if self.magfield_world:
            self.magfield_world.tick()
            self.magfield_gen += 1

    def _draw_magfield(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the magnetic field particle simulation."""
        if not self.magfield_world:
            return
        mw = self.magfield_world

        # Build a grid for rendering: each cell can hold trail or particle info
        # We use 2-char wide cells like other modes
        draw_w = min(grid_cols, mw.width)
        draw_h = min(grid_rows, mw.height)

        # Collect trail positions into a grid for efficient rendering
        trail_grid: dict[tuple[int, int], tuple[float, float]] = {}  # (r,c) -> (charge, age_fraction)
        particle_grid: dict[tuple[int, int], dict] = {}  # (r,c) -> particle

        for p in mw.particles:
            # Draw trail
            trail = p["trail"]
            for ti, (tx, ty) in enumerate(trail):
                tr = int(ty)
                tc = int(tx)
                if 0 <= tr < draw_h and 0 <= tc < draw_w:
                    age = (ti + 1) / max(len(trail), 1)
                    trail_grid[(tr, tc)] = (p["q"], age)

            # Draw particle at current position
            pr = int(p["y"])
            pc = int(p["x"])
            if 0 <= pr < draw_h and 0 <= pc < draw_w:
                particle_grid[(pr, pc)] = p

        # Render trails first, then particles on top
        for (r, c), (charge, age) in trail_grid.items():
            if (r, c) in particle_grid:
                continue  # particle will overwrite
            sc = c * 2
            if sc + 1 >= max_w:
                continue

            # Trail chars: dim dots fading with age
            trail_chars = ["··", "∙∙", "░░", "▒▒"]
            ci = min(int(age * len(trail_chars)), len(trail_chars) - 1)
            ch = trail_chars[ci]

            if self.use_color:
                if charge > 0:
                    cp = curses.color_pair(110)  # red trail for positive
                else:
                    cp = curses.color_pair(111)  # blue trail for negative
                attr = cp | curses.A_DIM
            else:
                attr = curses.A_DIM

            try:
                self.stdscr.addstr(r, sc, ch, attr)
            except curses.error:
                pass

        # Render particles
        for (r, c), p in particle_grid.items():
            sc = c * 2
            if sc + 1 >= max_w:
                continue

            speed = math.sqrt(p["vx"] ** 2 + p["vy"] ** 2)

            # Direction-based character
            if abs(p["vx"]) > abs(p["vy"]):
                ch = "»»" if p["vx"] > 0 else "««"
            else:
                ch = "▼▼" if p["vy"] > 0 else "▲▲"

            if self.use_color:
                # Color by charge and speed
                if p["q"] > 0:
                    if speed > 2.0:
                        cp = curses.color_pair(112)  # bright red (fast positive)
                    else:
                        cp = curses.color_pair(113)  # yellow (slow positive)
                else:
                    if speed > 2.0:
                        cp = curses.color_pair(114)  # bright cyan (fast negative)
                    else:
                        cp = curses.color_pair(115)  # blue (slow negative)
                attr = cp | curses.A_BOLD
            else:
                attr = curses.A_BOLD if p["q"] > 0 else curses.A_NORMAL

            try:
                self.stdscr.addstr(r, sc, ch, attr)
            except curses.error:
                pass

        # Draw field direction indicator in top-right corner
        if draw_h > 2 and max_w > 20:
            field_info = f"B=({mw.Bx:.1f},{mw.By:.1f},{mw.Bz:.1f})"
            if abs(mw.Ex) > 0.01 or abs(mw.Ey) > 0.01:
                field_info += f" E=({mw.Ex:.1f},{mw.Ey:.1f})"
            fi_x = max(0, max_w - len(field_info) - 2)
            attr = curses.color_pair(3) | curses.A_DIM if self.use_color else curses.A_DIM
            try:
                self.stdscr.addstr(0, fi_x, field_info, attr)
            except curses.error:
                pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = MAGFIELD_PRESET_NAMES[mw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = mw.stats
            total_steps = self.magfield_gen * mw.steps_per_tick
            status = (
                f" MagField | Gen: {self.magfield_gen} ({total_steps} steps) | "
                f"Particles: {st['n']} (+{st['pos']}/-{st['neg']}) | "
                f"Avg spd: {st['avg_speed']:.2f} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str} "
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
                "[P/N]Preset [+/-]B-field [E]toggle E | "
                "[A]dd particle [T]rail | "
                "[F]aster [D]slower | [Shift+G]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- N-Body gravity mode ---

    def _handle_nbody_input(self, key: int) -> bool:
        """Handle input while in N-Body gravity mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            if not self.running:
                self._nbody_tick()
        elif key == ord("r"):
            if self.nbody_world:
                self.nbody_world.reset()
                self.nbody_gen = 0
                self._set_message("Reset")
        # Cycle preset forward/back
        elif key == ord("p") or key == ord("n"):
            if self.nbody_world:
                direction = 1 if key == ord("n") else -1
                name = self.nbody_world.cycle_preset(direction)
                self.nbody_preset_idx = self.nbody_world.preset_idx
                self.nbody_gen = 0
                self._set_message(f"Preset: {name}")
        # Adjust G (gravity strength)
        elif key == ord("+") or key == ord("="):
            if self.nbody_world:
                self.nbody_world.G *= 1.25
                self._set_message(f"G = {self.nbody_world.G:.3f}")
        elif key == ord("-") or key == ord("_"):
            if self.nbody_world:
                self.nbody_world.G *= 0.8
                self._set_message(f"G = {self.nbody_world.G:.3f}")
        # Toggle trail length
        elif key == ord("t"):
            if self.nbody_world:
                nw = self.nbody_world
                nw.trail_len = (nw.trail_len + 10) % 60
                if nw.trail_len == 0:
                    nw.trail_len = 10
                self._set_message(f"Trail length: {nw.trail_len}")
        # Add a random body
        elif key == ord("a"):
            if self.nbody_world:
                nw = self.nbody_world
                x = random.uniform(nw.width * 0.1, nw.width * 0.9)
                y = random.uniform(nw.height * 0.1, nw.height * 0.9)
                mass = random.uniform(2.0, 15.0)
                angle = random.uniform(0, 2 * math.pi)
                speed = random.uniform(0.2, 0.8)
                nw.bodies.append({
                    "x": x, "y": y,
                    "vx": speed * math.cos(angle),
                    "vy": speed * math.sin(angle),
                    "mass": mass, "kind": "planet", "trail": [],
                })
                self._set_message(f"Added body (n={len(nw.bodies)})")
        # Add a massive star
        elif key == ord("A"):
            if self.nbody_world:
                nw = self.nbody_world
                nw.bodies.append({
                    "x": nw.width / 2.0 + random.uniform(-5, 5),
                    "y": nw.height / 2.0 + random.uniform(-5, 5),
                    "vx": random.uniform(-0.2, 0.2),
                    "vy": random.uniform(-0.2, 0.2),
                    "mass": random.uniform(50.0, 120.0),
                    "kind": "star", "trail": [],
                })
                self._set_message(f"Added star (n={len(nw.bodies)})")
        # Steps per tick
        elif key == ord("]"):
            if self.nbody_world:
                self.nbody_world.steps_per_tick = min(20, self.nbody_world.steps_per_tick + 1)
                self._set_message(f"Steps/tick: {self.nbody_world.steps_per_tick}")
        elif key == ord("["):
            if self.nbody_world:
                self.nbody_world.steps_per_tick = max(1, self.nbody_world.steps_per_tick - 1)
                self._set_message(f"Steps/tick: {self.nbody_world.steps_per_tick}")
        # Speed control
        elif key == ord("f"):
            self.speed = min(20, self.speed + 1)
            self._update_timeout()
        elif key == ord("d"):
            self.speed = max(1, self.speed - 1)
            self._update_timeout()
        # Exit N-Body mode
        elif key == ord("K") or key == 27:
            self._stop_nbody()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_nbody(self) -> None:
        """Enter N-Body gravity simulation mode."""
        self.running = False
        self.nbody_mode = True
        self.nbody_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = NBODY_PRESET_NAMES[self.nbody_preset_idx]
        self.nbody_world = NBodyWorld(w, h, preset=preset)
        self._set_message(
            "N-Body — [Space]Run [P/N]Preset [+/-]Gravity [Shift+K]Exit"
        )

    def _stop_nbody(self) -> None:
        """Exit N-Body gravity simulation mode."""
        self.nbody_mode = False
        self.running = False
        self.nbody_world = None
        self.nbody_gen = 0
        self._set_message("N-Body mode ended")

    def _nbody_tick(self) -> None:
        """Advance one N-body simulation step."""
        if self.nbody_world:
            self.nbody_world.tick()
            self.nbody_gen += 1

    def _draw_nbody(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the N-body gravitational simulation."""
        if not self.nbody_world:
            return
        nw = self.nbody_world

        draw_w = min(grid_cols, nw.width)
        draw_h = min(grid_rows, nw.height)

        # Collect trail positions
        trail_grid: dict[tuple[int, int], tuple[str, float]] = {}  # (r,c) -> (kind, age_fraction)
        body_grid: dict[tuple[int, int], dict] = {}  # (r,c) -> body

        for b in nw.bodies:
            trail = b["trail"]
            for ti, (tx, ty) in enumerate(trail):
                tr = int(ty)
                tc = int(tx)
                if 0 <= tr < draw_h and 0 <= tc < draw_w:
                    age = (ti + 1) / max(len(trail), 1)
                    trail_grid[(tr, tc)] = (b["kind"], age)

            br = int(b["y"])
            bc = int(b["x"])
            if 0 <= br < draw_h and 0 <= bc < draw_w:
                body_grid[(br, bc)] = b

        # Render trails
        for (r, c), (kind, age) in trail_grid.items():
            if (r, c) in body_grid:
                continue
            sc = c * 2
            if sc + 1 >= max_w:
                continue

            trail_chars = ["··", "∙∙", "░░", "▒▒"]
            ci = min(int(age * len(trail_chars)), len(trail_chars) - 1)
            ch = trail_chars[ci]

            if self.use_color:
                if kind == "star":
                    cp = curses.color_pair(123)
                elif kind == "planet":
                    cp = curses.color_pair(124)
                else:
                    cp = curses.color_pair(125)
                attr = cp | curses.A_DIM
            else:
                attr = curses.A_DIM

            try:
                self.stdscr.addstr(r, sc, ch, attr)
            except curses.error:
                pass

        # Render bodies
        for (r, c), b in body_grid.items():
            sc = c * 2
            if sc + 1 >= max_w:
                continue

            mass = b["mass"]
            kind = b["kind"]

            # Body character based on kind and mass
            if kind == "star":
                if mass >= 100:
                    ch = "★★"
                elif mass >= 40:
                    ch = "✦✦"
                else:
                    ch = "✶✶"
            elif kind == "planet":
                if mass >= 10:
                    ch = "●●"
                else:
                    ch = "○○"
            else:  # asteroid
                ch = "∘∘"

            if self.use_color:
                if kind == "star":
                    if mass >= 80:
                        cp = curses.color_pair(126)  # magenta for massive stars
                    else:
                        cp = curses.color_pair(120)  # yellow for stars
                elif kind == "planet":
                    cp = curses.color_pair(121)  # cyan for planets
                else:
                    cp = curses.color_pair(122)  # white for asteroids
                attr = cp | curses.A_BOLD
            else:
                attr = curses.A_BOLD if kind == "star" else curses.A_NORMAL

            try:
                self.stdscr.addstr(r, sc, ch, attr)
            except curses.error:
                pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = NBODY_PRESET_NAMES[nw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = nw.stats
            total_steps = self.nbody_gen * nw.steps_per_tick
            status = (
                f" N-Body | Gen: {self.nbody_gen} ({total_steps} steps) | "
                f"Bodies: {st['n']} (★{st['stars']} ●{st['planets']} ∘{st['asteroids']}) | "
                f"Mass: {st['total_mass']:.0f} | G: {nw.G:.3f} | "
                f"Preset: {preset_name} | Speed: {self.speed} | {state_str} "
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
                "[P/N]Preset [+/-]Gravity [T]rail | "
                "[A]dd planet [Shift+A]dd star | "
                "[F]aster [D]slower | [Shift+K]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Abelian Sandpile mode ---

    def _handle_sandpile_input(self, key: int) -> bool:
        """Handle input while in Abelian Sandpile mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            # Single step
            self._sandpile_tick()
        elif key == ord("r"):
            if self.sandpile_world:
                self.sandpile_world.reset()
                self.sandpile_gen = 0
                self._set_message("Sandpile reset")
        elif key == ord("p"):
            # Previous preset
            if self.sandpile_world:
                name = self.sandpile_world.cycle_preset(-1)
                self.sandpile_preset_idx = self.sandpile_world.preset_idx
                self.sandpile_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            # Next preset
            if self.sandpile_world:
                name = self.sandpile_world.cycle_preset(1)
                self.sandpile_preset_idx = self.sandpile_world.preset_idx
                self.sandpile_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("f"):
            if self.sandpile_world:
                self.sandpile_world.steps_per_tick = min(
                    100, self.sandpile_world.steps_per_tick + 1
                )
                self._set_message(f"Steps/tick: {self.sandpile_world.steps_per_tick}")
        elif key == ord("d"):
            if self.sandpile_world:
                self.sandpile_world.steps_per_tick = max(
                    1, self.sandpile_world.steps_per_tick - 1
                )
                self._set_message(f"Steps/tick: {self.sandpile_world.steps_per_tick}")
        elif key == ord("+") or key == ord("="):
            # Increase threshold
            if self.sandpile_world:
                self.sandpile_world.threshold += 1
                self._set_message(f"Threshold: {self.sandpile_world.threshold}")
        elif key == ord("-"):
            # Decrease threshold
            if self.sandpile_world:
                self.sandpile_world.threshold = max(2, self.sandpile_world.threshold - 1)
                self._set_message(f"Threshold: {self.sandpile_world.threshold}")
        elif key == ord("1"):
            if self.sandpile_world:
                self.sandpile_world.drop_mode = "center"
                self._set_message("Drop mode: center")
        elif key == ord("2"):
            if self.sandpile_world:
                self.sandpile_world.drop_mode = "random"
                self._set_message("Drop mode: random")
        elif key == ord("3"):
            if self.sandpile_world:
                self.sandpile_world.drop_mode = "multi"
                self._set_message("Drop mode: multi")
        elif key == ord("4"):
            if self.sandpile_world:
                self.sandpile_world.drop_mode = "none"
                self._set_message("Drop mode: none (click to drop)")
        elif key == ord("c"):
            # Drop a big pile at center
            if self.sandpile_world:
                sw = self.sandpile_world
                cr, cc = sw.height // 2, sw.width // 2
                for _ in range(100):
                    sw.drop_at(cr, cc)
                self._set_message("Dropped 100 grains at center")
        elif key == ord("J") or key == 27:  # Shift+J or ESC to exit
            self._stop_sandpile()
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if self.sandpile_world and bstate & curses.BUTTON1_CLICKED:
                    gc = mx // 2
                    gr = my
                    self.sandpile_world.drop_at(gr, gc)
            except curses.error:
                pass
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_sandpile(self) -> None:
        """Enter Abelian Sandpile simulation mode."""
        self.running = False
        self.sandpile_mode = True
        self.sandpile_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = SANDPILE_PRESET_NAMES[self.sandpile_preset_idx]
        self.sandpile_world = SandpileWorld(w, h, preset=preset)
        try:
            curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:
            pass
        self._set_message(
            "Sandpile — [Space]Run [P/N]Preset [1-4]Drop mode [Shift+J]Exit"
        )

    def _stop_sandpile(self) -> None:
        """Exit Abelian Sandpile simulation mode."""
        self.sandpile_mode = False
        self.running = False
        self.sandpile_world = None
        self.sandpile_gen = 0
        self._set_message("Sandpile mode ended")

    def _sandpile_tick(self) -> None:
        """Advance one sandpile simulation step."""
        if self.sandpile_world:
            self.sandpile_world.tick()
            self.sandpile_gen += 1

    def _draw_sandpile(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Abelian Sandpile simulation."""
        if not self.sandpile_world:
            return
        sw = self.sandpile_world
        threshold = sw.threshold

        draw_h = min(grid_rows, sw.height)
        draw_w = min(grid_cols, sw.width)

        # Character and color lookup for grain counts
        grain_chars = ["  ", "░░", "▒▒", "▓▓", "██"]
        # Color pairs: 130=0, 131=1, 132=2, 133=3, 134=toppling, 135=high, 136=very high

        for r in range(draw_h):
            row = sw.grid[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                val = row[c]
                if val == 0:
                    continue  # leave blank

                # Pick character
                if val < threshold:
                    ci = min(val, len(grain_chars) - 1)
                    ch = grain_chars[ci]
                else:
                    ch = "██"

                # Pick color
                if self.use_color:
                    if val == 0:
                        cp = 130
                    elif val == 1:
                        cp = 131
                    elif val == 2:
                        cp = 132
                    elif val == 3:
                        cp = 133
                    elif val >= threshold:
                        if val >= threshold * 2:
                            cp = 136
                        elif val >= threshold + 2:
                            cp = 135
                        else:
                            cp = 134
                    else:
                        # For high thresholds, map values to gradient
                        frac = val / max(threshold - 1, 1)
                        if frac < 0.33:
                            cp = 131
                        elif frac < 0.66:
                            cp = 132
                        else:
                            cp = 133

                    attr = curses.color_pair(cp)
                    if val >= threshold:
                        attr |= curses.A_BOLD
                else:
                    attr = curses.A_NORMAL
                    if val >= threshold:
                        attr = curses.A_BOLD | curses.A_REVERSE

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = SANDPILE_PRESET_NAMES[sw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = sw.stats
            sparkline = sw.sparkline(min(30, max(5, max_w // 6)))
            status = (
                f" Sandpile | Gen: {self.sandpile_gen} | "
                f"Grains: {st['total_grains']} | Max: {st['max_height']} | "
                f"Thresh: {threshold} | "
                f"Aval: {st['current_avalanche']} (avg:{st['avg_avalanche']:.0f} max:{st['max_avalanche']}) | "
                f"Drop: {sw.drop_mode} | "
                f"{sparkline} | "
                f"Preset: {preset_name} | {state_str} "
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
                "[P/N]Preset [1-4]DropMode [C]enter100 | "
                "[+/-]Threshold [F]aster [D]slower | "
                "[Click]Drop | [Shift+J]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Forest Fire mode ---

    def _handle_forestfire_input(self, key: int) -> bool:
        """Handle input while in Forest Fire mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            self._forestfire_tick()
        elif key == ord("r"):
            if self.forestfire_world:
                self.forestfire_world.reset()
                self.forestfire_gen = 0
                self._set_message("Forest fire reset")
        elif key == ord("p"):
            if self.forestfire_world:
                name = self.forestfire_world.cycle_preset(-1)
                self.forestfire_preset_idx = self.forestfire_world.preset_idx
                self.forestfire_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            if self.forestfire_world:
                name = self.forestfire_world.cycle_preset(1)
                self.forestfire_preset_idx = self.forestfire_world.preset_idx
                self.forestfire_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("f"):
            if self.forestfire_world:
                self.forestfire_world.steps_per_tick = min(
                    20, self.forestfire_world.steps_per_tick + 1
                )
                self._set_message(f"Steps/tick: {self.forestfire_world.steps_per_tick}")
        elif key == ord("d"):
            if self.forestfire_world:
                self.forestfire_world.steps_per_tick = max(
                    1, self.forestfire_world.steps_per_tick - 1
                )
                self._set_message(f"Steps/tick: {self.forestfire_world.steps_per_tick}")
        elif key == ord("g"):
            # Increase growth probability
            if self.forestfire_world:
                self.forestfire_world.p_grow = min(1.0, self.forestfire_world.p_grow + 0.01)
                self._set_message(f"Growth: {self.forestfire_world.p_grow:.3f}")
        elif key == ord("l"):
            # Increase lightning probability
            if self.forestfire_world:
                self.forestfire_world.p_lightning = min(
                    0.1, self.forestfire_world.p_lightning * 2 if self.forestfire_world.p_lightning > 0 else 0.00005
                )
                self._set_message(f"Lightning: {self.forestfire_world.p_lightning:.5f}")
        elif key == ord("L"):
            # Decrease lightning probability
            if self.forestfire_world:
                self.forestfire_world.p_lightning = max(0.0, self.forestfire_world.p_lightning / 2)
                self._set_message(f"Lightning: {self.forestfire_world.p_lightning:.5f}")
        elif key == ord("G"):
            # Decrease growth probability
            if self.forestfire_world:
                self.forestfire_world.p_grow = max(0.0, self.forestfire_world.p_grow - 0.01)
                self._set_message(f"Growth: {self.forestfire_world.p_grow:.3f}")
        elif key == ord("F") or key == 27:  # Shift+F or ESC to exit
            self._stop_forestfire()
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if self.forestfire_world and bstate & curses.BUTTON1_CLICKED:
                    gc = mx // 2
                    gr = my
                    self.forestfire_world.strike_at(gr, gc)
            except curses.error:
                pass
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_forestfire(self) -> None:
        """Enter Forest Fire simulation mode."""
        self.running = False
        self.forestfire_mode = True
        self.forestfire_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = FORESTFIRE_PRESET_NAMES[self.forestfire_preset_idx]
        self.forestfire_world = ForestFireWorld(w, h, preset=preset)
        try:
            curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:
            pass
        self._set_message(
            "Forest Fire — [Space]Run [P/N]Preset [Click]Ignite [Shift+F]Exit"
        )

    def _stop_forestfire(self) -> None:
        """Exit Forest Fire simulation mode."""
        self.forestfire_mode = False
        self.running = False
        self.forestfire_world = None
        self.forestfire_gen = 0
        self._set_message("Forest fire mode ended")

    def _forestfire_tick(self) -> None:
        """Advance one forest fire simulation step."""
        if self.forestfire_world:
            self.forestfire_world.tick()
            self.forestfire_gen += 1

    def _draw_forestfire(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Forest Fire simulation."""
        if not self.forestfire_world:
            return
        fw = self.forestfire_world

        draw_h = min(grid_rows, fw.height)
        draw_w = min(grid_cols, fw.width)

        for r in range(draw_h):
            row = fw.grid[r]
            cool_row = fw.cooldown[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                cell = row[c]
                if cell == FIRE_EMPTY:
                    continue

                if cell == FIRE_TREE:
                    ch = "██"
                    if self.use_color:
                        attr = curses.color_pair(140)
                    else:
                        attr = curses.A_NORMAL
                elif cell == FIRE_BURNING:
                    ch = "▓▓"
                    if self.use_color:
                        attr = curses.color_pair(142) | curses.A_BOLD
                    else:
                        attr = curses.A_BOLD | curses.A_REVERSE
                elif cell == FIRE_CHARRED:
                    remaining = cool_row[c]
                    if remaining > fw.charred_cooldown // 2:
                        ch = "░░"
                        if self.use_color:
                            attr = curses.color_pair(143)
                        else:
                            attr = curses.A_DIM
                    else:
                        ch = "░░"
                        if self.use_color:
                            attr = curses.color_pair(144)
                        else:
                            attr = curses.A_DIM
                else:
                    continue

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = FORESTFIRE_PRESET_NAMES[fw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = fw.stats
            sparkline = fw.sparkline(min(30, max(5, max_w // 6)))
            status = (
                f" Forest Fire | Gen: {self.forestfire_gen} | "
                f"Trees: {st['trees']} ({st['density']:.1%}) | "
                f"Burning: {st['burning']} | Charred: {st['charred']} | "
                f"Fire: {st['current_fire']} (avg:{st['avg_fire']:.0f} max:{st['max_fire']}) | "
                f"{sparkline} | "
                f"Preset: {preset_name} | {state_str} "
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
                "[P/N]Preset [F]aster [D]slower | "
                "[g/G]Growth± [l/L]Lightning± | "
                "[Click]Ignite | [Shift+F]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- DLA (Diffusion-Limited Aggregation) mode ---

    def _handle_dla_input(self, key: int) -> bool:
        """Handle input while in DLA mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            self._dla_tick()
        elif key == ord("r"):
            if self.dla_world:
                self.dla_world.reset()
                self.dla_gen = 0
                self._set_message("DLA reset")
        elif key == ord("p"):
            if self.dla_world:
                name = self.dla_world.cycle_preset(-1)
                self.dla_preset_idx = self.dla_world.preset_idx
                self.dla_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            if self.dla_world:
                name = self.dla_world.cycle_preset(1)
                self.dla_preset_idx = self.dla_world.preset_idx
                self.dla_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("f"):
            if self.dla_world:
                self.dla_world.walkers_per_tick = min(
                    200, self.dla_world.walkers_per_tick + 10
                )
                self._set_message(f"Steps/tick: {self.dla_world.walkers_per_tick}")
        elif key == ord("d"):
            if self.dla_world:
                self.dla_world.walkers_per_tick = max(
                    5, self.dla_world.walkers_per_tick - 10
                )
                self._set_message(f"Steps/tick: {self.dla_world.walkers_per_tick}")
        elif key == ord("w"):
            if self.dla_world:
                self.dla_world.num_walkers = min(5000, self.dla_world.num_walkers + 100)
                self._set_message(f"Walkers: {self.dla_world.num_walkers}")
        elif key == ord("W"):
            if self.dla_world:
                self.dla_world.num_walkers = max(50, self.dla_world.num_walkers - 100)
                self._set_message(f"Walkers: {self.dla_world.num_walkers}")
        elif key == ord("k"):
            if self.dla_world:
                self.dla_world.stickiness = min(1.0, self.dla_world.stickiness + 0.1)
                self._set_message(f"Stickiness: {self.dla_world.stickiness:.1f}")
        elif key == ord("K"):
            if self.dla_world:
                self.dla_world.stickiness = max(0.1, self.dla_world.stickiness - 0.1)
                self._set_message(f"Stickiness: {self.dla_world.stickiness:.1f}")
        elif key == ord("L") or key == 27:  # Shift+L or ESC to exit
            self._stop_dla()
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if self.dla_world and bstate & curses.BUTTON1_CLICKED:
                    gc = mx // 2
                    gr = my
                    self.dla_world.add_seed(gr, gc)
            except curses.error:
                pass
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_dla(self) -> None:
        """Enter DLA simulation mode."""
        self.running = False
        self.dla_mode = True
        self.dla_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = DLA_PRESET_NAMES[self.dla_preset_idx]
        self.dla_world = DLAWorld(w, h, preset=preset)
        try:
            curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:
            pass
        self._set_message(
            "DLA — [Space]Run [P/N]Preset [Click]Seed [Shift+L]Exit"
        )

    def _stop_dla(self) -> None:
        """Exit DLA simulation mode."""
        self.dla_mode = False
        self.running = False
        self.dla_world = None
        self.dla_gen = 0
        self._set_message("DLA mode ended")

    def _dla_tick(self) -> None:
        """Advance one DLA simulation step."""
        if self.dla_world:
            self.dla_world.tick()
            self.dla_gen += 1

    def _draw_dla(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the DLA simulation."""
        if not self.dla_world:
            return
        dw = self.dla_world

        draw_h = min(grid_rows, dw.height)
        draw_w = min(grid_cols, dw.width)

        max_order = max(1, dw.max_crystal_order)

        # Build walker set for fast lookup
        walker_set = set(dw.walkers)

        for r in range(draw_h):
            row = dw.grid[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                val = row[c]
                if val > 0:
                    # Crystal cell — color by age
                    age_frac = val / max_order
                    if age_frac < 0.1:
                        ch = "██"
                        cp = 150  # white: core
                    elif age_frac < 0.35:
                        ch = "██"
                        cp = 153  # magenta: old
                    elif age_frac < 0.6:
                        ch = "▓▓"
                        cp = 152  # blue: mid
                    elif age_frac < 0.85:
                        ch = "▒▒"
                        cp = 151  # cyan: young
                    else:
                        ch = "░░"
                        cp = 155  # green: tips
                elif (r, c) in walker_set:
                    ch = "··"
                    cp = 154  # yellow: walker
                else:
                    continue

                try:
                    if self.use_color:
                        self.stdscr.addstr(r, sc, ch, curses.color_pair(cp))
                    else:
                        attr = curses.A_BOLD if val > 0 else curses.A_DIM
                        self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = DLA_PRESET_NAMES[dw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = dw.stats
            status = (
                f" DLA | Gen: {self.dla_gen} | "
                f"Crystals: {st['crystals']} ({st['coverage']:.1%}) | "
                f"Walkers: {st['walkers']} | "
                f"Sticky: {dw.stickiness:.1f} | "
                f"Preset: {preset_name} | {state_str} "
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
                "[P/N]Preset [F]aster [D]slower | "
                "[w/W]Walkers± [k/K]Sticky± | "
                "[Click]Seed | [Shift+L]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Epidemic SIR (Susceptible-Infected-Recovered) mode ---

    def _handle_sir_input(self, key: int) -> bool:
        """Handle input while in Epidemic SIR mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            self._sir_tick()
        elif key == ord("r"):
            if self.sir_world:
                self.sir_world.reset()
                self.sir_gen = 0
                self._set_message("SIR simulation reset")
        elif key == ord("p"):
            if self.sir_world:
                name = self.sir_world.cycle_preset(-1)
                self.sir_preset_idx = self.sir_world.preset_idx
                self.sir_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            if self.sir_world:
                name = self.sir_world.cycle_preset(1)
                self.sir_preset_idx = self.sir_world.preset_idx
                self.sir_gen = 0
                self._set_message(f"Preset: {name}")
        elif key == ord("f"):
            if self.sir_world:
                self.sir_world.steps_per_tick = min(
                    20, self.sir_world.steps_per_tick + 1
                )
                self._set_message(f"Steps/tick: {self.sir_world.steps_per_tick}")
        elif key == ord("d"):
            if self.sir_world:
                self.sir_world.steps_per_tick = max(
                    1, self.sir_world.steps_per_tick - 1
                )
                self._set_message(f"Steps/tick: {self.sir_world.steps_per_tick}")
        elif key == ord("b"):
            # Increase transmission rate (beta)
            if self.sir_world:
                self.sir_world.beta = min(1.0, self.sir_world.beta + 0.02)
                self._set_message(f"Beta (transmission): {self.sir_world.beta:.3f}")
        elif key == ord("B"):
            # Decrease transmission rate
            if self.sir_world:
                self.sir_world.beta = max(0.0, self.sir_world.beta - 0.02)
                self._set_message(f"Beta (transmission): {self.sir_world.beta:.3f}")
        elif key == ord("g"):
            # Increase recovery rate (gamma)
            if self.sir_world:
                self.sir_world.gamma = min(1.0, self.sir_world.gamma + 0.01)
                self._set_message(f"Gamma (recovery): {self.sir_world.gamma:.3f}")
        elif key == ord("G"):
            # Decrease recovery rate
            if self.sir_world:
                self.sir_world.gamma = max(0.0, self.sir_world.gamma - 0.01)
                self._set_message(f"Gamma (recovery): {self.sir_world.gamma:.3f}")
        elif key == ord("m"):
            # Increase mortality
            if self.sir_world:
                self.sir_world.mortality = min(1.0, self.sir_world.mortality + 0.005)
                self._set_message(f"Mortality: {self.sir_world.mortality:.3f}")
        elif key == ord("M"):
            # Decrease mortality
            if self.sir_world:
                self.sir_world.mortality = max(0.0, self.sir_world.mortality - 0.005)
                self._set_message(f"Mortality: {self.sir_world.mortality:.3f}")
        elif key == ord("H") or key == 27:  # Shift+H or ESC to exit
            self._stop_sir()
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if self.sir_world and bstate & curses.BUTTON1_CLICKED:
                    gc = mx // 2
                    gr = my
                    self.sir_world.infect_at(gr, gc)
            except curses.error:
                pass
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_sir(self) -> None:
        """Enter Epidemic SIR simulation mode."""
        self.running = False
        self.sir_mode = True
        self.sir_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = SIR_PRESET_NAMES[self.sir_preset_idx]
        self.sir_world = SIRWorld(w, h, preset=preset)
        try:
            curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:
            pass
        self._set_message(
            "Epidemic SIR — [Space]Run [P/N]Preset [Click]Infect [Shift+H]Exit"
        )

    def _stop_sir(self) -> None:
        """Exit Epidemic SIR simulation mode."""
        self.sir_mode = False
        self.running = False
        self.sir_world = None
        self.sir_gen = 0
        self._set_message("Epidemic SIR mode ended")

    def _sir_tick(self) -> None:
        """Advance one SIR simulation step."""
        if self.sir_world:
            self.sir_world.tick()
            self.sir_gen += 1

    def _draw_sir(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Epidemic SIR simulation."""
        if not self.sir_world:
            return
        sw = self.sir_world

        draw_h = min(grid_rows, sw.height)
        draw_w = min(grid_cols, sw.width)

        for r in range(draw_h):
            row = sw.grid[r]
            age_row = sw.age[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                cell = row[c]
                if cell == SIR_SUSCEPTIBLE:
                    ch = "██"
                    if self.use_color:
                        attr = curses.color_pair(160)
                    else:
                        attr = curses.A_NORMAL
                elif cell == SIR_INFECTED:
                    age = age_row[c]
                    if age <= 3:
                        ch = "▓▓"
                        if self.use_color:
                            attr = curses.color_pair(162) | curses.A_BOLD  # yellow early
                        else:
                            attr = curses.A_BOLD | curses.A_REVERSE
                    elif age <= 8:
                        ch = "██"
                        if self.use_color:
                            attr = curses.color_pair(161) | curses.A_BOLD  # red
                        else:
                            attr = curses.A_BOLD | curses.A_REVERSE
                    else:
                        ch = "░░"
                        if self.use_color:
                            attr = curses.color_pair(165)  # magenta late
                        else:
                            attr = curses.A_BOLD
                elif cell == SIR_RECOVERED:
                    ch = "░░"
                    if self.use_color:
                        attr = curses.color_pair(163)
                    else:
                        attr = curses.A_DIM
                elif cell == SIR_DEAD:
                    ch = "··"
                    if self.use_color:
                        attr = curses.color_pair(164) | curses.A_DIM
                    else:
                        attr = curses.A_DIM
                else:
                    continue

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = SIR_PRESET_NAMES[sw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = sw.stats
            sparkline = sw.sparkline(min(30, max(5, max_w // 6)))
            status = (
                f" SIR Epidemic | Gen: {self.sir_gen} | "
                f"S: {st['susceptible']} ({st['s_pct']:.1%}) | "
                f"I: {st['infected']} ({st['i_pct']:.1%}) | "
                f"R: {st['recovered']} ({st['r_pct']:.1%}) | "
                f"D: {st['dead']} | "
                f"β={sw.beta:.2f} γ={sw.gamma:.2f} μ={sw.mortality:.3f} | "
                f"{sparkline} | "
                f"{preset_name} | {state_str} "
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
                "[P/N]Preset [F]aster [D]slower | "
                "[b/B]Beta± [g/G]Gamma± [m/M]Mortality± | "
                "[Click]Infect | [Shift+H]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Maze Generator & Solver mode ---

    def _handle_maze_input(self, key: int) -> bool:
        """Handle input while in Maze mode."""
        if key == ord("q"):
            return False
        elif key == ord(" "):
            self.running = not self.running
        elif key == ord("s"):
            self._maze_tick()
        elif key == ord("r"):
            if self.maze_world:
                self.maze_world.reset()
                self.maze_gen = 0
                self.running = True
                self._set_message("Maze reset — generating…")
        elif key == ord("p"):
            if self.maze_world:
                name = self.maze_world.cycle_preset(-1)
                self.maze_preset_idx = self.maze_world.preset_idx
                self.maze_gen = 0
                self.running = True
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            if self.maze_world:
                name = self.maze_world.cycle_preset(1)
                self.maze_preset_idx = self.maze_world.preset_idx
                self.maze_gen = 0
                self.running = True
                self._set_message(f"Preset: {name}")
        elif key == ord("f"):
            if self.maze_world:
                self.maze_world.solve_speed = min(50, self.maze_world.solve_speed + 1)
                self.maze_world.gen_speed = min(80, self.maze_world.gen_speed + 2)
                self._set_message(f"Speed: gen={self.maze_world.gen_speed} solve={self.maze_world.solve_speed}")
        elif key == ord("d"):
            if self.maze_world:
                self.maze_world.solve_speed = max(1, self.maze_world.solve_speed - 1)
                self.maze_world.gen_speed = max(1, self.maze_world.gen_speed - 2)
                self._set_message(f"Speed: gen={self.maze_world.gen_speed} solve={self.maze_world.solve_speed}")
        elif key == ord("g"):
            # Re-generate (new random maze)
            if self.maze_world:
                self.maze_world.reset()
                self.maze_gen = 0
                self.running = True
                self._set_message("New maze generating…")
        elif key == ord("v"):
            # Manually trigger solve
            if self.maze_world and self.maze_world.gen_done and not self.maze_world.solving:
                self.maze_world.start_solve()
                self.running = True
                self._set_message("Solving…")
        elif key == ord("M") or key == 27:  # Shift+M or ESC to exit
            self._stop_maze()
        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if self.maze_world and bstate & curses.BUTTON1_CLICKED:
                    gc = mx // 2
                    gr = my
                    self.maze_world.toggle_wall(gr, gc)
            except curses.error:
                pass
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_maze(self) -> None:
        """Enter Maze Generator & Solver mode."""
        self.running = True
        self.maze_mode = True
        self.maze_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(5, max_w // 2)
        h = max(5, max_h - 3)
        preset = MAZE_PRESET_NAMES[self.maze_preset_idx]
        self.maze_world = MazeWorld(w, h, preset=preset)
        try:
            curses.mousemask(curses.BUTTON1_CLICKED)
        except curses.error:
            pass
        self._set_message(
            "Maze Solver — [Space]Run [P/N]Preset [G]enerate [V]Solve [Click]Wall [Shift+M]Exit"
        )

    def _stop_maze(self) -> None:
        """Exit Maze mode."""
        self.maze_mode = False
        self.running = False
        self.maze_world = None
        self.maze_gen = 0
        self._set_message("Maze mode ended")

    def _maze_tick(self) -> None:
        """Advance one maze simulation step."""
        if self.maze_world:
            self.maze_world.tick()
            self.maze_gen += 1

    def _draw_maze(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Maze Generator & Solver simulation."""
        if not self.maze_world:
            return
        mw = self.maze_world

        draw_h = min(grid_rows, mw.height)
        draw_w = min(grid_cols, mw.width)

        for r in range(draw_h):
            row = mw.grid[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                cell = row[c]
                if cell == MAZE_WALL:
                    ch = "██"
                    if self.use_color:
                        attr = curses.color_pair(170) | curses.A_DIM
                    else:
                        attr = curses.A_REVERSE
                elif cell == MAZE_PATH:
                    ch = "  "
                    attr = curses.A_NORMAL
                elif cell == MAZE_START:
                    ch = "SS"
                    if self.use_color:
                        attr = curses.color_pair(172) | curses.A_BOLD
                    else:
                        attr = curses.A_BOLD
                elif cell == MAZE_END:
                    ch = "EE"
                    if self.use_color:
                        attr = curses.color_pair(173) | curses.A_BOLD
                    else:
                        attr = curses.A_BOLD | curses.A_REVERSE
                elif cell == MAZE_VISITED:
                    ch = "░░"
                    if self.use_color:
                        attr = curses.color_pair(174)
                    else:
                        attr = curses.A_DIM
                elif cell == MAZE_SOLUTION:
                    ch = "██"
                    if self.use_color:
                        attr = curses.color_pair(175) | curses.A_BOLD
                    else:
                        attr = curses.A_BOLD
                elif cell == MAZE_FRONTIER:
                    ch = "▓▓"
                    if self.use_color:
                        attr = curses.color_pair(176)
                    else:
                        attr = curses.A_NORMAL
                elif cell == MAZE_CARVING:
                    ch = "▒▒"
                    if self.use_color:
                        attr = curses.color_pair(177) | curses.A_BOLD
                    else:
                        attr = curses.A_BOLD
                else:
                    continue

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            preset_name = MAZE_PRESET_NAMES[mw.preset_idx]
            state_str = "RUNNING" if self.running else "PAUSED"
            st = mw.stats
            phase = mw.phase
            status = (
                f" Maze Solver | Gen: {self.maze_gen} | "
                f"Phase: {phase} | "
                f"Walls: {st['walls']} Paths: {st['paths']} | "
                f"Explored: {st['visited']} Frontier: {st['frontier']} | "
                f"Solution: {st['sol_len']} | "
                f"{preset_name} | {state_str} "
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
                " [Space]Run [S]tep [R]eset [G]enerate [V]Solve | "
                "[P/N]Preset [F]aster [D]slower | "
                "[Click]Toggle wall | [Shift+M]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Fractal Explorer mode ---

    def _handle_fractal_input(self, key: int) -> bool:
        """Handle input while in Fractal Explorer mode."""
        if key == ord("q"):
            return False
        elif key in (curses.KEY_UP, ord("k")):
            if self.fractal_world:
                self.fractal_world.pan(0, -1)
                self.fractal_world.cursor_r = max(0, self.fractal_world.cursor_r - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            if self.fractal_world:
                self.fractal_world.pan(0, 1)
                self.fractal_world.cursor_r = min(self.fractal_world.height - 1, self.fractal_world.cursor_r + 1)
        elif key in (curses.KEY_LEFT, ord("h")):
            if self.fractal_world:
                self.fractal_world.pan(-1, 0)
                self.fractal_world.cursor_c = max(0, self.fractal_world.cursor_c - 1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            if self.fractal_world:
                self.fractal_world.pan(1, 0)
                self.fractal_world.cursor_c = min(self.fractal_world.width - 1, self.fractal_world.cursor_c + 1)
        elif key == ord("+") or key == ord("=") or key == ord("i"):
            if self.fractal_world:
                self.fractal_world.zoom_in()
                self._set_message(f"Zoom: {self.fractal_world.zoom:.1f}x")
        elif key == ord("-") or key == ord("o"):
            if self.fractal_world:
                self.fractal_world.zoom_out()
                self._set_message(f"Zoom: {self.fractal_world.zoom:.1f}x")
        elif key == ord("]"):
            if self.fractal_world:
                self.fractal_world.increase_iter()
                self._set_message(f"Max iterations: {self.fractal_world.max_iter}")
        elif key == ord("["):
            if self.fractal_world:
                self.fractal_world.decrease_iter()
                self._set_message(f"Max iterations: {self.fractal_world.max_iter}")
        elif key == ord("J") or key == ord(" "):
            if self.fractal_world:
                self.fractal_world.toggle_julia()
                mode = "Julia" if self.fractal_world.julia_mode else "Mandelbrot"
                self._set_message(f"Switched to {mode} set")
        elif key == ord("c"):
            if self.fractal_world:
                name = self.fractal_world.cycle_palette()
                self._set_message(f"Palette: {name}")
        elif key == ord("p"):
            if self.fractal_world:
                name = self.fractal_world.cycle_preset(-1)
                self.fractal_preset_idx = self.fractal_world.preset_idx
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            if self.fractal_world:
                name = self.fractal_world.cycle_preset(1)
                self.fractal_preset_idx = self.fractal_world.preset_idx
                self._set_message(f"Preset: {name}")
        elif key == ord("r"):
            if self.fractal_world:
                self.fractal_world.reset()
                self.fractal_gen = 0
                self._set_message("View reset")
        elif key == ord("Z") or key == 27:  # Shift+Z or ESC to exit
            self._stop_fractal()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_fractal(self) -> None:
        """Enter Fractal Explorer mode."""
        self.running = False
        self.fractal_mode = True
        self.fractal_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = FRACTAL_PRESET_NAMES[self.fractal_preset_idx]
        self.fractal_world = FractalWorld(w, h, preset=preset)
        self._set_message(
            "Fractal Explorer — [Arrows]Pan [+/-]Zoom [Space]Julia [C]olor [P/N]Preset [Shift+Z]Exit"
        )

    def _stop_fractal(self) -> None:
        """Exit Fractal Explorer mode."""
        self.fractal_mode = False
        self.running = False
        self.fractal_world = None
        self.fractal_gen = 0
        self._set_message("Fractal Explorer mode ended")

    def _fractal_tick(self) -> None:
        """Advance one fractal computation step."""
        if self.fractal_world:
            self.fractal_world.tick()
            self.fractal_gen += 1

    def _draw_fractal(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Fractal Explorer simulation."""
        if not self.fractal_world:
            return
        fw = self.fractal_world

        # Ensure computed
        fw.compute()

        draw_h = min(grid_rows, fw.height)
        draw_w = min(grid_cols, fw.width)

        for r in range(draw_h):
            row_data = fw.grid[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                n = row_data[c]
                ch, attr = fw.iter_to_char_attr(n, self.use_color)

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Draw cursor crosshair (only in Mandelbrot mode for Julia selection)
        if not fw.julia_mode:
            cr, cc = fw.cursor_r, fw.cursor_c
            if 0 <= cr < draw_h and 0 <= cc < draw_w:
                sc = cc * 2
                if sc + 1 < max_w:
                    try:
                        self.stdscr.addstr(cr, sc, "++", curses.A_REVERSE | curses.A_BOLD)
                    except curses.error:
                        pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            st = fw.stats
            preset_name = FRACTAL_PRESET_NAMES[fw.preset_idx]
            if fw.julia_mode:
                status = (
                    f" {st['mode']} | c=({st['julia_re']:.4f}, {st['julia_im']:.4f}i) | "
                    f"Zoom: {st['zoom']:.1f}x | Iter: {st['max_iter']} | "
                    f"Palette: {st['palette']} | {preset_name} "
                )
            else:
                status = (
                    f" {st['mode']} | Center: ({st['center_re']:.6f}, {st['center_im']:.6f}i) | "
                    f"Zoom: {st['zoom']:.1f}x | Iter: {st['max_iter']} | "
                    f"Cursor: ({st['cursor_re']:.4f}, {st['cursor_im']:.4f}i) | "
                    f"Palette: {st['palette']} | {preset_name} "
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
                " [Arrows/hjkl]Pan [+/-/i/o]Zoom []/[]Iter | "
                "[Space/J]Toggle Julia [C]olor palette | "
                "[P/N]Preset [R]eset | [Shift+Z]Exit [Q]uit"
            )
            try:
                self.stdscr.addstr(help_y, 0, help_text[:max_w - 1], curses.A_DIM)
            except curses.error:
                pass

    # --- Strange Attractor mode ---

    def _handle_attractor_input(self, key: int) -> bool:
        """Handle input while in Strange Attractor mode."""
        if key == ord("q"):
            return False
        elif key == ord("c"):
            if self.attractor_world:
                name = self.attractor_world.cycle_palette()
                self._set_message(f"Palette: {name}")
        elif key == ord("p"):
            if self.attractor_world:
                name = self.attractor_world.cycle_preset(-1)
                self.attractor_preset_idx = self.attractor_world.preset_idx
                self._set_message(f"Preset: {name}")
        elif key == ord("n"):
            if self.attractor_world:
                name = self.attractor_world.cycle_preset(1)
                self.attractor_preset_idx = self.attractor_world.preset_idx
                self._set_message(f"Preset: {name}")
        elif key == ord("r"):
            if self.attractor_world:
                self.attractor_world.reset()
                self.attractor_gen = 0
                self._set_message("Reset")
        elif key == ord(" "):
            if self.attractor_world:
                rot = self.attractor_world.toggle_rotate()
                self._set_message(f"Auto-rotate: {'ON' if rot else 'OFF'}")
        elif key == ord("+") or key == ord("="):
            if self.attractor_world:
                self.attractor_world.view_scale *= 1.2
                self._set_message(f"Scale: {self.attractor_world.view_scale:.2f}x")
        elif key == ord("-"):
            if self.attractor_world:
                self.attractor_world.view_scale = max(0.1, self.attractor_world.view_scale / 1.2)
                self._set_message(f"Scale: {self.attractor_world.view_scale:.2f}x")
        elif key in (curses.KEY_LEFT, ord("h")):
            if self.attractor_world:
                self.attractor_world.pan_x -= 2.0
        elif key in (curses.KEY_RIGHT, ord("l")):
            if self.attractor_world:
                self.attractor_world.pan_x += 2.0
        elif key in (curses.KEY_UP, ord("k")):
            if self.attractor_world:
                self.attractor_world.pan_y += 2.0
        elif key in (curses.KEY_DOWN, ord("j")):
            if self.attractor_world:
                self.attractor_world.pan_y -= 2.0
        elif key == ord("1"):
            if self.attractor_world:
                aw = self.attractor_world
                if aw.attractor_type == "lorenz":
                    v = aw.adjust_param("sigma", 1.0)
                    self._set_message(f"σ = {v:.1f}")
                elif aw.attractor_type == "rossler":
                    v = aw.adjust_param("a", 0.01)
                    self._set_message(f"a = {v:.3f}")
                elif aw.attractor_type == "henon":
                    v = aw.adjust_param("a", 0.01)
                    self._set_message(f"a = {v:.3f}")
        elif key == ord("2"):
            if self.attractor_world:
                aw = self.attractor_world
                if aw.attractor_type == "lorenz":
                    v = aw.adjust_param("rho", 1.0)
                    self._set_message(f"ρ = {v:.1f}")
                elif aw.attractor_type == "rossler":
                    v = aw.adjust_param("b", 0.01)
                    self._set_message(f"b = {v:.3f}")
                elif aw.attractor_type == "henon":
                    v = aw.adjust_param("b", 0.01)
                    self._set_message(f"b = {v:.3f}")
        elif key == ord("3"):
            if self.attractor_world:
                aw = self.attractor_world
                if aw.attractor_type == "lorenz":
                    v = aw.adjust_param("beta", 0.1)
                    self._set_message(f"β = {v:.3f}")
                elif aw.attractor_type == "rossler":
                    v = aw.adjust_param("c", 0.5)
                    self._set_message(f"c = {v:.1f}")
        elif key == ord("!"):
            if self.attractor_world:
                aw = self.attractor_world
                if aw.attractor_type == "lorenz":
                    v = aw.adjust_param("sigma", -1.0)
                    self._set_message(f"σ = {v:.1f}")
                elif aw.attractor_type == "rossler":
                    v = aw.adjust_param("a", -0.01)
                    self._set_message(f"a = {v:.3f}")
                elif aw.attractor_type == "henon":
                    v = aw.adjust_param("a", -0.01)
                    self._set_message(f"a = {v:.3f}")
        elif key == ord("@"):
            if self.attractor_world:
                aw = self.attractor_world
                if aw.attractor_type == "lorenz":
                    v = aw.adjust_param("rho", -1.0)
                    self._set_message(f"ρ = {v:.1f}")
                elif aw.attractor_type == "rossler":
                    v = aw.adjust_param("b", -0.01)
                    self._set_message(f"b = {v:.3f}")
                elif aw.attractor_type == "henon":
                    v = aw.adjust_param("b", -0.01)
                    self._set_message(f"b = {v:.3f}")
        elif key == ord("#"):
            if self.attractor_world:
                aw = self.attractor_world
                if aw.attractor_type == "lorenz":
                    v = aw.adjust_param("beta", -0.1)
                    self._set_message(f"β = {v:.3f}")
                elif aw.attractor_type == "rossler":
                    v = aw.adjust_param("c", -0.5)
                    self._set_message(f"c = {v:.1f}")
        elif key == ord("A") or key == 27:  # Shift+A or ESC to exit
            self._stop_attractor()
        elif key == curses.KEY_RESIZE:
            pass
        return True

    def _start_attractor(self) -> None:
        """Enter Strange Attractor visualization mode."""
        self.attractor_mode = True
        self.attractor_gen = 0
        max_h, max_w = self.stdscr.getmaxyx()
        w = max(4, max_w // 2)
        h = max(4, max_h - 3)
        preset = ATTRACTOR_PRESET_NAMES[self.attractor_preset_idx]
        self.attractor_world = AttractorWorld(w, h, preset=preset)
        self.running = True
        self._set_message(
            "Strange Attractors — [P/N]Preset [C]olor [Space]Rotate [+/-]Scale [1-3/!@#]Params [Shift+A]Exit"
        )

    def _stop_attractor(self) -> None:
        """Exit Strange Attractor mode."""
        self.attractor_mode = False
        self.running = False
        self.attractor_world = None
        self.attractor_gen = 0
        self._set_message("Strange Attractor mode ended")

    def _attractor_tick(self) -> None:
        """Advance one attractor simulation step."""
        if self.attractor_world:
            self.attractor_world.tick()
            self.attractor_gen += 1

    def _draw_attractor(self, max_h: int, max_w: int, grid_rows: int, grid_cols: int) -> None:
        """Draw the Strange Attractor visualization."""
        if not self.attractor_world:
            return
        aw = self.attractor_world

        draw_h = min(grid_rows, aw.height)
        draw_w = min(grid_cols, aw.width)

        for r in range(draw_h):
            row_data = aw.density[r]
            for c in range(draw_w):
                sc = c * 2
                if sc + 1 >= max_w:
                    break

                val = row_data[c]
                ch, attr = aw.density_to_char_attr(val, self.use_color)

                try:
                    self.stdscr.addstr(r, sc, ch, attr)
                except curses.error:
                    pass

        # Status bar
        status_y = max_h - 2
        if status_y > 0:
            st = aw.stats
            preset_name = ATTRACTOR_PRESET_NAMES[aw.preset_idx]
            params = st["params"]
            param_str = " ".join(f"{k}={v}" for k, v in params.items() if k != "type")
            status = (
                f" {st['attractor']} | {param_str} | "
                f"Steps: {st['steps']} | Trail: {st['trail']} | "
                f"Palette: {st['palette']} | {preset_name} "
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
                " [P/N]Preset [C]olor [Space]Toggle rotate [+/-]Scale [Arrows]Pan | "
                "[1/2/3]Inc param [!/@ /#]Dec param | [R]eset [Shift+A]Exit [Q]uit"
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

        if self.menu_mode:
            self._draw_menu(max_h, max_w)
        elif self.lenia_mode:
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
        elif self.boids_mode:
            self._draw_boids(max_h, max_w, grid_rows, grid_cols)
        elif self.nca_mode:
            self._draw_nca(max_h, max_w, grid_rows, grid_cols)
        elif self.wfc_mode:
            self._draw_wfc(max_h, max_w, grid_rows, grid_cols)
        elif self.turmite_mode:
            self._draw_turmite(max_h, max_w, grid_rows, grid_cols)
        elif self.erosion_mode:
            self._draw_erosion(max_h, max_w, grid_rows, grid_cols)
        elif self.magfield_mode:
            self._draw_magfield(max_h, max_w, grid_rows, grid_cols)
        elif self.nbody_mode:
            self._draw_nbody(max_h, max_w, grid_rows, grid_cols)
        elif self.sandpile_mode:
            self._draw_sandpile(max_h, max_w, grid_rows, grid_cols)
        elif self.forestfire_mode:
            self._draw_forestfire(max_h, max_w, grid_rows, grid_cols)
        elif self.dla_mode:
            self._draw_dla(max_h, max_w, grid_rows, grid_cols)
        elif self.sir_mode:
            self._draw_sir(max_h, max_w, grid_rows, grid_cols)
        elif self.maze_mode:
            self._draw_maze(max_h, max_w, grid_rows, grid_cols)
        elif self.fractal_mode:
            self._draw_fractal(max_h, max_w, grid_rows, grid_cols)
        elif self.attractor_mode:
            self._draw_attractor(max_h, max_w, grid_rows, grid_cols)
        elif self.split_mode:
            self._draw_split(max_h, max_w, grid_rows, grid_cols)
        elif self.blueprint_mode:
            self._draw_blueprint(max_h, max_w, grid_rows, grid_cols)
        else:
            self._draw_normal(max_h, max_w, grid_rows, grid_cols)

        # Demo tour overlay on top of whatever mode is drawing
        if self.demo_tour_mode:
            self._draw_demo_tour_overlay(max_h, max_w)

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

    # ---- Demo Tour (Screensaver) ----

    def _stop_current_mode(self) -> None:
        """Stop whichever simulation mode is currently active."""
        if self.lenia_mode:
            self._stop_lenia()
        elif self.wolfram_mode:
            self._stop_wolfram()
        elif self.multistate_mode:
            self._stop_multistate()
        elif self.sand_mode:
            self._stop_sand()
        elif self.rd_mode:
            self._stop_rd()
        elif self.pl_mode:
            self._stop_pl()
        elif self.eco_mode:
            self._stop_eco()
        elif self.physarum_mode:
            self._stop_physarum()
        elif self.fluid_mode:
            self._stop_fluid()
        elif self.ising_mode:
            self._stop_ising()
        elif self.boids_mode:
            self._stop_boids()
        elif self.nca_mode:
            self._stop_nca()
        elif self.wfc_mode:
            self._stop_wfc()
        elif self.turmite_mode:
            self._stop_turmite()
        elif self.erosion_mode:
            self._stop_erosion()
        elif self.magfield_mode:
            self._stop_magfield()
        elif self.nbody_mode:
            self._stop_nbody()
        elif self.sandpile_mode:
            self._stop_sandpile()
        elif self.forestfire_mode:
            self._stop_forestfire()
        elif self.dla_mode:
            self._stop_dla()
        elif self.sir_mode:
            self._stop_sir()
        elif self.maze_mode:
            self._stop_maze()
        elif self.fractal_mode:
            self._stop_fractal()
        elif self.attractor_mode:
            self._stop_attractor()
        elif self.split_mode:
            self._stop_split()
        elif self.evolve_mode:
            self._stop_evolve()

    def _start_demo_tour(self) -> None:
        """Start the demo tour screensaver that cycles through all modes."""
        self._stop_current_mode()
        self.demo_tour_mode = True
        self.demo_tour_idx = 0
        self.demo_tour_paused = False
        self._demo_tour_launch_current()

    def _stop_demo_tour(self) -> None:
        """Exit demo tour and return to Conway's Game of Life."""
        self._stop_current_mode()
        self.demo_tour_mode = False
        self.demo_tour_paused = False
        self.running = False
        self._set_message("Demo Tour ended — press ? for mode picker")

    def _demo_tour_launch_current(self) -> None:
        """Launch the mode at the current demo tour index."""
        self._stop_current_mode()
        _, label, _, method_name = self.MENU_MODES[self.demo_tour_idx]
        method = getattr(self, method_name)
        method()
        # Auto-run the simulation
        self.running = True
        self.demo_tour_start_time = time.monotonic()

    def _demo_tour_next(self) -> None:
        """Advance to the next mode in the tour."""
        self.demo_tour_idx = (self.demo_tour_idx + 1) % len(self.MENU_MODES)
        self._demo_tour_launch_current()

    def _demo_tour_prev(self) -> None:
        """Go back to the previous mode in the tour."""
        self.demo_tour_idx = (self.demo_tour_idx - 1) % len(self.MENU_MODES)
        self._demo_tour_launch_current()

    def _handle_demo_tour_input(self, key: int) -> bool:
        """Handle input during demo tour. Most keys exit the tour."""
        if key == ord("q"):
            self._stop_demo_tour()
            return False

        # Navigation within the tour
        if key in (curses.KEY_RIGHT, ord("n"), ord("l"), ord(" ")):
            self._demo_tour_next()
        elif key in (curses.KEY_LEFT, ord("p"), ord("h")):
            self._demo_tour_prev()
        # Pause/resume
        elif key == ord("P") or key == ord("k"):
            self.demo_tour_paused = not self.demo_tour_paused
            if not self.demo_tour_paused:
                # Reset timer so current mode gets a full duration from now
                self.demo_tour_start_time = time.monotonic()
        # Adjust duration
        elif key == ord("+") or key == ord("="):
            self.demo_tour_duration = min(60.0, self.demo_tour_duration + 2.0)
        elif key == ord("-") or key == ord("_"):
            self.demo_tour_duration = max(4.0, self.demo_tour_duration - 2.0)
        # Resize: ignore
        elif key == curses.KEY_RESIZE:
            pass
        # Any other key: exit demo tour, keep current mode running
        elif key == 27:  # Escape
            self._stop_demo_tour()
        elif key in (ord("\n"), ord("\r")):
            # Enter: exit tour but stay in current mode
            self.demo_tour_mode = False
            self.demo_tour_paused = False
            cat, label, desc, _ = self.MENU_MODES[self.demo_tour_idx]
            self._set_message(f"Staying in {label} — tour ended")
        return True

    def _draw_demo_tour_overlay(self, max_h: int, max_w: int) -> None:
        """Draw an informational overlay on top of the current mode during demo tour."""
        if max_h < 5 or max_w < 30:
            return

        cat, label, desc, _ = self.MENU_MODES[self.demo_tour_idx]
        idx = self.demo_tour_idx
        total = len(self.MENU_MODES)
        elapsed = time.monotonic() - self.demo_tour_start_time
        remaining = max(0.0, self.demo_tour_duration - elapsed) if not self.demo_tour_paused else self.demo_tour_duration - elapsed

        # Progress bar
        progress = min(1.0, elapsed / self.demo_tour_duration) if not self.demo_tour_paused else min(1.0, elapsed / self.demo_tour_duration)
        bar_width = min(30, max_w - 4)
        filled = int(bar_width * progress)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Build overlay lines
        mode_num = f"[{idx + 1}/{total}]"
        title_line = f" ▶ DEMO TOUR  {mode_num} "
        name_line = f" {label} "
        cat_line = f" {cat} "
        desc_line = f" {desc} "
        timer_line = f" {bar} {remaining:.0f}s " if not self.demo_tour_paused else f" {bar} PAUSED "
        controls_line = " ←/→:skip  P:pause  +/-:speed  Enter:stay  Esc:exit "

        lines = [title_line, cat_line, name_line, "", desc_line, timer_line, "", controls_line]

        # Calculate box dimensions
        box_w = max(len(line) for line in lines) + 4
        box_w = min(box_w, max_w - 2)
        box_h = len(lines) + 2  # +2 for top/bottom border

        # Position: top-right corner
        start_r = 1
        start_c = max(0, max_w - box_w - 2)

        # Draw box background
        try:
            # Top border
            top_border = "╭" + "─" * (box_w - 2) + "╮"
            self.stdscr.addstr(start_r, start_c, top_border[:max_w - start_c],
                               curses.color_pair(3) | curses.A_BOLD if self.use_color else curses.A_BOLD)

            for i, line in enumerate(lines):
                r = start_r + 1 + i
                if r >= max_h - 2:
                    break
                # Pad line to fill box
                padded = line.ljust(box_w - 2)[:box_w - 2]
                content = "│" + padded + "│"

                attr = curses.A_BOLD if self.use_color else curses.A_BOLD
                if i == 0:  # Title
                    attr = curses.color_pair(9) | curses.A_BOLD if self.use_color else curses.A_BOLD | curses.A_REVERSE
                elif i == 2:  # Mode name
                    attr = curses.color_pair(11) | curses.A_BOLD if self.use_color else curses.A_BOLD
                elif i == 4:  # Description
                    attr = curses.color_pair(3) if self.use_color else curses.A_DIM
                elif i == 5:  # Timer/progress
                    attr = curses.color_pair(10) | curses.A_BOLD if self.use_color else curses.A_BOLD
                elif i == 7:  # Controls
                    attr = curses.A_DIM

                self.stdscr.addstr(r, start_c, content[:max_w - start_c], attr)

            # Bottom border
            bot_r = start_r + len(lines) + 1
            if bot_r < max_h - 2:
                bot_border = "╰" + "─" * (box_w - 2) + "╯"
                self.stdscr.addstr(bot_r, start_c, bot_border[:max_w - start_c],
                                   curses.color_pair(3) | curses.A_BOLD if self.use_color else curses.A_BOLD)
        except curses.error:
            pass

    # ---- Mode Picker Menu ----

    def _menu_start_life(self) -> None:
        """Return to Conway's Game of Life (no-op if already there)."""
        self._set_message("Conway's Game of Life")

    def _open_menu(self) -> None:
        """Open the mode picker menu."""
        self.menu_mode = True
        self.menu_cursor = 0
        self.menu_scroll = 0

    def _close_menu(self) -> None:
        """Close the mode picker menu without launching anything."""
        self.menu_mode = False

    def _handle_menu_input(self, key: int) -> bool:
        """Handle input while mode picker menu is open."""
        num_items = len(self.MENU_MODES)

        if key == ord("q"):
            return False

        # Close menu
        if key in (27, ord("?"), ord("/")):  # Escape or toggle keys
            self._close_menu()

        # Navigate up
        elif key in (curses.KEY_UP, ord("k")):
            self.menu_cursor = (self.menu_cursor - 1) % num_items

        # Navigate down
        elif key in (curses.KEY_DOWN, ord("j")):
            self.menu_cursor = (self.menu_cursor + 1) % num_items

        # Jump to previous category
        elif key in (curses.KEY_LEFT, ord("h")):
            # Find the category of the current item
            cur_cat = self.MENU_MODES[self.menu_cursor][0]
            # Find the start of the previous category
            prev_start = 0
            for i, cat in enumerate(self._menu_categories):
                if cat == cur_cat:
                    if i > 0:
                        prev_start = self._menu_cat_indices[i - 1]
                    else:
                        prev_start = self._menu_cat_indices[-1]
                    break
            self.menu_cursor = prev_start

        # Jump to next category
        elif key in (curses.KEY_RIGHT, ord("l")):
            cur_cat = self.MENU_MODES[self.menu_cursor][0]
            next_start = 0
            for i, cat in enumerate(self._menu_categories):
                if cat == cur_cat:
                    if i < len(self._menu_categories) - 1:
                        next_start = self._menu_cat_indices[i + 1]
                    else:
                        next_start = self._menu_cat_indices[0]
                    break
            self.menu_cursor = next_start

        # Page up / Page down
        elif key == curses.KEY_PPAGE:
            self.menu_cursor = max(0, self.menu_cursor - 10)
        elif key == curses.KEY_NPAGE:
            self.menu_cursor = min(num_items - 1, self.menu_cursor + 10)

        # Home / End
        elif key == curses.KEY_HOME:
            self.menu_cursor = 0
        elif key == curses.KEY_END:
            self.menu_cursor = num_items - 1

        # Launch selected mode
        elif key in (curses.KEY_ENTER, ord("\n"), ord("\r")):
            _, label, _, method_name = self.MENU_MODES[self.menu_cursor]
            self._close_menu()
            method = getattr(self, method_name)
            method()

        # Launch demo tour from menu
        elif key == ord("!"):
            self._close_menu()
            self._start_demo_tour()

        elif key == curses.KEY_RESIZE:
            pass

        return True

    def _draw_menu(self, max_h: int, max_w: int) -> None:
        """Draw the full-screen mode picker menu."""
        # Title
        title = " Simulation Mode Picker "
        subtitle = " Use arrows to navigate, Enter to launch, ? or Esc to close "
        hint = " h/l or Left/Right: jump categories | ! Demo Tour (auto-cycle all modes) "

        # Center title
        col = max(0, (max_w - len(title)) // 2)
        try:
            if self.use_color:
                self.stdscr.addstr(0, col, title, curses.color_pair(9) | curses.A_BOLD)
            else:
                self.stdscr.addstr(0, col, title, curses.A_BOLD | curses.A_REVERSE)
        except curses.error:
            pass

        # Subtitle
        sub_col = max(0, (max_w - len(subtitle)) // 2)
        try:
            self.stdscr.addstr(1, sub_col, subtitle, curses.A_DIM)
        except curses.error:
            pass

        # Available rows for items (reserve top 3 lines and bottom 2)
        top_margin = 3
        bottom_margin = 2
        visible_rows = max(1, max_h - top_margin - bottom_margin)

        # Adjust scroll to keep cursor visible
        if self.menu_cursor < self.menu_scroll:
            self.menu_scroll = self.menu_cursor
        # Account for category headers when computing visible extent
        # Simple approach: scroll so cursor item is visible
        if self.menu_cursor >= self.menu_scroll + visible_rows:
            self.menu_scroll = self.menu_cursor - visible_rows + 1
        self.menu_scroll = max(0, self.menu_scroll)

        # Compute display lines: category headers + items
        # We build a flat list of display lines with their types
        display_lines: list[tuple[str, str, int]] = []  # (type, text, mode_idx)
        last_cat = ""
        for idx, (cat, label, desc, _) in enumerate(self.MENU_MODES):
            if cat != last_cat:
                if last_cat:
                    display_lines.append(("blank", "", -1))
                display_lines.append(("header", cat, -1))
                last_cat = cat
            display_lines.append(("item", f"  {label:<32s} {desc}", idx))

        # Find which display line corresponds to the cursor
        cursor_display_idx = 0
        for di, (dtype, _, midx) in enumerate(display_lines):
            if dtype == "item" and midx == self.menu_cursor:
                cursor_display_idx = di
                break

        # Adjust scroll based on display lines
        if cursor_display_idx < self.menu_scroll:
            self.menu_scroll = cursor_display_idx
        if cursor_display_idx >= self.menu_scroll + visible_rows:
            self.menu_scroll = cursor_display_idx - visible_rows + 1
        self.menu_scroll = max(0, min(self.menu_scroll, max(0, len(display_lines) - visible_rows)))

        # Category color mapping
        cat_colors = {
            "Cellular Automata": 11,  # cyan
            "Physics": 10,            # green
            "Biology": 9,             # yellow
            "Procedural": 12,         # magenta
            "Algorithms": 11,         # cyan
        }

        # Render visible lines
        row = top_margin
        for di in range(self.menu_scroll, min(len(display_lines), self.menu_scroll + visible_rows)):
            if row >= max_h - bottom_margin:
                break
            dtype, text, midx = display_lines[di]
            if dtype == "blank":
                row += 1
                continue
            elif dtype == "header":
                # Category header
                header_text = f" {text} "
                cat_col = cat_colors.get(text, 8)
                try:
                    if self.use_color:
                        self.stdscr.addstr(row, 1, header_text,
                                           curses.color_pair(cat_col) | curses.A_BOLD)
                    else:
                        self.stdscr.addstr(row, 1, header_text, curses.A_BOLD | curses.A_UNDERLINE)
                except curses.error:
                    pass
            elif dtype == "item":
                is_selected = (midx == self.menu_cursor)
                display_text = text[:max_w - 4]
                try:
                    if is_selected:
                        marker = " > "
                        if self.use_color:
                            self.stdscr.addstr(row, 0, marker, curses.color_pair(9) | curses.A_BOLD)
                            self.stdscr.addstr(row, 3, display_text, curses.A_REVERSE | curses.A_BOLD)
                        else:
                            self.stdscr.addstr(row, 0, marker, curses.A_BOLD)
                            self.stdscr.addstr(row, 3, display_text, curses.A_REVERSE | curses.A_BOLD)
                    else:
                        try:
                            self.stdscr.addstr(row, 3, display_text)
                        except curses.error:
                            pass
                except curses.error:
                    pass
            row += 1

        # Bottom hint bar
        try:
            hint_text = hint[:max_w - 1]
            self.stdscr.addstr(max_h - 1, max(0, (max_w - len(hint_text)) // 2),
                               hint_text, curses.A_DIM)
        except curses.error:
            pass

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
    parser.add_argument("--demo", action="store_true", help="Start in Demo Tour screensaver mode")
    parser.add_argument("--demo-duration", type=float, default=10.0, help="Seconds per mode in Demo Tour (default: 10)")
    args = parser.parse_args()

    def start(stdscr):
        max_h, max_w = stdscr.getmaxyx()
        w = args.width if args.width > 0 else max(1, max_w // 2)
        h = args.height if args.height > 0 else max(1, max_h - 3)
        app = App(stdscr, w, h, filepath=args.file)
        if args.demo:
            app.demo_tour_duration = args.demo_duration
            app._start_demo_tour()
        app.run()

    curses.wrapper(start)


if __name__ == "__main__":
    main()

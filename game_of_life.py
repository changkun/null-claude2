#!/usr/bin/env python3
"""Terminal-based cellular automaton simulator using curses."""

import argparse
import curses
import json
import os
import random
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
            if self.split_mode:
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

        if self.split_mode:
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
                f"[F/G]Rule [D]ash [H]eat [A]Evolve [M]Split [B]lue [X]Del [L]RLE [+/-]Spd [T]orus [</>]Rew [W]Save [O]Load"
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

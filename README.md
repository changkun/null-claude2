# Cellular Automaton Sandbox

A terminal-based simulation suite featuring 27 interactive modes — from Conway's Game of Life to fluid dynamics, fractal explorers, and 3D ray casting. All rendered in your terminal using curses.

## Requirements

- Python 3.12+
- A terminal with color support (256-color recommended)
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

```bash
# Clone and run
git clone <repo-url>
cd null-claude2

# Using uv (recommended)
uv run game_of_life.py

# Or with pip
pip install -e .
cellaut
```

## Usage

```bash
# Launch with default settings (auto-fits terminal size)
uv run game_of_life.py

# Custom grid size
uv run game_of_life.py --width 120 --height 40

# Start in demo tour mode (cycles through all simulations)
uv run game_of_life.py --demo

# Adjust demo tour speed (seconds per mode)
uv run game_of_life.py --demo --demo-duration 15

# Specify a save/load file path
uv run game_of_life.py --file my_save.json
```

Press `?` or `/` at any time to open the **Mode Picker** menu.

## Simulation Modes

Each mode has a scientific or mathematical background. See **[GUIDE.md](GUIDE.md)**
for detailed descriptions of the algorithms, history, and parameters behind
every simulation.

### Cellular Automata

| Mode | Key | Description |
|------|-----|-------------|
| Conway's Game of Life | *(default)* | Classic 2-state cellular automaton with pattern library, brush painting, heatmap, genetic evolver, and split-screen comparison |
| Wolfram 1D | `W` | All 256 elementary 1D cellular automata rules |
| Lenia | `L` | Continuous cellular automaton with smooth kernels |
| Multi-State | `Shift+X` | Brian's Brain, Wireworld, and Langton's Ant |
| Neural CA | `Shift+N` | Neural cellular automata with learned update rules |
| Abelian Sandpile | `Shift+J` | Self-organized criticality on a grid |

### Physics

| Mode | Key | Description |
|------|-----|-------------|
| Falling Sand | `F` | Particle-based sandbox with multiple materials (sand, water, fire, etc.) |
| Reaction-Diffusion | `Shift+R` | Gray-Scott model with multiple parameter presets |
| Fluid Dynamics | `Shift+D` | Lattice Boltzmann method fluid simulation |
| Ising Model | `Shift+I` | Statistical mechanics spin lattice with temperature control |
| Magnetic Field | `Shift+G` | Electromagnetic particle simulation |
| N-Body Gravity | `Shift+K` | Gravitational N-body simulation |
| Hydraulic Erosion | `Shift+Y` | Terrain erosion by water flow |
| DLA | `Shift+L` | Diffusion-limited aggregation crystal growth |
| Double Pendulum | `Shift+O` | Chaotic double pendulum with divergence visualization |

### Biology

| Mode | Key | Description |
|------|-----|-------------|
| Particle Life | `Shift+P` | Emergent life-like behavior from simple attraction rules |
| Wa-Tor Ecosystem | `Shift+E` | Predator-prey population dynamics |
| Physarum Slime | `Shift+S` | Slime mold agent-based network formation |
| Boids Flocking | `Shift+B` | Reynolds flocking with separation, alignment, and cohesion |
| Forest Fire | `Shift+F` | Stochastic forest fire cellular automaton |
| Epidemic SIR | `Shift+H` | Disease spread with susceptible/infected/recovered agents |

### Procedural Generation

| Mode | Key | Description |
|------|-----|-------------|
| Wave Function Collapse | `Shift+T` | Constraint-based procedural terrain generation |
| Turmites | `Shift+U` | 2D Turing machines on a grid |

### Algorithms

| Mode | Key | Description |
|------|-----|-------------|
| Maze Solver | `Shift+M` | Procedural maze generation with A* pathfinding |
| 3D Ray Caster | `Shift+V` | First-person 3D walk through generated mazes |

### Mathematics

| Mode | Key | Description |
|------|-----|-------------|
| Fractal Explorer | `Shift+Z` | Interactive Mandelbrot & Julia set explorer with zoom/pan |
| Strange Attractors | `Shift+A` | Lorenz, Rossler & Henon chaotic attractor visualization |

## Game of Life Controls

These controls apply in the default Conway's Game of Life mode:

| Key | Action |
|-----|--------|
| `Space` | Start/pause simulation |
| `Enter` | Toggle cell under cursor |
| Arrow keys | Move cursor |
| `+` / `-` | Adjust simulation speed |
| `P` / `N` | Cycle through pattern library |
| `R` | Randomize grid |
| `C` | Clear grid |
| `T` | Toggle toroidal wrapping |
| `<` / `>` | Rewind / fast-forward history |
| `V` | Toggle brush painting mode |
| `[` / `]` | Adjust brush size |
| `H` | Toggle heatmap visualization |
| `D` | Toggle pattern detection dashboard |
| `A` | Toggle genetic algorithm evolver |
| `M` | Toggle split-screen comparison mode |
| `G` / `F` | Cycle rule presets |
| `Shift+L` | Import RLE pattern file |
| `w` | Save state |
| `O` | Load state |
| `Q` | Quit |

## How It Was Built

This project was built through iterative AI-driven development using a thinker-worker architecture (see `.ralph/` for orchestration metadata). Starting from an empty repository, each round added a new simulation mode or feature, growing the codebase from a simple Game of Life to the full 27-mode simulation suite.

## License

MIT

# Simulation Mode Guide

This document describes the scientific background, formal descriptions,
algorithms, and controls for each of the 27 simulation modes in the Cellular
Automaton Sandbox.

---

## Cellular Automata

### Conway's Game of Life

**Background.**
Devised by mathematician John Conway in 1970, the Game of Life is the most
famous cellular automaton. It demonstrates how complex, seemingly intelligent
behavior can emerge from two trivially simple rules applied to a grid of
on/off cells.

Despite this simplicity, the Game of Life is Turing-complete. It supports
stable structures (blocks, beehives), oscillators (blinkers, pulsars),
spaceships (gliders, LWSS), and guns that manufacture gliders indefinitely.

**Formulation.**
Let `S(t) ⊂ Z²` be the set of live cells at generation `t`, where `Z²`
denotes the integer lattice (the grid). Define the Moore neighborhood of cell
`(r, c)` as `N(r, c) = {(r+i, c+j) : i, j ∈ {-1, 0, 1}} \ {(r, c)}` — the
8 surrounding cells. Let `n(r, c, t) = |N(r, c) ∩ S(t)|` be the number of
live neighbors at generation `t`. The standard Life rule (B3/S23) is:

```
S(t+1) = { (r,c) : n(r,c,t) ∈ B  if (r,c) ∉ S(t) }     (birth)
        ∪ { (r,c) : n(r,c,t) ∈ S  if (r,c) ∈ S(t) }     (survival)

where:
  B = {3}      — birth set: required neighbor count for a dead cell to be born
  S = {2, 3}   — survival set: required neighbor count for a live cell to survive
  H, W         — grid height and width
```

The sandbox supports arbitrary birth/survival rulesets. With toroidal boundary
conditions, indices wrap: `(r mod H, c mod W)`.

**Features in this sandbox.**
Pattern library (glider, Gosper gun, R-pentomino, etc.), brush painting with
configurable size and shape, heatmap overlay, genetic algorithm evolver,
split-screen comparison, cell age coloring, population sparkline, pattern
detection dashboard, toroidal wrapping, history rewind, blueprint mode, RLE
import, and save/load.

**Controls**: `Space` run/pause, `Enter` toggle cell, arrows move cursor,
`+/-` speed, `P/N` cycle patterns, `R` randomize, `C` clear, `T` toroidal,
`</>` rewind/forward, `V` brush, `H` heatmap, `D` dashboard, `A` evolver,
`M` split-screen, `G/F` rule presets, `w` save, `O` load.

**Source**: Martin Gardner, "Mathematical Games: The fantastic combinations of
John Conway's new solitaire game 'life'," *Scientific American*, vol. 223,
no. 4, pp. 120-123, October 1970.
[ibiblio.org](https://www.ibiblio.org/lifepatterns/october1970.html)

---

### Wolfram 1D Elementary Cellular Automata

**Background.**
Stephen Wolfram systematically studied all 256 one-dimensional cellular
automaton rules in the 1980s, cataloging them by number (0-255). Each rule
defines how a cell's next state depends on its current state and its two
immediate neighbors, encoded as an 8-bit lookup table.

Some notable rules:
- **Rule 30**: chaotic, used by Mathematica as a random number generator.
- **Rule 90**: produces the Sierpinski triangle fractal.
- **Rule 110**: proven to be Turing-complete by Matthew Cook in 2004.
- **Rule 184**: models basic traffic flow.

**Formulation.**
Let `s_i(t) ∈ {0, 1}` be the state of cell `i` at generation `t`. A rule
number `R ∈ [0, 255]` encodes an 8-entry lookup table. For each 3-cell
neighborhood pattern `(s_{i-1}, s_i, s_{i+1})`, compute the pattern index:

```
k = s_{i-1} · 4 + s_i · 2 + s_{i+1}     (k ∈ {0, ..., 7})
s_i(t+1) = bit k of R                     (i.e., (R >> k) & 1)

where:
  s_i(t)    — state of cell i at generation t (0 or 1)
  R         — Wolfram rule number (0-255), encodes the 8-bit lookup table
  k         — index into the lookup table, computed from the 3-cell neighborhood
```

Successive generations are rendered top to bottom. The initial row is either a
single center cell or a random binary sequence.

**Controls**: `W` to enter, `+/-` change rule number, `P/N` jump to notable
rules, `Space` run/pause, `R` randomize initial row.

**Source**: Stephen Wolfram, "Statistical Mechanics of Cellular Automata,"
*Reviews of Modern Physics*, vol. 55, no. 3, pp. 601-644, 1983.
[doi.org/10.1103/RevModPhys.55.601](https://doi.org/10.1103/RevModPhys.55.601)
| Also: Stephen Wolfram, *A New Kind of Science*, Wolfram Media, 2002.
[wolframscience.com](https://www.wolframscience.com/nks/)

---

### Lenia — Continuous Cellular Automaton

**Background.**
Lenia, introduced by Bert Wang-Chak Chan in 2019, generalizes discrete
cellular automata into continuous space. Instead of binary alive/dead states,
each cell holds a float value in [0, 1]. A smooth Gaussian kernel replaces the
discrete neighbor count, and a continuous growth function replaces the
birth/survival lookup.

This produces lifelike "creatures" — self-organizing, self-moving blobs that
resemble microorganisms.

**Formulation.**
Let `A(x, t) ∈ [0, 1]` be the cell state. Define a ring-shaped kernel `K`
with radius `R` using a Gaussian bell:

```
K(r) = exp(-(r - μ_K)² / (2σ_K²))     for 0 < r ≤ 1, where r = dist/R
K is normalized: K ← K / Σ K

where:
  A(x, t) ∈ [0, 1]  — continuous cell state ("aliveness") at position x, time t
  R                  — kernel radius in cells
  r                  — normalized distance from center (dist/R)
  μ_K, σ_K           — kernel bell curve center and width (shape the ring)
  K(r)               — kernel weight at normalized distance r
```

The potential field is the weighted neighborhood sum:

```
U(x, t) = Σ_{y ∈ N_R(x)} K(|x - y| / R) · A(y, t)

where:
  U(x, t)   — potential (weighted neighborhood activity) at cell x
  N_R(x)    — set of cells within radius R of x
```

The growth function maps potential to a state change rate:

```
G(u) = 2 · exp(-(u - μ_G)² / (2σ_G²)) - 1     (range: [-1, 1])

where:
  μ_G, σ_G  — growth function center and width (define the "ideal" potential)
  G > 0     — cell grows (state increases)
  G < 0     — cell decays (state decreases)
```

The state update with timestep `dt = 1/T`:

```
A(x, t+1) = clamp(A(x, t) + dt · G(U(x, t)),  0, 1)

where:
  T          — integration period (higher T = smaller steps = smoother dynamics)
  dt = 1/T   — timestep per generation
  clamp      — restrict result to [0, 1]
```

**Preset parameters:**

| Preset | R | T | μ_K | σ_K | μ_G | σ_G |
|--------|---|---|-----|-----|-----|-----|
| Orbium | 13 | 10 | 0.5 | 0.15 | 0.15 | 0.015 |
| Geminium | 10 | 10 | 0.5 | 0.15 | 0.14 | 0.014 |
| Hydrogeminium | 12 | 10 | 0.5 | 0.15 | 0.16 | 0.016 |
| Smooth Life | 8 | 5 | 0.5 | 0.20 | 0.26 | 0.036 |

**Controls**: `L` to enter, `Space` run/pause, `P/N` cycle presets, `R`
randomize, `+/-` speed.

**Source**: Bert Wang-Chak Chan, "Lenia: Biology of Artificial Life,"
*Complex Systems*, vol. 28, no. 3, pp. 251-286, 2019.
[arxiv.org/abs/1812.05433](https://arxiv.org/abs/1812.05433)

---

### Multi-State Automata (Brian's Brain, Wireworld, Langton's Ant)

**Background.**
These three automata use more than two cell states, enabling richer dynamics.

**Brian's Brain formulation.**
Three states: `{OFF, ON, DYING}`. Let `n_ON(r,c)` be the count of ON
neighbors in the Moore neighborhood.

```
ON      → DYING
DYING   → OFF
OFF     → ON    if n_ON(r,c) = 2
OFF     → OFF   otherwise
```

No stable structures are possible — every ON cell dies after one generation.

**Wireworld formulation.**
Four states: `{EMPTY, CONDUCTOR, HEAD, TAIL}`. Let `n_H(r,c)` be the count
of HEAD neighbors.

```
HEAD       → TAIL
TAIL       → CONDUCTOR
CONDUCTOR  → HEAD       if n_H(r,c) ∈ {1, 2}
CONDUCTOR  → CONDUCTOR  otherwise
EMPTY      → EMPTY
```

This suffices to simulate digital logic gates and full computers.

**Langton's Ant formulation.**
An ant at position `(r, c)` with direction `d ∈ {UP, RIGHT, DOWN, LEFT}` on a
binary grid `g(r,c) ∈ {WHITE, BLACK}`:

```
if g(r,c) = WHITE:
    d ← turn_right(d)
    g(r,c) ← BLACK
else:
    d ← turn_left(d)
    g(r,c) ← WHITE
(r,c) ← (r,c) + Δ(d)

where Δ = {UP: (-1,0), RIGHT: (0,1), DOWN: (1,0), LEFT: (0,-1)}
```

After ~10,000 chaotic steps, the ant invariably builds a periodic diagonal
"highway."

**Controls**: `Shift+X` to enter, `P/N` switch between automaton types,
`Space` run/pause, `Enter` toggle cells.

**Sources**:
Brian's Brain & Wireworld: A. K. Dewdney, "Computer Recreations: The cellular
automata programs that create Wireworld, Rugworld and other diversions,"
*Scientific American*, vol. 262, pp. 146-149, January 1990.
[mathworld.wolfram.com/WireWorld.html](https://mathworld.wolfram.com/WireWorld.html)
| Langton's Ant: Christopher G. Langton, "Studying Artificial Life with
Cellular Automata," *Physica D*, vol. 22, nos. 1-3, pp. 120-149, 1986.
[doi.org/10.1016/0167-2789(86)90237-X](https://doi.org/10.1016/0167-2789(86)90237-X)

---

### Neural Cellular Automata

**Background.**
Neural Cellular Automata (NCA), popularized by Mordvintsev et al. at Google
in 2020, replace hand-crafted rules with learned neural networks. Each cell
carries multiple continuous channels. At each step, cells perceive their
neighborhood through Sobel filters, process the result through a small MLP,
and update their state — mimicking biological morphogenesis.

**Formulation.**
Let `s(x) ∈ R^C` be the `C`-channel state vector at cell `x` (default
`C = 4`). Perception uses three 3x3 convolution kernels per channel:

```
         [-1 0 1]          [-1 -2 -1]          [0 0 0]
S_x =    [-2 0 2] / 8     S_y = [ 0  0  0] / 8     I = [0 1 0]
         [-1 0 1]          [ 1  2  1]          [0 0 0]
```

For each channel `c`, compute `(I * s_c, S_x * s_c, S_y * s_c)` to form a
perception vector `p ∈ R^{3C}`. The MLP update:

```
h = σ(W₁ · p + b₁)           (hidden layer)
δ = tanh(W₂ · h + b₂)        (output layer)
s(x) ← clamp(s(x) + 0.1 · δ + ξ,  -1, 1)

where:
  s(x) ∈ R^C     — C-channel state vector at cell x (default C = 4)
  S_x, S_y       — Sobel edge-detection kernels (horizontal and vertical gradients)
  I              — identity kernel (passes through the cell's own state)
  p ∈ R^{3C}     — perception vector (3 filter responses × C channels)
  W₁, b₁         — hidden layer weights and biases (size: 3C × hidden_size)
  W₂, b₂         — output layer weights and biases (size: hidden_size × C)
  σ              — activation function (sigmoid, tanh, or relu, per preset)
  δ ∈ R^C        — proposed state change vector
  ξ              — uniform noise ~ U(-noise/2, noise/2) for stochastic variation
  0.1            — learning rate (scales the state update magnitude)
```

Alive masking: if channel 0 of state `s_0(x) < 0.1` and no neighbor has
`s_0 ≥ 0.1`, set `s(x) ← 0` (dead cells with no alive neighbors stay dead).
Stochastic update: each cell skips its update with probability
`1 - update_rate`.

**Preset parameters:**

| Preset | update_rate | noise | activation | hidden_size |
|--------|-------------|-------|------------|-------------|
| grow | 0.15 | 0.05 | sigmoid | 16 |
| persist | 0.10 | 0.02 | tanh | 16 |
| morphogenesis | 0.08 | 0.12 | relu | 16 |
| regenerate | 0.12 | 0.04 | sigmoid | 16 |

**Controls**: `Shift+N` to enter, `Space` run/pause, `X` paint cells, `E`
erase, `P/N` presets, `+/-` speed.

**Source**: Alexander Mordvintsev, Ettore Randazzo, Eyvind Niklasson, and
Michael Levin, "Growing Neural Cellular Automata," *Distill*, 2020.
[distill.pub/2020/growing-ca](https://distill.pub/2020/growing-ca/)

---

### Abelian Sandpile

**Background.**
The Abelian Sandpile Model, introduced by Bak, Tang, and Wiesenfeld in 1987,
is the canonical example of self-organized criticality. The system naturally
evolves to a critical state where avalanches of all sizes occur, following a
power-law distribution.

**Formulation.**
Let `z(r, c) ∈ Z≥0` be the number of grains at cell `(r, c)`. Define a
threshold `θ` (default `θ = 4`). A cell topples when `z(r,c) ≥ θ`:

```
z(r, c) ← z(r, c) - θ · ⌊z(r, c) / θ⌋
z(r±1, c) ← z(r±1, c) + ⌊z(r, c) / θ⌋
z(r, c±1) ← z(r, c±1) + ⌊z(r, c) / θ⌋

where:
  z(r, c) ∈ Z≥0   — number of sand grains at cell (r, c)
  θ                — toppling threshold (default 4; grains redistribute when z ≥ θ)
  ⌊z/θ⌋           — number of excess units to distribute to each of 4 neighbors
```

Grains that would leave the grid boundary are lost (open boundary). Toppling
repeats until no cell exceeds the threshold. The "identity" preset starts from
`z(r,c) = θ - 1` everywhere and relaxes, producing fractal patterns.

**Presets**: center-drop, random-rain, identity, multi-source, high-threshold
(`θ = 8`).

**Controls**: `Shift+J` to enter, `Space` run/pause, `P/N` presets,
`1-4` drop mode, cursor to click-drop grains.

**Source**: Per Bak, Chao Tang, and Kurt Wiesenfeld, "Self-organized
criticality: An explanation of the 1/f noise," *Physical Review Letters*,
vol. 59, no. 4, pp. 381-384, 1987.
[doi.org/10.1103/PhysRevLett.59.381](https://doi.org/10.1103/PhysRevLett.59.381)

---

## Physics

### Falling Sand

**Background.**
Falling sand games simulate granular material physics with simple per-particle
rules. The genre originated as a Java applet on the Japanese Dofi-Blog in 2005.

**Formulation.**
The grid `g(r, c) ∈ {EMPTY, SAND, WATER, FIRE, STONE, PLANT}` is updated
bottom-to-top with randomized column order. Each material follows local rules:

```
SAND:   if g(r+1, c) ∈ {EMPTY, WATER} → swap(r,c, r+1,c)
        else try diagonal: swap(r,c, r+1,c±1) if target ∈ {EMPTY, WATER}

WATER:  if g(r+1, c) = EMPTY → swap down
        else try diagonal down, then spread horizontally

FIRE:   with P=0.08 → decay to EMPTY
        ignite adjacent PLANT with P=0.4
        rise: swap(r,c, r-1,c) if EMPTY above
        trapped fire dies with P=0.2

PLANT:  grow into adjacent EMPTY with P=0.005

STONE:  immobile (no update)
```

**Materials**: Sand, Water, Fire, Stone, Plant.

**Controls**: `F` to enter, `Space` run/pause, `P/N` cycle materials,
`+/-` brush size, cursor to place material.

**Source**: Falling sand game history and variants.
[handwiki.org/wiki/Software:Falling-sand_game](https://handwiki.org/wiki/Software:Falling-sand_game)

---

### Reaction-Diffusion (Gray-Scott Model)

**Background.**
The Gray-Scott model describes two chemical species U and V that react and
diffuse on a surface, producing patterns predicted by Turing's 1952
morphogenesis theory.

**Formulation.**
Let `u(x, t)` and `v(x, t)` be the concentrations of species U and V. The
governing PDEs:

```
∂u/∂t = D_u ∇²u - uv² + f(1 - u)
∂v/∂t = D_v ∇²v + uv² - (f + k)v

where:
  u(x, t), v(x, t) ∈ [0,1] — concentrations of chemical species U and V
  D_u = 0.21     — diffusion rate of U (how fast U spreads spatially)
  D_v = 0.105    — diffusion rate of V (V diffuses more slowly than U)
  f              — feed rate (replenishes U from a reservoir, removes V)
  k              — kill rate (rate at which V decays to inert product)
  ∇²             — Laplacian operator (measures local concentration curvature)
  -uv²           — reaction term: U is consumed when it meets two V molecules
  +uv²           — reaction term: V is produced autocatalytically
```

The discrete update (4 substeps per tick, `δt = 0.25`) uses the 5-point
Laplacian stencil:

```
∇²u ≈ u(r-1,c) + u(r+1,c) + u(r,c-1) + u(r,c+1) - 4u(r,c)

u ← clamp(u + δt · (D_u · ∇²u - uv² + f(1-u)),  0, 1)
v ← clamp(v + δt · (D_v · ∇²v + uv² - (f+k)v),  0, 1)

where:
  δt = 0.25  — substep size (4 substeps per visible tick for numerical stability)
  clamp      — restrict result to [0, 1]
```

**Preset parameters (f, k):**

| Preset | f | k | Pattern |
|--------|-------|-------|---------|
| Mitosis | 0.0367 | 0.0649 | Self-replicating spots |
| Coral | 0.0545 | 0.062 | Branching growth |
| Maze | 0.029 | 0.057 | Labyrinthine stripes |
| Solitons | 0.03 | 0.06 | Traveling pulses |
| Worms | 0.078 | 0.061 | Worm-like structures |
| Bubbles | 0.012 | 0.05 | Expanding rings |
| Waves | 0.014 | 0.054 | Oscillating waves |

**Controls**: `Shift+R` to enter, `Space` run/pause, `P/N` presets, `Enter`
drop chemical seed, `+/-` speed.

**Sources**: P. Gray and S. K. Scott, "Autocatalytic reactions in the
isothermal, continuous stirred tank reactor," *Chemical Engineering Science*,
vol. 39, no. 6, pp. 1087-1097, 1984.
[doi.org/10.1016/0009-2509(84)87017-7](https://doi.org/10.1016/0009-2509(84)87017-7)
| Alan M. Turing, "The Chemical Basis of Morphogenesis," *Philosophical
Transactions of the Royal Society B*, vol. 237, no. 641, pp. 37-72, 1952.
[doi.org/10.1098/rstb.1952.0012](https://doi.org/10.1098/rstb.1952.0012)

---

### Fluid Dynamics (Lattice Boltzmann Method)

**Background.**
The Lattice Boltzmann Method (LBM) simulates fluid flow by tracking
probability distributions of particles on a lattice rather than solving the
Navier-Stokes equations directly.

**Formulation.**
The D2Q9 model uses 9 discrete velocity directions `e_i` with weights `w_i`:

```
e_0 = (0,0)     w_0 = 4/9       (rest)
e_{1..4}         w_{1..4} = 1/9  (cardinal: E, N, W, S)
e_{5..8}         w_{5..8} = 1/36 (diagonal: NE, NW, SW, SE)
```

Each cell stores 9 distribution functions `f_i(x, t)`. Macroscopic quantities:

```
ρ = Σ_i f_i                    (density)
ρu = Σ_i e_i f_i               (momentum)

where:
  f_i(x, t)  — probability of finding a particle at cell x with velocity e_i
  ρ           — macroscopic fluid density at cell x
  u = (u_x, u_y) — macroscopic fluid velocity at cell x
  e_i         — discrete velocity vector for direction i
  w_i         — lattice weight for direction i
```

The equilibrium distribution (Maxwell-Boltzmann discretized to the lattice):

```
f_i^eq = w_i ρ (1 + 3(e_i · u) + 9/2 (e_i · u)² - 3/2 |u|²)

where:
  f_i^eq  — equilibrium distribution (what f_i relaxes toward)
  e_i · u — dot product of lattice velocity with fluid velocity
```

BGK collision and streaming:

```
f_i(x + e_i, t+1) = f_i(x, t) + ω(f_i^eq - f_i)

where:
  ω = 1/τ      — relaxation frequency (controls how fast f_i → f_i^eq)
  τ = 3ν + 0.5 — relaxation time
  ν             — kinematic viscosity of the fluid
```

Boundary conditions: bounce-back on obstacles (`f_{opp(i)} ← f_i`, reflecting
particles back), Zou-He inlet with prescribed velocity, zero-gradient outlet.

**Preset parameters:**

| Preset | ν | u_inlet | Behavior |
|--------|------|---------|----------|
| laminar | 0.08 | 0.08 | Smooth flow |
| moderate | 0.04 | 0.12 | Moderate Re |
| turbulent | 0.02 | 0.15 | Vortex streets |
| viscous | 0.15 | 0.06 | Slow, thick flow |
| fast | 0.01 | 0.18 | Chaotic vortices |

**Controls**: `Shift+D` to enter, `Space` run/pause, `Enter` paint obstacles,
`+/-` viscosity, `D/F` speed, `C` clear obstacles.

**Source**: G. R. McNamara and G. Zanetti, "Use of the Boltzmann Equation to
Simulate Lattice-Gas Automata," *Physical Review Letters*, vol. 61, no. 20,
pp. 2332-2335, 1988.
[pubmed.ncbi.nlm.nih.gov/10039085](https://pubmed.ncbi.nlm.nih.gov/10039085/)

---

### Ising Model

**Background.**
The 2D Ising model, proposed by Wilhelm Lenz in 1920 and solved exactly by
Lars Onsager in 1944, is the most studied model in statistical mechanics.

**Formulation.**
A square lattice of spins `s_i ∈ {+1, -1}` with Hamiltonian:

```
H = -J Σ_{<i,j>} s_i s_j

where:
  H           — Hamiltonian (total energy of the spin configuration)
  s_i ∈ {+1, -1} — spin at lattice site i
  J           — coupling constant (J > 0: ferromagnetic, J < 0: antiferromagnetic)
  <i,j>       — sum over all nearest-neighbor pairs (each pair counted once)
```

The Metropolis-Hastings algorithm proposes single spin flips. For a flip at
site `i`, the energy change is:

```
ΔE = 2J s_i Σ_{j ∈ N(i)} s_j

where:
  ΔE     — energy change if spin s_i is flipped
  N(i)   — the 4 nearest neighbors of site i (periodic boundary conditions)
```

The flip is accepted with probability:

```
P(accept) = min(1, exp(-ΔE / k_B T))

where:
  k_B = 1   — Boltzmann constant (set to 1 in simulation units)
  T          — temperature (controls thermal fluctuations; higher T = more random)
```

Observables:

```
Magnetization:  M = (1/N) Σ_i s_i          (average spin; M ≈ ±1 when ordered)
Energy density: E = -(J/N) Σ_{<i,j>} s_i s_j   (average energy per site)

where:
  N — total number of lattice sites
```

Critical temperature: `T_c = 2J / ln(1 + √2) ≈ 2.269 J/k_B` — the exact
Onsager solution for the 2D square lattice phase transition.

**Preset parameters:**

| Preset | T | J | Phase |
|--------|------|------|-------|
| cold | 0.5 | 1.0 | Deep ferromagnetic |
| cool | 1.5 | 1.0 | Large domains |
| critical | 2.269 | 1.0 | Phase transition |
| warm | 3.0 | 1.0 | Paramagnetic |
| hot | 5.0 | 1.0 | Fully disordered |
| anti-ferro | 1.5 | -1.0 | Checkerboard order |

**Controls**: `Shift+I` to enter, `Space` run/pause, `,/.` adjust
temperature, `P/N` presets.

**Source**: Lars Onsager, "Crystal Statistics. I. A Two-Dimensional Model with
an Order-Disorder Transition," *Physical Review*, vol. 65, nos. 3-4,
pp. 117-149, 1944.
[ui.adsabs.harvard.edu](https://ui.adsabs.harvard.edu/abs/1944PhRv...65..117O/abstract)

---

### Magnetic Field (Electromagnetic Particles)

**Background.**
Charged particles in electromagnetic fields obey the Lorentz force law. The
simulation integrates particle trajectories using the Boris method, a
symplectic integrator that exactly preserves circular orbit geometry.

**Formulation.**
The Lorentz force on a particle with charge `q`, velocity `v`, in fields
`B` and `E`:

```
F = q(v × B + E)

where:
  F        — force on the particle (Lorentz force)
  q        — particle charge (+1 or -1)
  v        — particle velocity vector
  B        — magnetic field vector (B_x, B_y, B_z)
  E        — electric field vector (E_x, E_y)
  v × B    — cross product (deflects particle perpendicular to both v and B)
```

The Boris integrator (with `δt = 0.15`) splits the update into three phases:

```
1. Half E-field kick:     v⁻ = v^n + (qδt/2) E

2. B-field rotation:      t = (qδt/2) B
                          v' = v⁻ + v⁻ × t
                          s = 2t / (1 + |t|²)
                          v⁺ = v⁻ + v' × s

3. Half E-field kick:     v^{n+1} = v⁺ + (qδt/2) E

Position update:          x^{n+1} = x^n + v^{n+1} · δt

where:
  v^n, v^{n+1}  — velocity at timestep n and n+1
  x^n, x^{n+1}  — position at timestep n and n+1
  δt = 0.15      — integration timestep
  v⁻, v⁺         — intermediate velocities (before/after B-field rotation)
  t              — rotation half-angle vector (from B-field)
  s              — rotation scaling vector (ensures exact circular orbit geometry)
```

Speed cap: `|v| ≤ 4.0`. Reflective boundary conditions.

In magnetic bottle mode, the field strengthens at the boundaries:

```
B_z ← B_z · (1 + 3(2y/H - 1)⁴)
B_x ← B_x + 0.3 · (2x/W - 1) · (2y/H - 1)²

where:
  H, W  — grid height and width
  y, x  — particle position (normalized to [0, H] and [0, W])
```

**Presets**: cyclotron, magnetic-bottle, exb-drift, hall-effect, aurora.

**Controls**: `Shift+G` to enter, `Space` run/pause, `+/-` B-field strength,
`E` toggle E-field, `P/N` presets.

**Source**: J. P. Boris, "Relativistic Plasma Simulation — Optimization of a
Hybrid Code," in *Proceedings of the Fourth Conference on Numerical Simulation
of Plasmas*, pp. 3-67, Naval Research Laboratory, Washington, D.C., 1970.
[particleincell.com (tutorial)](https://www.particleincell.com/2011/vxb-rotation/)

---

### N-Body Gravity

**Background.**
The gravitational N-body problem — computing the motion of N masses under
mutual gravitational attraction — is one of the oldest problems in physics.
For N ≥ 3 there is no general closed-form solution and the system is
typically chaotic.

**Formulation.**
Pairwise gravitational force with softening:

```
F_ij = G m_i m_j / (|r_ij|² + ε²)
a_i = Σ_{j≠i} G m_j (r_j - r_i) / (|r_ij|² + ε²)^{3/2}

where:
  F_ij      — gravitational force magnitude between bodies i and j
  G = 0.5   — gravitational constant (simulation units)
  m_i, m_j  — masses of the two bodies
  r_ij      — displacement vector from body i to body j
  |r_ij|    — distance between bodies i and j
  ε = 1.5   — softening length (prevents force singularity at r → 0)
  a_i       — acceleration of body i (sum of gravitational pulls from all others)
```

Velocity-Verlet integration (`δt = 0.08`):

```
v_i ← v_i + a_i · δt
x_i ← x_i + v_i · δt

where:
  v_i   — velocity of body i
  x_i   — position of body i
  δt    — integration timestep
```

Speed cap: `|v| ≤ 5.0`. Collision merging when `|r_ij| < (R_i + R_j) · d_merge`:

```
m_new = m_i + m_j
v_new = (m_i v_i + m_j v_j) / m_new     (momentum conservation)
x_new = (m_i x_i + m_j x_j) / m_new     (center of mass)

where:
  d_merge = 1.0             — merge distance multiplier
  R_i = max(0.3, m_i^{1/3} · 0.3)  — visual radius of body i (scales with mass)
```

Body classification: mass ≥ 30 → star, mass ≥ 8 → planet, else asteroid.

**Presets**: binary-star, solar-system, three-body, asteroid-belt, figure-eight.

**Controls**: `Shift+K` to enter, `Space` run/pause, `+/-` gravity strength,
`A` add planet, `Shift+A` add star, `P/N` presets.

**Source**: Alain Chenciner and Richard Montgomery, "A Remarkable Periodic
Solution of the Three-Body Problem in the Case of Equal Masses," *Annals of
Mathematics*, Second Series, vol. 152, no. 3, pp. 881-901, 2000.
[arxiv.org/abs/math/0011268](https://arxiv.org/abs/math/0011268)

---

### Hydraulic Erosion

**Background.**
Hydraulic erosion shapes landscapes through rainfall, water flow, sediment
transport, and deposition.

**Formulation.**
Five scalar fields: terrain height `T(r,c)`, water depth `W(r,c)`, sediment
concentration `S(r,c)`, velocity `V(r,c)`, cumulative erosion. Each tick:

```
1. Rainfall:     W(r,c) += rain_rate · (1 + ξ)     with P=0.3, ξ ~ U(0,1)

2. Flow routing:  Find lowest neighbor n* by effective height T + W.
                  Δh = (T(r,c) + W(r,c)) - (T(n*) + W(n*))
                  flow = min(W(r,c), Δh/2)

3. Velocity:     V_new = min(√(V² + Δh · g), 3.0)

4. Capacity:     C = max(Δh, Δh_min) · V_new · κ · flow

5. Erosion/Deposition:
   if S < C:     erode = min((C - S) · α_e,  T/2)
                 T -= erode,  S += erode
   else:         deposit = (S - C) · α_d
                 T += deposit,  S -= deposit

6. Transport:    Move water and proportional sediment to n*.

7. Evaporation:  W ← W · (1 - evap_rate)

where:
  T(r,c)    — terrain height at cell (r,c)
  W(r,c)    — water depth at cell (r,c)
  S(r,c)    — sediment concentration suspended in water
  V(r,c)    — water flow velocity
  n*        — lowest neighboring cell (steepest descent direction)
  Δh        — height difference to lowest neighbor (drives flow)
  flow      — amount of water transferred to neighbor
  g         — gravity (controls how much Δh accelerates water)
  C         — sediment carrying capacity (how much sediment the water can hold)
  κ         — sediment capacity coefficient (preset-dependent)
  Δh_min    — minimum slope for capacity calculation (prevents zero capacity on flats)
  α_e       — erosion rate (fraction of capacity deficit eroded per tick)
  α_d       — deposition rate (fraction of excess sediment deposited per tick)
  ξ         — uniform random noise in [0, 1]
  evap_rate — evaporation rate (fraction of water lost per tick)
```

**Presets**: gentle-hills, mountain-range, canyon-carver, river-delta,
volcanic — each with different `rain_rate`, `α_e`, `α_d`, `κ`, `g`.

**Controls**: `Shift+Y` to enter, `Space` run/pause, `+/-` rain rate,
`P/N` presets, `F/D` speed.

**Source**: F. Kenton Musgrave, Craig E. Kolb, and Robert S. Mace, "The
Synthesis and Rendering of Eroded Fractal Terrains," *Computer Graphics
(SIGGRAPH '89 Proceedings)*, vol. 23, no. 3, pp. 41-50, 1989.
[history.siggraph.org](https://history.siggraph.org/learning/the-synthesis-and-rendering-of-eroded-fractal-terrains-by-musgrave-kolb-and-mace/)

---

### Diffusion-Limited Aggregation (DLA)

**Background.**
DLA, introduced by Witten and Sander in 1981, models crystal growth by random
deposition. The resulting structures are fractals with dimension ~1.7.

**Formulation.**
A binary grid `g(r,c) ∈ {0, crystal}` and a set of random walkers `W`. Each
tick, for each walker `w = (r, c)`:

```
1. Random step:  (r', c') = (r + δr, c + δc)    δr, δc ∈ {-1, 0, 1}
2. Boundary:     If out of bounds, respawn at random boundary position.
3. Sticking:     If any von Neumann neighbor of (r', c') is crystal
                 AND random() < stickiness:
                     g(r', c') ← crystal_order++
                     Remove w from walker set
4. Otherwise:    (r, c) ← (r', c')
```

**Preset parameters:**

| Preset | stickiness | walkers | walkers/tick |
|--------|------------|---------|--------------|
| center-seed | 1.0 | 800 | 50 |
| sparse-tendrils | 0.3 | 600 | 40 |
| coral | 0.7 | 1200 | 80 |
| lightning | 0.5 | 800 | 50 |

**Controls**: `Shift+L` to enter, `Space` run/pause, cursor to place seeds,
`P/N` presets.

**Source**: T. A. Witten Jr. and L. M. Sander, "Diffusion-Limited
Aggregation, a Kinetic Critical Phenomenon," *Physical Review Letters*,
vol. 47, no. 19, pp. 1400-1403, 1981.
[ui.adsabs.harvard.edu](https://ui.adsabs.harvard.edu/abs/1981PhRvL..47.1400W/abstract)

---

### Double Pendulum

**Background.**
A double pendulum is the simplest mechanical system that exhibits
deterministic chaos. The simulation runs two pendulums with infinitesimal
initial angle differences to visualize divergence.

**Formulation.**
Two rigid rods of lengths `L₁, L₂` and bob masses `m₁, m₂` under gravity
`g = 9.81 m/s²`. The state is `(θ₁, θ₂, ω₁, ω₂)`. The equations of motion
derived from the Lagrangian:

```
α₁ = [-g(2m₁+m₂)sin θ₁ - m₂g sin(θ₁-2θ₂)
       - 2 sin δ · m₂(ω₂²L₂ + ω₁²L₁ cos δ)]
      / [L₁(2m₁ + m₂ - m₂ cos 2δ)]

α₂ = [2 sin δ · (ω₁²L₁(m₁+m₂) + g(m₁+m₂)cos θ₁ + ω₂²L₂m₂ cos δ)]
      / [L₂(2m₁ + m₂ - m₂ cos 2δ)]

where:
  θ₁, θ₂     — angles of the upper and lower rods from vertical (radians)
  ω₁, ω₂     — angular velocities (dθ₁/dt, dθ₂/dt)
  α₁, α₂     — angular accelerations (dω₁/dt, dω₂/dt)
  δ = θ₁ - θ₂ — angle difference between the two rods
  L₁, L₂     — rod lengths (meters)
  m₁, m₂     — bob masses (kg)
  g = 9.81    — gravitational acceleration (m/s²)
  γ           — damping coefficient (optional; α₁ -= γω₁, α₂ -= γω₂)
```

Integration uses 4th-order Runge-Kutta with `δt = 0.002 s`. Bob positions in
Cartesian coordinates:

```
x₁ = L₁ sin θ₁           y₁ = L₁ cos θ₁
x₂ = x₁ + L₂ sin θ₂     y₂ = y₁ + L₂ cos θ₂
```

Pendulum B starts with `θ₁_B = θ₁_A + Δ`, `θ₂_B = θ₂_A + Δ` where
`Δ = 0.001 rad` — an infinitesimal perturbation. The divergence
`|Δθ₁| + |Δθ₂|` grows exponentially, confirming a positive Lyapunov exponent
(characteristic of deterministic chaos).

**Presets**: classic, heavy-light, long-short, high-energy, damped, symmetric.

**Controls**: `Shift+O` to enter, `Space` pause, `T` toggle trail, `D`
toggle damping, `+/-` initial angle offset, `R` reset, `P/N` presets.

**Source**: Tomasz Stachowiak and Toshio Okada, "A Numerical Analysis of Chaos
in the Double Pendulum," *Chaos, Solitons & Fractals*, vol. 29, no. 2,
pp. 417-422, 2006.
[hal.science/hal-01389907](https://hal.science/hal-01389907)

---

## Biology

### Particle Life

**Background.**
Particle Life, explored by Jeffrey Ventrella, simulates emergent life-like
behavior from simple attraction and repulsion rules between colored particle
types. Different random interaction matrices produce wildly different
"chemistries."

**Formulation.**
`N` particles of `K = 6` types, each with position `x_i ∈ R²` and velocity
`v_i ∈ R²`. The interaction matrix `A[k₁][k₂] ∈ [-1, 1]` defines
attraction/repulsion between types. The piecewise-linear force between
particles `i, j` at distance `r`:

```
         ⎧ r/(β·r_max) - 1              if r < β·r_max   (universal repulsion zone)
F(r,a) = ⎨ a · 2t          if t < 0.5   (rising attraction/repulsion)
         ⎩ a · 2(1 - t)    if t ≥ 0.5   (falling attraction/repulsion)
         0                               if r ≥ r_max     (no interaction)

where:
  r           — distance between two particles
  a ∈ [-1, 1] — interaction strength from matrix A[k_i][k_j] (+ attracts, - repels)
  t = (r - β·r_max) / (r_max - β·r_max) — normalized position in interaction zone
  r_max = 80  — maximum interaction radius (beyond this, particles don't interact)
  β = 0.3     — repulsion fraction (inner 30% of r_max is always repulsive)
  F(r,a)      — force magnitude (positive = repulsion, negative = attraction)
```

The velocity update (with damping):

```
v_i ← v_i · (1 - friction) + (Σ_j F(|r_ij|, A[k_i][k_j]) · r̂_ij · force_scale) · δt
x_i ← x_i + v_i · δt     (toroidal wrap)

where:
  v_i          — velocity of particle i
  x_i          — position of particle i
  r̂_ij         — unit direction vector from particle i to j
  A[k_i][k_j]  — interaction matrix entry for particle types k_i and k_j
  force_scale = 5.0   — global force multiplier
  friction = 0.05     — velocity damping per tick (prevents runaway speeds)
  δt = 0.02           — integration timestep
  K = 6               — number of particle types
  N                   — total number of particles
```

**Controls**: `Shift+P` to enter, `Space` run/pause, `R` randomize
interaction matrix, `P/N` presets, `+/-` speed.

**Source**: Jeffrey Ventrella, *Clusters* (interactive particle life
simulation).
[ventrella.com/Clusters](https://ventrella.com/Clusters/)

---

### Wa-Tor Ecosystem

**Background.**
Wa-Tor, created by Alexander Dewdney in 1984, simulates predator-prey
dynamics on a toroidal ocean, producing Lotka-Volterra oscillations.

**Formulation.**
A toroidal grid of cells, each either EMPTY, FISH, or SHARK. Each entity has
an `age` counter; sharks also have an `energy` counter. Per tick (randomized
order):

```
FISH:
    age += 1
    Move to random empty von Neumann neighbor.
    if age ≥ breed_fish (default 3):
        Leave offspring at old position (age = 0).

SHARK:
    age += 1,  energy -= 1
    if energy ≤ 0: die (cell → EMPTY).
    if adjacent fish exists:
        Eat it (move there), energy += starve_energy (default 4).
    else:
        Move to random empty neighbor.
    if age ≥ breed_shark (default 8):
        Leave offspring (age = 0, energy = starve_energy).
```

The population dynamics approximate the continuous Lotka-Volterra system:
`dx/dt = αx - βxy`, `dy/dt = δxy - γy`, where `x` = prey population,
`y` = predator population, `α` = prey birth rate, `β` = predation rate,
`δ` = predator growth from feeding, `γ` = predator death rate.

**Controls**: `Shift+E` to enter, `Space` run/pause, `+/-` speed,
`P/N` presets.

**Source**: A. K. Dewdney, "Computer Recreations," *Scientific American*,
vol. 251, no. 6, pp. 14-22, December 1984.
[doi.org/10.1038/scientificamerican1284-14](https://doi.org/10.1038/scientificamerican1284-14)

---

### Physarum Slime Mold

**Background.**
Physarum polycephalum is a slime mold that solves optimization problems
without a brain, producing networks resembling highway maps and vascular
systems.

**Formulation.**
`N` agents, each with position `(x, y)` and heading `φ`, on a trail field
`T(r, c) ∈ R≥0`. Per tick:

```
1. Sense:    s_L = T(x + d·cos(φ - θ_s), y + d·sin(φ - θ_s))
             s_C = T(x + d·cos(φ),        y + d·sin(φ))
             s_R = T(x + d·cos(φ + θ_s), y + d·sin(φ + θ_s))

2. Rotate:   if s_C ≥ s_L and s_C ≥ s_R:  φ unchanged  (straight)
             elif s_L > s_R:               φ -= θ_turn
             elif s_R > s_L:               φ += θ_turn
             else (s_L = s_R > s_C):       φ ± θ_turn (random)

3. Move:     x ← (x + cos φ) mod W
             y ← (y + sin φ) mod H

4. Deposit:  T(⌊y⌋, ⌊x⌋) += deposit_amount

5. Diffuse:  T_new(r,c) = ((1-k_d)·T(r,c) + k_d·avg₃ₓ₃(T)) · (1 - decay)

where:
  (x, y)         — agent position (continuous coordinates)
  φ               — agent heading angle (radians)
  T(r, c)         — pheromone trail intensity at grid cell (r, c)
  s_L, s_C, s_R   — trail readings at left, center, and right sensor positions
  d               — sensor distance (how far ahead the agent looks)
  θ_s             — sensor angle (angular offset for left/right sensors from heading)
  θ_turn          — turn angle (how much the agent rotates per step)
  deposit_amount  — pheromone deposited by each agent per step
  k_d             — diffusion kernel weight (blend ratio: 0 = no diffusion, 1 = full blur)
  avg₃ₓ₃(T)      — mean of 3×3 neighborhood (smooths the trail field)
  decay           — trail decay rate per tick (fraction of trail lost)
  W, H            — grid width and height (toroidal boundary)
```

**Presets**: network, ring, maze-solver, tendrils, dense — each with different
`d`, `θ_s`, `θ_turn`, `deposit_amount`, `k_d`, `decay`.

**Controls**: `Shift+S` to enter, `Space` run/pause, `P/N` presets,
`+/-` speed.

**Sources**: Jeff Jones, "Characteristics of Pattern Formation and Evolution
in Approximations of Physarum Transport Networks," *Artificial Life*, vol. 16,
no. 2, pp. 127-153, 2010.
[doi.org/10.1162/artl.2010.16.2.16202](https://doi.org/10.1162/artl.2010.16.2.16202)
| Atsushi Tero et al., "Rules for Biologically Inspired Adaptive Network
Design," *Science*, vol. 327, no. 5964, pp. 439-442, 2010.
[doi.org/10.1126/science.1177894](https://doi.org/10.1126/science.1177894)

---

### Boids Flocking

**Background.**
Boids, created by Craig Reynolds in 1987, demonstrates how realistic flocking
behavior emerges from three simple local steering rules.

**Formulation.**
Each boid has position `x_i ∈ R²` and velocity `v_i ∈ R²`. Three steering
forces are computed from neighbors within respective perception radii:

```
Separation:  f_sep = -Σ_{j: |r_ij|<R_s} r̂_ij / |r_ij|²
Alignment:   f_ali = (Σ_{j: |r_ij|<R_a} v_j) / n_a - v_i
Cohesion:    f_coh = (Σ_{j: |r_ij|<R_c} r_ij) / n_c

v_i ← v_i + w_s · f_sep + w_a · f_ali + w_c · f_coh

where:
  x_i, v_i    — position and velocity of boid i
  r_ij         — displacement vector from boid i to boid j
  r̂_ij         — unit direction vector from i to j
  |r_ij|       — distance between boids i and j
  n_a, n_c     — number of neighbors within alignment / cohesion radii
  f_sep        — separation force (steers away from crowding; inversely proportional to distance²)
  f_ali        — alignment force (steers toward neighbors' average heading)
  f_coh        — cohesion force (steers toward neighbors' average position)
  R_s = 2.0    — separation perception radius (only nearby boids trigger avoidance)
  R_a = 4.0    — alignment perception radius
  R_c = 8.0    — cohesion perception radius
  w_s = 0.02   — separation weight
  w_a = 0.05   — alignment weight
  w_c = 0.005  — cohesion weight
  v_min = 0.3  — minimum speed (boids never stop)
  v_max = 1.5  — maximum speed
```

Speed clamping: `v_min ≤ |v_i| ≤ v_max`. Position update with toroidal wrap:
`x_i ← (x_i + v_i) mod (W, H)`.

**Presets**: classic, tight, loose, predator, murmuration, school.

**Controls**: `Shift+B` to enter, `Space` run/pause, `P/N` presets,
`F/D` speed.

**Source**: Craig W. Reynolds, "Flocks, Herds, and Schools: A Distributed
Behavioral Model," *Computer Graphics (SIGGRAPH '87 Proceedings)*, vol. 21,
no. 4, pp. 25-34, 1987.
[red3d.com/cwr/boids](https://www.red3d.com/cwr/boids/)

---

### Forest Fire

**Background.**
The forest fire model, introduced by Drossel and Schwabl in 1992, is a
cellular automaton that self-organizes to a critical state with power-law
distributed fire sizes.

**Formulation.**
Grid cells are in one of four states: `{EMPTY, TREE, BURNING, CHARRED}`. At
each tick (von Neumann neighborhood):

```
TREE     → BURNING     if any neighbor is BURNING (deterministic ignition)
TREE     → BURNING     with probability p_lightning (spontaneous lightning strike)
BURNING  → CHARRED     (deterministic, every tick)
CHARRED  → EMPTY       after cooldown ticks expire
EMPTY    → TREE        with probability p_grow (stochastic regrowth)

where:
  p_grow       — probability an empty cell grows a tree per tick
  p_lightning  — probability a tree spontaneously ignites per tick (very small)
  cooldown     — number of ticks a charred cell remains before becoming empty (default 3-5)
  p_c ≈ 0.5927 — 2D site percolation threshold (critical tree density)
```

Near `p_c`, fire cascade sizes follow a power-law distribution `P(s) ~ s^{-τ}`
(where `s` is cascade size and `τ` is the critical exponent).

**Presets**: classic, dense-forest, sparse-dry, percolation-threshold,
regrowth, inferno — varying `p_grow`, `p_lightning`, `cooldown`.

**Controls**: `Shift+F` to enter, `Space` run/pause, cursor to ignite trees,
`P/N` presets.

**Source**: B. Drossel and F. Schwabl, "Self-organized critical forest-fire
model," *Physical Review Letters*, vol. 69, no. 11, pp. 1629-1632, 1992.
[doi.org/10.1103/PhysRevLett.69.1629](https://doi.org/10.1103/PhysRevLett.69.1629)

---

### Epidemic SIR Model

**Background.**
The SIR model, formulated by Kermack and McKendrick in 1927, divides a
population into Susceptible, Infected, and Recovered compartments.

**Formulation.**
Grid cells are `{SUSCEPTIBLE, INFECTED, RECOVERED, DEAD}`. Each tick (von
Neumann neighborhood):

```
SUSCEPTIBLE with k infected neighbors:
    P(infection) = 1 - (1 - β)^k
    Infect with this probability.

INFECTED:
    With probability γ:
        → DEAD       with probability μ
        → RECOVERED  with probability 1 - μ

where:
  β          — transmission probability per infected neighbor per tick
  k          — number of infected von Neumann neighbors (0-4)
  (1 - β)^k  — probability of escaping infection from all k neighbors
  γ          — recovery probability per tick (inverse of average infection duration)
  μ          — mortality probability (chance of death upon recovery)
  R₀ = β/γ   — basic reproduction number (epidemic grows if R₀ > 1)
```

The continuous mean-field ODE approximation (well-mixed population):

```
dS/dt = -βSI
dI/dt = βSI - γI
dR/dt = γI

where:
  S, I, R ∈ [0, 1] — fraction of population that is susceptible, infected, recovered
```

**Presets**: classic, highly-contagious, deadly-plague, slow-burn,
sparse-population, pandemic — varying `β`, `γ`, `μ`.

**Controls**: `Shift+H` to enter, `Space` run/pause, cursor to infect cells,
`P/N` presets.

**Source**: William Ogilvy Kermack and A. G. McKendrick, "A contribution to
the mathematical theory of epidemics," *Proceedings of the Royal Society of
London. Series A*, vol. 115, no. 772, pp. 700-721, 1927.
[doi.org/10.1098/rspa.1927.0118](https://doi.org/10.1098/rspa.1927.0118)

---

## Procedural Generation

### Wave Function Collapse

**Background.**
Wave Function Collapse (WFC), created by Maxim Gumin in 2016, is a
constraint-satisfaction algorithm inspired by quantum mechanics.

**Formulation.**
A grid of cells, each holding a set of possible tiles `P(r,c) ⊆ {0, ..., 5}`
(water, sand, grass, forest, mountain, snow). Adjacency constraints
`A[t] ⊂ {0, ..., 5}` define which tiles may neighbor tile `t`.

```
1. Observe:   Find cell (r*,c*) with minimum entropy:
              (r*,c*) = argmin_{|P(r,c)|>1} (|P(r,c)| + ξ),  ξ ~ U(-0.1, 0.1)

2. Collapse:  Choose tile t ∈ P(r*,c*) with weighted probability:
              Prob(t) = w_t / Σ_{t'∈P} w_{t'}

3. Propagate: BFS from (r*,c*). For each neighbor n of current cell c:
              P(n) ← P(n) ∩ {t : ∃ s ∈ P(c) with t ∈ A[s] and s ∈ A[t]}
              If P(n) changed, add n's neighbors to queue.
              If P(n) = ∅, contradiction (mark failed).

where:
  P(r, c)    — set of possible tiles at cell (r, c) (starts as {0,...,5}, shrinks)
  |P(r, c)|  — number of remaining tile options (entropy proxy)
  ξ          — small random noise for tiebreaking when multiple cells have equal entropy
  w_t        — weight for tile t (higher weight = more likely to be chosen)
  A[t]       — adjacency set: tiles allowed to neighbor tile t
  BFS        — breadth-first search (propagates constraints outward from collapsed cell)
```

Default adjacency (terrain): water↔{water, sand}, sand↔{water, sand, grass},
grass↔{sand, grass, forest}, forest↔{grass, forest, mountain},
mountain↔{forest, mountain, snow}, snow↔{mountain, snow}.

**Presets**: terrain (uniform weights), islands (water-heavy), highlands
(mountain-heavy), coastal (beach-heavy), checkerboard (alternating).

**Controls**: `Shift+T` to enter, `Space` run/pause, `S` single step,
`R` reset, `P/N` presets.

**Source**: Maxim Gumin, *WaveFunctionCollapse* (GitHub repository), 2016.
[github.com/mxgmn/WaveFunctionCollapse](https://github.com/mxgmn/WaveFunctionCollapse)

---

### Turmites (2D Turing Machines)

**Background.**
Turmites generalize Langton's Ant into full 2D Turing machines with multiple
states and colors.

**Formulation.**
An agent at position `(r, c)` with internal state `q` and direction
`d ∈ {UP, RIGHT, DOWN, LEFT}` on a grid `g(r,c) ∈ {0, ..., C-1}`. A
transition table `δ[q][g]` defines the update rule:

```
(color_new, turn, q_new) = δ[q][g(r,c)]

g(r, c) ← color_new
d ← (d + turn) mod 4
(r, c) ← (r, c) + Δ(d)
q ← q_new

where:
  (r, c)     — agent position on the grid (toroidal boundary)
  q          — internal state of the agent (finite state machine)
  d          — direction index: 0=UP, 1=RIGHT, 2=DOWN, 3=LEFT
  g(r, c)    — color of the grid cell at (r, c), range {0, ..., C-1}
  δ[q][g]    — transition table: maps (state, color) → (new_color, turn, new_state)
  turn       — rotation: 0=none, 1=right 90°, 2=u-turn 180°, 3=left 90°
  Δ(d)       — direction vector: UP=(-1,0), RIGHT=(0,1), DOWN=(1,0), LEFT=(0,-1)
```

Langton's Ant is the simplest case: `δ[0][0] = (1, 1, 0)` (white → black,
turn right), `δ[0][1] = (0, 3, 0)` (black → white, turn left).

**Presets**: langton-ant, fibonacci, square-builder, highway, chaotic,
snowflake, striped, spiral-4c, counter, worm.

**Controls**: `Shift+U` to enter, `Space` run/pause, `+/-` add/remove
turmites, `P/N` presets, `F/D` speed.

**Source**: Christopher G. Langton, "Studying Artificial Life with Cellular
Automata," *Physica D*, vol. 22, nos. 1-3, pp. 120-149, 1986.
[doi.org/10.1016/0167-2789(86)90237-X](https://doi.org/10.1016/0167-2789(86)90237-X)

---

## Algorithms

### Maze Generator and Solver

**Background.**
The maze generator uses a recursive backtracker (randomized DFS). The solver
uses A* pathfinding.

**Formulation.**

*Generation* (recursive backtracker on a grid where odd-indexed cells are
carve-able):

```
1. Mark cell (1,1) as PATH, push to stack S.
2. While S ≠ ∅:
   a. Pop cell (r, c).
   b. Let N = unvisited cells at distance 2: {(r±2,c), (r,c±2)} ∩ grid.
   c. If N ≠ ∅:
      Choose random (nr, nc) ∈ N.
      Carve wall between: g((r+nr)/2, (c+nc)/2) ← PATH.
      Mark (nr, nc) as PATH, push to S.
   d. Else: backtrack (continue popping).
```

*Braiding*: after generation, for each wall cell with ≥ 2 adjacent path cells,
remove it with probability `p_loop` (creating cycles).

*A\* solver*: cost function `f(n) = g(n) + h(n)`:

```
where:
  n         — a cell being evaluated
  g(n)      — actual path cost from start to n (each step costs 1.0)
  h(n)      — heuristic estimate from n to goal: Manhattan distance |r - r_end| + |c - c_end|
  f(n)      — total estimated cost (cells with lowest f are explored first)
  p_loop    — braiding probability (chance of removing a wall to create loops)
```

**Presets**: classic (`p_loop = 0`), braided (0.3), sparse (0.1), dense, speed-run.

**Controls**: `Shift+M` to enter, `Space` run/pause, `G` generate new maze,
`V` solve, cursor to toggle walls, `P/N` presets.

**Source**: Jamis Buck, *Mazes for Programmers: Code Your Own Twisty Little
Passages*, The Pragmatic Programmers, 2015.
[pragprog.com](https://pragprog.com/titles/jbmaze/mazes-for-programmers/)

---

### 3D Ray Caster

**Background.**
The ray caster renders a first-person 3D view of a maze using the same
technique as Wolfenstein 3D (1992).

**Formulation.**
Player at position `(p_x, p_y)` with viewing angle `φ` and field of view
`FOV` (default `π/3`). For each screen column `col ∈ [0, W)`:

```
θ = φ - FOV/2 + (col/W) · FOV

where:
  φ         — player's viewing angle (radians, 0 = east)
  FOV       — field of view (default π/3 radians = 60°)
  col       — screen column index (0 to W-1)
  W         — screen width in columns
  θ         — angle of the ray cast for this column
```

DDA (Digital Differential Analyzer) marches through the grid:

```
δ_x = |1 / cos θ|,   δ_y = |1 / sin θ|

Initialize side distances from player position to first grid line.
While not hit and depth < 30:
    if side_x < side_y:
        side_x += δ_x,  advance map_x
        depth = side_x - δ_x
    else:
        side_y += δ_y,  advance map_y
        depth = side_y - δ_y
    if grid[map_y][map_x] = WALL: hit

where:
  (p_x, p_y)     — player position (fractional grid coordinates)
  (map_x, map_y) — current grid cell being tested
  δ_x, δ_y       — distance the ray must travel to cross one grid line (x or y)
  side_x, side_y  — cumulative distance to next x / y grid line
  depth           — total ray travel distance when wall is hit
```

Fish-eye correction and wall rendering:

```
perp_dist = depth · cos(θ - φ)
wall_height = screen_height / perp_dist

where:
  perp_dist    — perpendicular distance to wall (removes fish-eye distortion)
  wall_height  — on-screen height of the wall column (taller = closer)
```

**Presets**: classic, braided, sparse, wide-fov (`FOV = π/2`), speed-run.

**Controls**: `Shift+V` to enter, `W/Up` forward, `S/Down` backward,
`A/Left` turn left, `D/Right` turn right, `,/.` strafe, `M` minimap,
`G` generate new maze, `P/N` presets.

**Source**: Jamis Buck, *Mazes for Programmers: Code Your Own Twisty Little
Passages*, The Pragmatic Programmers, 2015.
[pragprog.com](https://pragprog.com/titles/jbmaze/mazes-for-programmers/)

---

## Mathematics

### Fractal Explorer (Mandelbrot and Julia Sets)

**Background.**
The Mandelbrot set is the set of complex numbers *c* for which the iteration
`z ← z² + c` remains bounded. Julia sets are the companion family
parameterized by a fixed *c*.

**Formulation.**
For a grid point mapped to complex coordinate `(re, im)` via:

```
scale = 3 / zoom
re = center_re + (col - W/2) / W · scale · aspect
im = center_im + (row - H/2) / H · scale
```

The iteration (escape-time algorithm):

```
Mandelbrot mode:  z₀ = 0,         c = (re, im)
Julia mode:       z₀ = (re, im),  c = (c_re, c_im)  (fixed)

n = 0
while n < max_iter and z_r² + z_i² ≤ 4:
    (z_r, z_i) ← (z_r² - z_i² + c_r,  2·z_r·z_i + c_i)
    n += 1

where:
  z = z_r + z_i·i  — complex number being iterated (real and imaginary parts)
  c = c_r + c_i·i  — complex parameter (grid coordinate or fixed Julia param)
  z₀              — initial value of z (0 for Mandelbrot, grid point for Julia)
  max_iter        — maximum iterations before declaring the point "in the set"
  |z|² = z_r² + z_i²  — squared magnitude (escape test)
  4               — escape radius squared (|z| > 2 means the orbit diverges)
  n               — escape iteration count (mapped to color via palette)
  (re, im)        — complex coordinate of the grid point being tested
  zoom            — magnification factor (higher = deeper zoom into the fractal)
  center_re, center_im — center of the viewport in complex coordinates
  aspect          — width/height ratio of the terminal
```

**Preset parameters:**

| Preset | center | zoom | max_iter |
|--------|--------|------|----------|
| classic | (-0.5, 0) | 1 | 80 |
| seahorse-valley | (-0.745, 0.186) | 200 | 150 |
| spiral | (-0.7616, -0.0848) | 500 | 200 |
| julia-dendrite | Julia c = (0, 1) | 1 | 100 |
| julia-rabbit | Julia c = (-0.123, 0.745) | 1 | 100 |
| julia-galaxy | Julia c = (-0.8, 0.156) | 1 | 120 |

**Palettes**: classic, fire, ocean, neon, grayscale.

**Controls**: `Shift+Z` to enter, arrow keys pan, `+/-` zoom, `Space` toggle
Julia mode, `C` cycle color palette, `P/N` presets, `R` reset view.

**Source**: Benoit B. Mandelbrot, *The Fractal Geometry of Nature*, W. H.
Freeman, New York, 1983.
[mathworld.wolfram.com/MandelbrotSet.html](https://mathworld.wolfram.com/MandelbrotSet.html)

---

### Strange Attractors

**Background.**
A strange attractor is the long-term pattern traced by a chaotic dynamical
system in phase space. Despite being deterministic, the trajectory never
exactly repeats — it fills a fractal set.

**Lorenz system** (Euler integration):

```
dx/dt = σ(y - x)
dy/dt = x(ρ - z) - y
dz/dt = xy - βz

where:
  (x, y, z)  — state variables (represent convective flow amplitude, temperature
               difference, and vertical temperature profile distortion)
  σ (sigma)  — Prandtl number (ratio of viscous to thermal diffusion)
  ρ (rho)    — Rayleigh number (driving force; chaos onset at ρ ≈ 24.74)
  β (beta)   — geometric factor of the convection cell
  δt         — Euler integration timestep
```

**Rossler system** (Euler integration):

```
dx/dt = -y - z
dy/dt = x + ay
dz/dt = b + z(x - c)

where:
  (x, y, z)  — state variables
  a           — controls the speed of x-y oscillation
  b           — controls the z "kick" magnitude
  c           — controls when z grows large (folding threshold; chaos onset ≈ c > 5)
```

**Henon map** (discrete):

```
x_{n+1} = 1 - a·x_n² + y_n
y_{n+1} = b·x_n

where:
  (x_n, y_n)  — state at iteration n
  a            — nonlinearity parameter (classic: 1.4; controls folding/stretching)
  b            — contraction parameter (classic: 0.3; controls area contraction per step)
```

Divergence check: if `|x|, |y|, or |z| > 10⁶`, reset to `(1, 1, 1)`.

**Preset parameters:**

| Preset | System | Parameters | δt | steps/tick |
|--------|--------|------------|-----|-----------|
| lorenz-classic | Lorenz | σ=10, ρ=28, β=8/3 | 0.005 | 50 |
| lorenz-chaotic | Lorenz | σ=10, ρ=99.96, β=8/3 | 0.003 | 60 |
| rossler-classic | Rossler | a=0.2, b=0.2, c=5.7 | 0.01 | 40 |
| rossler-funnel | Rossler | a=0.2, b=0.2, c=14.0 | 0.005 | 50 |
| henon | Henon | a=1.4, b=0.3 | — | 200 |
| henon-wide | Henon | a=1.2, b=0.3 | — | 200 |

**Controls**: `Shift+A` to enter, `Space` toggle rotation, `C` cycle color
palette, `+/-` scale, `1/2/3` increment parameters, `!/@ /#` decrement
parameters, `P/N` presets, `R` reset.

**Sources**:
Lorenz: Edward N. Lorenz, "Deterministic Nonperiodic Flow," *Journal of the
Atmospheric Sciences*, vol. 20, no. 2, pp. 130-141, 1963.
[mathworld.wolfram.com/LorenzAttractor.html](https://mathworld.wolfram.com/LorenzAttractor.html)
| Rossler: O. E. Rossler, "An equation for continuous chaos," *Physics Letters
A*, vol. 57, no. 5, pp. 397-398, 1976.
[doi.org/10.1016/0375-9601(76)90101-8](https://doi.org/10.1016/0375-9601(76)90101-8)
| Henon: M. Henon, "A two-dimensional mapping with a strange attractor,"
*Communications in Mathematical Physics*, vol. 50, no. 1, pp. 69-77, 1976.
[doi.org/10.1007/BF01608556](https://doi.org/10.1007/BF01608556)

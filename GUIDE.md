# Simulation Mode Guide

This document describes the scientific background, algorithms, and controls
for each of the 27 simulation modes in the Cellular Automaton Sandbox.

---

## Cellular Automata

### Conway's Game of Life

**Background.**
Devised by mathematician John Conway in 1970, the Game of Life is the most
famous cellular automaton. It demonstrates how complex, seemingly intelligent
behavior can emerge from two trivially simple rules applied to a grid of
on/off cells:

- **Birth**: a dead cell with exactly 3 live neighbors becomes alive.
- **Survival**: a live cell with 2 or 3 live neighbors stays alive; otherwise
  it dies.

Despite this simplicity, the Game of Life is Turing-complete. It supports
stable structures (blocks, beehives), oscillators (blinkers, pulsars),
spaceships (gliders, LWSS), and guns that manufacture gliders indefinitely.

**Features in this sandbox.**
The implementation goes well beyond a basic viewer. It includes a pattern
library (glider, Gosper gun, R-pentomino, etc.), brush painting with
configurable size and shape, a heatmap overlay showing cumulative cell
activity, a genetic algorithm evolver that breeds patterns for target fitness,
a split-screen mode comparing two rulesets side by side, cell age coloring,
population sparkline, pattern detection dashboard, toroidal wrapping, history
rewind, blueprint mode for custom pattern creation, RLE pattern import, and
save/load to JSON.

**Controls**: `Space` run/pause, `Enter` toggle cell, arrows move cursor,
`+/-` speed, `P/N` cycle patterns, `R` randomize, `C` clear, `T` toroidal,
`</>` rewind/forward, `V` brush, `H` heatmap, `D` dashboard, `A` evolver,
`M` split-screen, `G/F` rule presets, `w` save, `O` load.

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

The simulator renders successive generations top to bottom, scrolling as the
grid fills.

**Controls**: `W` to enter, `+/-` change rule number, `P/N` jump to notable
rules, `Space` run/pause, `R` randomize initial row.

---

### Lenia — Continuous Cellular Automaton

**Background.**
Lenia, introduced by Bert Wang-Chak Chan in 2019, generalizes discrete
cellular automata into continuous space. Instead of binary alive/dead states,
each cell holds a float value in [0, 1]. A smooth Gaussian kernel replaces the
discrete neighbor count, and a continuous growth function replaces the
birth/survival lookup.

This produces lifelike "creatures" — self-organizing, self-moving blobs that
resemble microorganisms. Named species include Orbium (a gliding blob),
Geminium (a self-replicating pair), and Smooth Life (a variant with smoother
dynamics).

**Presets**: Orbium, Geminium, Hydrogeminium, Smooth Life — each with
different kernel radius, growth parameters, and integration timestep.

**Controls**: `L` to enter, `Space` run/pause, `P/N` cycle presets, `R`
randomize, `+/-` speed.

---

### Multi-State Automata (Brian's Brain, Wireworld, Langton's Ant)

**Background.**
These three automata use more than two cell states, enabling richer dynamics.

**Brian's Brain** (Brian Silverman, 1994) uses three states: ON, DYING, OFF.
An ON cell always becomes DYING, DYING always becomes OFF, and OFF becomes ON
if exactly 2 neighbors are ON. This creates perpetually moving sparks and
oscillators — no static structures are possible.

**Wireworld** (Brian Silverman, 1987) has four states: EMPTY, CONDUCTOR, HEAD,
TAIL. Electron heads become tails, tails become conductors, and conductors
become heads if 1-2 neighbors are heads. This can simulate digital logic
gates, clocks, and even full computers.

**Langton's Ant** (Chris Langton, 1986) is a 2D Turing machine. An ant on a
white cell turns right, flips the cell to black, and moves forward; on a black
cell it turns left, flips to white, and moves forward. After ~10,000
apparently chaotic steps, the ant always begins building a diagonal
"highway" — an emergent order that has never been formally proven.

**Controls**: `Shift+X` to enter, `P/N` switch between automaton types,
`Space` run/pause, `Enter` toggle cells.

---

### Neural Cellular Automata

**Background.**
Neural Cellular Automata (NCA), popularized by Mordvintsev et al. at Google
in 2020, replace hand-crafted rules with learned neural networks. Each cell
carries multiple continuous channels (like RGBA). At each step, cells perceive
their neighborhood through Sobel filters, process the result through a small
MLP, and update their state.

NCAs can learn to grow specific shapes from a single seed cell and regenerate
when damaged — mimicking biological morphogenesis. The presets here use
hand-tuned weights that approximate these behaviors: growing, persisting,
morphogenesis (Turing-like pattern formation), and regeneration.

**Presets**: grow, persist, morphogenesis, regenerate.

**Controls**: `Shift+N` to enter, `Space` run/pause, `X` paint cells, `E`
erase, `P/N` presets, `+/-` speed.

---

### Abelian Sandpile

**Background.**
The Abelian Sandpile Model, introduced by Bak, Tang, and Wiesenfeld in 1987,
is the canonical example of self-organized criticality. Sand grains accumulate
on a grid. When any cell reaches a threshold (typically 4), it topples:
distributing one grain to each of its four neighbors. Edge grains fall off the
grid.

The key insight is that the system naturally evolves to a critical state where
avalanches of all sizes occur, following a power-law distribution — the same
statistics seen in earthquakes, forest fires, and stock market crashes. The
"identity" configuration (starting from maximum and relaxing) produces
beautiful fractal patterns.

**Presets**: center-drop, random-rain, identity, multi-source, high-threshold.

**Controls**: `Shift+J` to enter, `Space` run/pause, `P/N` presets,
`1-4` drop mode, cursor to click-drop grains.

---

## Physics

### Falling Sand

**Background.**
Falling sand games simulate granular material physics with simple per-particle
rules. Each cell is one of several materials, and interactions are resolved
locally: sand falls under gravity and slides diagonally, water flows and
spreads, fire rises and decays, stone is immobile, and plants grow slowly.
Cross-material interactions create emergent complexity — sand sinks through
water, fire ignites plants, water extinguishes fire.

The simulator processes cells bottom-to-top (so falling objects don't cascade
in a single frame) with randomized column order to prevent directional bias.

**Materials**: Sand, Water, Fire, Stone, Plant.

**Controls**: `F` to enter, `Space` run/pause, `P/N` cycle materials,
`+/-` brush size, cursor to place material.

---

### Reaction-Diffusion (Gray-Scott Model)

**Background.**
The Gray-Scott model describes two chemical species U and V that react and
diffuse on a surface. The reaction U + 2V -> 3V converts reactant U into
product V auto-catalytically, while V slowly decays. The feed rate *f*
replenishes U, and the kill rate *k* removes V.

Different (f, k) parameter combinations produce strikingly different patterns:
self-replicating spots (mitosis), coral-like branching, labyrinthine mazes,
traveling solitons, and worm-like structures. These patterns closely resemble
those found in nature — animal coat markings, coral growth, and chemical
oscillations — as predicted by Alan Turing's 1952 morphogenesis paper.

**Presets**: Mitosis, Coral, Maze, Solitons, Worms, Bubbles, Waves, Spots.

**Controls**: `Shift+R` to enter, `Space` run/pause, `P/N` presets, `Enter`
drop chemical seed, `+/-` speed.

---

### Fluid Dynamics (Lattice Boltzmann Method)

**Background.**
The Lattice Boltzmann Method (LBM) simulates fluid flow by tracking
probability distributions of particles on a lattice rather than solving the
Navier-Stokes equations directly. The D2Q9 model uses 9 velocity directions
per cell. Each timestep has two phases: streaming (particles move to
neighbors) and collision (distributions relax toward equilibrium via the BGK
operator).

At low Reynolds numbers the flow is laminar; as velocity increases, vortex
streets and turbulence develop. The simulation supports paintable obstacles
that create von Karman vortex streets and other flow phenomena.

**Presets**: laminar, moderate, turbulent, viscous, fast — varying viscosity
and inlet velocity to achieve different Reynolds numbers.

**Controls**: `Shift+D` to enter, `Space` run/pause, `Enter` paint obstacles,
`+/-` viscosity, `D/F` speed, `C` clear obstacles.

---

### Ising Model

**Background.**
The 2D Ising model, proposed by Wilhelm Lenz in 1920 and solved exactly by
Lars Onsager in 1944, is the most studied model in statistical mechanics. A
square lattice of spins (each +1 or -1) interact with their neighbors:
aligned spins lower the energy. The system is held at a temperature T.

At low temperature, spins align ferromagnetically (ordered). At the critical
temperature T_c = 2/ln(1+sqrt(2)) ~ 2.269, the system undergoes a continuous
phase transition: long-range correlations diverge, domain walls fracture, and
fluctuations occur at all scales. Above T_c, thermal noise dominates and the
system is paramagnetic (disordered). The Metropolis-Hastings algorithm
stochastically flips individual spins according to the Boltzmann distribution.

**Presets**: cold (0.5), cool (1.5), critical (2.269), warm (3.0), hot (5.0),
anti-ferromagnetic (J = -1).

**Controls**: `Shift+I` to enter, `Space` run/pause, `,/.` adjust
temperature, `P/N` presets.

---

### Magnetic Field (Electromagnetic Particles)

**Background.**
Charged particles in electromagnetic fields obey the Lorentz force law:
**F** = q(**v** x **B** + **E**), where **B** is the magnetic field and **E**
is the electric field. The simulation integrates particle trajectories using
the Boris method, a symplectic integrator that exactly preserves the circular
orbit geometry of particles in uniform magnetic fields.

Different field configurations produce distinct physical phenomena: cyclotron
orbits in uniform fields, magnetic bottle confinement from converging field
lines, ExB drift in crossed fields, Hall effect charge separation, and auroral
spiraling along field lines.

**Presets**: cyclotron, magnetic-bottle, exb-drift, hall-effect, aurora.

**Controls**: `Shift+G` to enter, `Space` run/pause, `+/-` B-field strength,
`E` toggle E-field, `P/N` presets.

---

### N-Body Gravity

**Background.**
The gravitational N-body problem — computing the motion of N masses under
mutual gravitational attraction (F = Gm1m2/r^2) — is one of the oldest
problems in physics. For N >= 3 there is no general closed-form solution, and
the system is typically chaotic: tiny perturbations lead to dramatically
different outcomes.

The simulation uses velocity-Verlet integration with gravitational softening
to prevent singularities at close approach. Bodies that come within a merge
distance collide inelastically, conserving momentum and mass.

**Presets**: binary-star (two orbiting stars), solar-system (star with
planets), three-body (chaotic), asteroid-belt (30 small bodies), figure-eight
(a special periodic three-body orbit discovered by Moore in 1993).

**Controls**: `Shift+K` to enter, `Space` run/pause, `+/-` gravity strength,
`A` add planet, `Shift+A` add star, `P/N` presets.

---

### Hydraulic Erosion

**Background.**
Hydraulic erosion shapes landscapes through the cycle of rainfall, water flow,
sediment transport, and deposition. Water picks up sediment in proportion to
its velocity and the terrain gradient; when it slows (on flatter ground or in
pools), sediment deposits. Over time this carves river valleys, canyons, and
deltas.

The simulation tracks five fields: terrain height, water depth, sediment
concentration, flow velocity, and cumulative erosion. Each preset generates a
different initial heightmap — sine hills, sharp ridges, volcanic cones — and
tunes the erosion/deposition balance.

**Presets**: gentle-hills, mountain-range, canyon-carver, river-delta,
volcanic.

**Controls**: `Shift+Y` to enter, `Space` run/pause, `+/-` rain rate,
`P/N` presets, `F/D` speed.

---

### Diffusion-Limited Aggregation (DLA)

**Background.**
DLA, introduced by Witten and Sander in 1981, models crystal growth by random
deposition. Particles perform random walks until they contact an existing
crystal, at which point they stick. The resulting structures are fractals with
dimension ~1.7, resembling snowflakes, lightning bolts, mineral dendrites, and
coral.

The stickiness parameter controls branching density: high stickiness produces
dense, compact clusters; low stickiness creates long, wispy tendrils as
particles penetrate deeper before sticking.

**Presets**: center-seed, line-seed, multi-seed, sparse-tendrils, coral,
lightning.

**Controls**: `Shift+L` to enter, `Space` run/pause, cursor to place seeds,
`P/N` presets.

---

### Double Pendulum

**Background.**
A double pendulum — two rigid rods connected end to end, swinging under
gravity — is the simplest mechanical system that exhibits deterministic chaos.
The equations of motion are derived from Lagrangian mechanics and integrated
with a fourth-order Runge-Kutta method.

Two pendulums launched with infinitesimally different initial angles will
initially track each other closely, then diverge exponentially. The rate of
divergence is characterized by the Lyapunov exponent — a positive value
confirms chaotic behavior. The simulation runs two such pendulums
simultaneously, coloring them differently so you can watch the divergence in
real time.

**Presets**: classic, heavy-light, long-short, high-energy, damped, symmetric.

**Controls**: `Shift+O` to enter, `Space` pause, `T` toggle trail, `D`
toggle damping, `+/-` initial angle offset, `R` reset, `P/N` presets.

---

## Biology

### Particle Life

**Background.**
Particle Life, explored by Jeffrey Ventrella and popularized by Tom Motz,
simulates emergent life-like behavior from simple attraction and repulsion
rules between colored particle types. Each pair of types has an interaction
strength: positive attracts, negative repels. The force is piecewise-linear
with universal short-range repulsion.

From these minimal rules, strikingly complex structures emerge: orbiting
clusters, cell-like membranes, chains, and self-propelled entities that
resemble primitive organisms. Different random interaction matrices produce
wildly different "chemistries."

**Controls**: `Shift+P` to enter, `Space` run/pause, `R` randomize
interaction matrix, `P/N` presets, `+/-` speed.

---

### Wa-Tor Ecosystem

**Background.**
Wa-Tor, created by Alexander Dewdney in 1984, simulates predator-prey
dynamics on a toroidal ocean. Fish swim randomly and breed asexually after
reaching maturity. Sharks hunt fish for energy and starve if they go too long
without eating.

The population dynamics follow Lotka-Volterra oscillations: fish proliferate,
sharks feast and multiply, overpredation crashes the fish population, sharks
starve and decline, fish recover, and the cycle repeats. The simulation tracks
both population curves in real time.

**Controls**: `Shift+E` to enter, `Space` run/pause, `+/-` speed,
`P/N` presets.

---

### Physarum Slime Mold

**Background.**
Physarum polycephalum is a slime mold that solves optimization problems
without a brain. Thousands of agents move, sense, and deposit pheromone
trails. Each agent looks ahead at three positions (left, center, right),
rotates toward the strongest pheromone signal, moves forward, and deposits
more pheromone. The trail field diffuses and decays over time.

This stigmergic algorithm — indirect communication through the environment —
produces networks that closely resemble highway maps, neural architectures,
and vascular systems. Physarum has famously been shown to find shortest paths
through mazes and approximate Steiner trees.

**Presets**: network, ring, maze-solver, tendrils, dense.

**Controls**: `Shift+S` to enter, `Space` run/pause, `P/N` presets,
`+/-` speed.

---

### Boids Flocking

**Background.**
Boids, created by Craig Reynolds in 1986, demonstrates how realistic flocking
behavior emerges from three simple local rules applied to each agent:

1. **Separation**: steer away from nearby neighbors to avoid crowding.
2. **Alignment**: steer toward the average heading of neighbors.
3. **Cohesion**: steer toward the average position of neighbors.

By adjusting the weights and perception radii of these three rules, the model
produces behaviors ranging from tight bird flocks and fish schools to loose
swarms and murmuration patterns.

**Presets**: classic, tight, loose, predator, murmuration, school.

**Controls**: `Shift+B` to enter, `Space` run/pause, `P/N` presets,
`F/D` speed.

---

### Forest Fire

**Background.**
The forest fire model, introduced by Drossel and Schwabl in 1992, is a
cellular automaton that self-organizes to a critical state. Trees grow
stochastically on empty cells, and fires ignite either from burning neighbors
or rare lightning strikes. Burning trees become charred, then empty.

Near the critical tree density (~59.27% in 2D site percolation), fires of all
sizes occur, following a power-law distribution. This is another example of
self-organized criticality — the same universality class as earthquakes and
avalanches.

**Presets**: classic, dense-forest, sparse-dry, percolation-threshold,
regrowth, inferno.

**Controls**: `Shift+F` to enter, `Space` run/pause, cursor to ignite trees,
`P/N` presets.

---

### Epidemic SIR Model

**Background.**
The SIR model, formulated by Kermack and McKendrick in 1927, divides a
population into Susceptible, Infected, and Recovered compartments. Susceptible
individuals become infected with probability dependent on the number of
infected neighbors (beta), and infected individuals recover (or die) with
probability gamma.

The basic reproduction number R0 = beta/gamma determines whether an epidemic
grows or dies out. The spatial version on a grid shows how geography, density,
and stochasticity affect disease spread — wave fronts, herd immunity
thresholds, and isolated clusters.

**Presets**: classic, highly-contagious, deadly-plague, slow-burn,
sparse-population, pandemic.

**Controls**: `Shift+H` to enter, `Space` run/pause, cursor to infect cells,
`P/N` presets.

---

## Procedural Generation

### Wave Function Collapse

**Background.**
Wave Function Collapse (WFC), created by Maxim Gumin in 2016, is a
constraint-satisfaction algorithm inspired by quantum mechanics. Each cell
starts in a superposition of all possible tiles. The algorithm iteratively
finds the cell with the lowest entropy (fewest remaining options), collapses
it to a single tile (weighted random), and propagates constraints to neighbors
via BFS. If a contradiction occurs (zero options), the algorithm backtracks.

The result is procedurally generated terrain that respects local adjacency
rules: water borders sand, sand borders grass, grass borders forest, and so
on. Different tile weight distributions produce islands, highlands, coastal
regions, or mixed landscapes.

**Presets**: terrain, islands, highlands, coastal, checkerboard.

**Controls**: `Shift+T` to enter, `Space` run/pause, `S` single step,
`R` reset, `P/N` presets.

---

### Turmites (2D Turing Machines)

**Background.**
Turmites generalize Langton's Ant into full 2D Turing machines. An agent on a
colored grid has an internal state. At each step, based on its current state
and the color of the cell it occupies, it writes a new color, turns, and
transitions to a new state. Different transition tables produce radically
different behaviors — from structured highways and spirals to chaotic
scattering.

Langton's Ant is the simplest turmite (1 state, 2 colors). More complex
turmites with 2-4 states and 2-4 colors can build squares, count in binary,
generate Fibonacci spirals, or produce fractal snowflake patterns.

**Presets**: langton-ant, fibonacci, square-builder, highway, chaotic,
snowflake, striped, spiral-4c, counter, worm.

**Controls**: `Shift+U` to enter, `Space` run/pause, `+/-` add/remove
turmites, `P/N` presets, `F/D` speed.

---

## Algorithms

### Maze Generator and Solver

**Background.**
The maze generator uses a recursive backtracker (randomized depth-first
search) to carve a perfect maze — one where every cell is reachable and there
is exactly one path between any two points. Optional braiding introduces
loops by randomly removing walls, creating multiple solution paths.

The solver uses A* pathfinding with Manhattan distance as the heuristic. You
can watch the generation and solving phases step by step: the generator carves
corridors in real time, then the solver explores and backtracks until it
finds the shortest path.

**Presets**: classic, braided, sparse, dense, speed-run.

**Controls**: `Shift+M` to enter, `Space` run/pause, `G` generate new maze,
`V` solve, cursor to toggle walls, `P/N` presets.

---

### 3D Ray Caster

**Background.**
The ray caster renders a first-person 3D view of a maze using the same
technique as Wolfenstein 3D (1992). For each column of the screen, a ray is
cast from the player's position into the maze. The DDA (Digital Differential
Analyzer) algorithm efficiently finds the first wall intersection, and the
wall is drawn at a height inversely proportional to the distance (with
fish-eye correction).

The maze is generated by the same recursive backtracker as the Maze Solver
mode. A minimap overlay shows the player's position and field of view.

**Presets**: classic, braided, sparse, wide-fov, speed-run.

**Controls**: `Shift+V` to enter, `W/Up` forward, `S/Down` backward,
`A/Left` turn left, `D/Right` turn right, `,/.` strafe, `M` minimap,
`G` generate new maze, `P/N` presets.

---

## Mathematics

### Fractal Explorer (Mandelbrot and Julia Sets)

**Background.**
The Mandelbrot set is the set of complex numbers *c* for which the iteration
z = z^2 + c (starting from z = 0) remains bounded. Its boundary is an
infinitely complex fractal — zooming reveals self-similar spirals, seahorses,
and dendritic filaments at every scale.

Julia sets are the companion: for a fixed *c*, the Julia set is the boundary
between z values that escape and those that don't. Each point in the
Mandelbrot set corresponds to a connected Julia set; points outside correspond
to disconnected "Fatou dust." The explorer lets you click any point to see its
Julia set.

**Presets**: classic (full Mandelbrot), seahorse-valley, spiral (500x zoom),
julia-dendrite, julia-rabbit, julia-galaxy.

**Palettes**: classic, fire, ocean, neon, grayscale.

**Controls**: `Shift+Z` to enter, arrow keys pan, `+/-` zoom, `Space` toggle
Julia mode, `C` cycle color palette, `P/N` presets, `R` reset view.

---

### Strange Attractors

**Background.**
A strange attractor is the long-term pattern traced by a chaotic dynamical
system in phase space. Despite being deterministic, the trajectory never
exactly repeats — it fills a fractal set.

**Lorenz attractor** (Edward Lorenz, 1963): discovered while modeling
atmospheric convection. The butterfly-shaped double spiral became the icon of
chaos theory. Parameters: sigma = 10, rho = 28, beta = 8/3.

**Rossler attractor** (Otto Rossler, 1976): a simpler system with a single
spiral that periodically folds back on itself. It was designed as the minimal
continuous chaotic system.

**Henon map** (Michel Henon, 1976): a discrete 2D map that produces a fractal
attractor with a Cantor-set cross-section, originally studied as a simplified
Poincare section of the Lorenz system.

**Presets**: lorenz-classic, lorenz-chaotic, rossler-classic, rossler-funnel,
henon, henon-wide.

**Controls**: `Shift+A` to enter, `Space` toggle rotation, `C` cycle color
palette, `+/-` scale, `1/2/3` increment parameters, `!/@ /#` decrement
parameters, `P/N` presets, `R` reset.

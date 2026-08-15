# Diablo IV Paragon Optimizer

Tooling to optimize Diablo IV paragon boards: which boards to run, at what
rotation, which glyph in each socket, and which nodes to buy.

Existing planners (Maxroll, D4Builds, Mobalytics) let you click nodes manually.
None of them optimize. This does.

## Why paragon is a real optimization problem

A glyph sits in a socket and counts a specific stat, but **only from nodes you
purchased inside a Manhattan-distance-5 diamond around that socket**. For every
5 of that stat in range, the glyph pays out its coefficient. So a mediocre node
inside the diamond can beat a better node outside it, and socket placement
depends on which nodes you plan to buy. That mutual dependence is what makes it
a search problem rather than a shopping list.

Decision variables: board selection, board rotation, entry gate, glyph
assignment, and node purchases, against a fixed point budget.

## What is verified, and how

Everything here was cross-checked rather than assumed.

| Fact | How it was established |
|---|---|
| Board geometry | Blizzard dump vs Maxroll tables, identical cell-for-cell on 10/10 Barbarian boards |
| Node values | 149/149 formulas agree across both sources |
| The six `ParagonPowerBudgetMultiplier` scalars | Each derived from 42-58 independent formulas, all yielding one distinct value |
| Glyph radius = Manhattan 5 | Pixel measurement of the in-game highlight, plus a diamond covering a constant 53 cells on 9/10 boards where a square gives a noisy 74-85 |
| Glyph level formula | Reproduces all 8 observed in-game values exactly |
| Damage buckets | Derived from Blizzard's own attribute naming (`Multiplicative_*` vs plain), not community lore |
| Board layout reading | Occupancy matched a known 441-cell layout at 100.0% |

### The six scalars

The game data stores many node values as `coefficient x
ParagonPowerBudgetMultiplierNode{rarity}{type}()`, and that function is compiled
into the client rather than shipped as data. Recovered by cross-referencing
Maxroll's resolved formula table:

| | Offensive | Defensive |
|---|---|---|
| Magic | 0.025 | 0.02 |
| Rare Minor | 0.05 | 0.04 |
| Rare Major | 0.05 | 0.04 |

### Glyph level formula

`value = base + perLevel * rank`, where rank is the displayed level minus 1 for
legendary bonuses and bonus-to-nodes affixes, and minus 2 for "for every 5 stat"
affixes. The bonus-to-nodes class stores its base in per-mille.

## Layout

```
src/     extraction, modelling and solving code
data/    the corpus: 79 boards, 561 nodes, 160 glyphs, 2853 skills,
         11795 items, 1273 aspects, 243 uniques, 35 mythics, 64 gems, 55 runes
docs/    findings and open questions
spopti/  a standalone re-implementation of rawrzcookie's Tap Titans 2
         optimizer, which is what this project grew out of
```

### Notable source files

- `src/damage_model.py` - bucket model. Seeds from a character's stats panel
  (which already rolls up gear, masterwork and tempering) and evaluates paragon
  as deltas on top, so complete gear data is not required to rank builds.
- `src/solver.py` - per (board, rotation, entry, glyph) greedy connected growth
  producing value curves, then a knapsack across boards with glyph uniqueness
  enforced.
- `src/extract2.py` - reads a paragon board off a screenshot. Fits the node
  lattice, then proves alignment by matching occupancy against the 10 known
  board layouts in 4 rotations. A poor match is reported as a failed read
  rather than guessed at.
- `src/ocr.swift` - Apple Vision OCR, used to pull data out of screen
  recordings locally. Build without `-O`; the optimizer hangs on this file.
- `src/build_everything.py` - regenerates `data/` from the upstream sources.

## Data sources

- [DiabloTools/d4data](https://github.com/DiabloTools/d4data) - Blizzard game
  files parsed to JSON. Geometry and structure.
- Maxroll's planner data - the resolved formula table that supplies the six
  scalars. Discovered via the browser's own resource timings.

Game data remains the property of Blizzard Entertainment. This repository
contains derived tables for analysis, plus original code.

## Status

Working: the corpus, the extractor, the bucket model, the damage model, the
solver machinery.

Open:
- The additive-damage bucket has no baseline, because the stats panel exposes no
  single additive total. Inflates anything landing in that bucket.
- Board-to-board chain cost is charged flat rather than routed exactly.
- Whether a glyph diamond can cross into an adjacent attached board.
- Uptime assumptions for conditional bonuses are judgement calls, exposed in
  `UPTIME` in `damage_model.py` rather than buried.

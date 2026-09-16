# Replay performance

Each sample runs 200 identity replays of the same 202-step scenario.
Five samples alternate full and compact order, with the same default oracles and scenario state.
The figures below are medians of those sample times; this is a microbenchmark, not a universal gain.

| Mode | Median batch seconds | Per replay milliseconds |
| --- | ---: | ---: |
| Before: full Step history | 0.5087 | 2.543 |
| After: compact structural rows | 0.3400 | 1.700 |

Observed speedup: **1.50×**. Raw samples are in `benchmarks/performance.json`.
Digest, decisions, executed step count and findings have separate parity tests across all 15 bugs × 50 seeds.



All 50 seeds per bug; only failing runs are shrunk. Each invocation has 5000 replays / 60 wall seconds, including guard, FIFO baseline and final verification. b06/b15 promote leaks; b11 uses max_time=60.

Per-bug columns are arithmetic means across its failing seeds. The last row is the median across individual failures, not a mean of means.

| Bug               | Failures | Deviations before → after | Executed steps before → after | Saved prefix after | Replays |    Seconds |
|-------------------|---------:|--------------------------:|------------------------------:|-------------------:|--------:|-----------:|
| b01               |       24 |               2.21 → 1.00 |                     6.5 → 6.0 |                2.8 |     8.9 |     0.0022 |
| b02               |       24 |               2.54 → 1.00 |                   10.0 → 10.0 |                2.8 |     9.8 |     0.0030 |
| b03               |       50 |               0.00 → 0.00 |                     1.0 → 1.0 |                0.0 |     3.0 |     0.0006 |
| b04               |       10 |               2.00 → 2.00 |                     5.0 → 5.0 |                3.0 |     8.0 |     0.0021 |
| b05               |        7 |               3.14 → 2.43 |                   10.6 → 10.6 |                8.1 |    17.3 |     0.0053 |
| b06               |       50 |               0.00 → 0.00 |                     4.0 → 4.0 |                0.0 |     3.0 |     0.0008 |
| b07               |       12 |               1.50 → 1.00 |                     5.0 → 5.0 |                3.0 |     8.0 |     0.0019 |
| b08               |       23 |               1.39 → 1.00 |                     6.4 → 6.0 |                2.9 |     7.7 |     0.0019 |
| b09               |       12 |               2.17 → 1.25 |                     9.8 → 9.8 |                5.8 |    11.8 |     0.0032 |
| b10               |        5 |               3.00 → 1.60 |                   10.0 → 10.0 |                3.2 |    10.0 |     0.0033 |
| b11               |       18 |               4.56 → 1.39 |                   13.0 → 12.7 |                4.2 |    15.1 |     0.0057 |
| b12               |        7 |               5.14 → 2.86 |                   10.0 → 10.0 |                5.7 |    17.4 |     0.0059 |
| b13               |       13 |               1.77 → 1.00 |                     6.0 → 6.0 |                2.6 |     8.2 |     0.0023 |
| b14               |       13 |               1.77 → 1.00 |                     6.0 → 6.0 |                2.6 |     8.2 |     0.0025 |
| b15               |       28 |               3.61 → 1.00 |                   12.0 → 12.0 |                2.7 |    11.0 |     0.0042 |
| **Pooled median** |  **296** |                 **2 → 1** |                             — |                  — |   **8** | **0.0020** |

The synthetic long run has **10006 executed steps**. Shrinking took **2.289s**, 27 replays, 3 → 1 deviations. Its saved prefix still contains 10002 choices because the long FIFO prefix precedes the race. The final program still executes 10006 steps.

These are measured bounded-search results, not proofs of global or exhaustive local minimality. FIFO already exposes b03 and b06, so zero deviations is correct. This corpus is deliberately small and does not establish performance on arbitrary applications. Wall timings vary by host.

Detection measurements

1000 trials per repeat, 5 disjoint seed blocks per strategy. Core defaults, with TaskLeak promoted to FAILURE only for b06. Corpus disabled.

| Bug | Expected oracle | FIFO rate | Random rate | Random median first | Observed min deviations (Random) |
| --- | --- | ---: | ---: | ---: | ---: |
| b01 | invariant | 0.0000 | 0.3788 | 2 | 1 |
| b02 | unhandled_exception | 0.0000 | 0.3788 | 2 | 1 |
| b03 | invariant | 1.0000 | 1.0000 | 1 | 0 |
| b04 | deadlock | 0.0000 | 0.1286 | 7 | 2 |
| b05 | invariant | 0.0000 | 0.0000 | not reached | None |
| b06 | task_leak | 1.0000 | 1.0000 | 1 | 0 |
| b07 | deadlock | 0.0000 | 0.2552 | 2 | 1 |
| b08 | deadlock | 0.0000 | 0.3708 | 3 | 1 |
| b09 | invariant | 0.0000 | 0.2430 | 2 | 1 |
| b10 | deadlock | 0.0000 | 0.1032 | 3 | 1 |
| b11 | time_budget | 0.0000 | 0.0000 | not reached | None |
| b12 | deadlock | 0.0000 | 0.1432 | 2 | 2 |
| b13 | invariant | 0.0000 | 0.1874 | 5 | 1 |
| b14 | invariant | 0.0000 | 0.1874 | 5 | 1 |
| b15 | task_leak | 0.0000 | 0.0000 | not reached | None |
Rates are failing trials / attempted trials for the expected oracle 

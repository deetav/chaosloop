Detection measurements

1000 trials per repeat, 5 disjoint seed blocks per strategy. Core defaults, with TaskLeak promoted to FAILURE only for b06. Corpus disabled.

| Bug | Expected oracle | FIFO rate | Random rate | Random median first | Observed min deviations (Random) |
| --- | --- | ---: | ---: | ---: | ---: |
| b01 | invariant | 0.0000 | 0.3788 | 2 | 1 |
| b02 | unhandled_exception | 0.0000 | 0.3788 | 2 | 1 |
| b03 | invariant | 1.0000 | 1.0000 | 1 | 0 |
Rates are failing trials / attempted trials for the expected oracle 

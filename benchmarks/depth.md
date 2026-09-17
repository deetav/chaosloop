# Observed FIFO-deviation complexity

Measured on CPython 3.13.15; 500 seeds per bug.

These measurements are best verified reproducers, not formal PCT bug depth. Budgeted greedy shrinking does not prove local or global minimality.

| Bug | Previous declaration | Observed minimum | Failing seeds | Distribution                | Steps |
|-----|---------------------:|-----------------:|--------------:|-----------------------------|------:|
| b01 |                    1 |                1 |           184 | {1: 184}                    |     6 |
| b02 |                    1 |                1 |           184 | {1: 184}                    |    10 |
| b03 |                    0 |                0 |           500 | {0: 500}                    |     1 |
| b04 |                    2 |                2 |            72 | {2: 72}                     |     5 |
| b05 |                    1 |                1 |           130 | {1: 49, 2: 51, 3: 9, 4: 21} |    11 |
| b06 |                    0 |                0 |           500 | {0: 500}                    |     4 |
| b07 |                    1 |                1 |           133 | {1: 133}                    |     5 |
| b08 |                    1 |                1 |           177 | {1: 177}                    |     6 |
| b09 |                    1 |                1 |           119 | {1: 92, 2: 27}              |    10 |
| b10 |                    1 |                1 |            36 | {1: 14, 2: 22}              |    10 |
| b11 |                    1 |                1 |           218 | {1: 165, 2: 53}             |     9 |
| b12 |                    2 |                2 |            67 | {2: 37, 3: 19, 4: 5, 5: 6}  |    10 |
| b13 |                    1 |                1 |            79 | {1: 79}                     |     6 |
| b14 |                    1 |                1 |            79 | {1: 79}                     |     6 |
| b15 |                    1 |                1 |           246 | {1: 242, 7: 4}              |    12 |

Distribution counts each failing seed once using its best verified signature. Raw JSON also records signature samples and unverified shrinks.
Steps refers to the complete reproduced execution, including its FIFO tail.

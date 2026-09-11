## 1. Coroutine or factory?
`run(coro, ...)` receives a coroutine object. `trial(scenario, ...)` receives a
zero-argument factory that returns a fresh coroutine. An `async def scenario`
function already is that factory: pass `scenario` to `trial`, and `scenario()` to
`run`.
## 2.  Return value or exception

`run` returns the coroutine's value or propagates the failure. `trial` returns a
`Trial` for scenario outcomes, including assertion failures, cancellation,
deadlock, and exhausted execution budgets. `KeyboardInterrupt` and `SystemExit`
still propagate. Invalid caller configuration is checked separately: a typo in
the API call should not masquerade as an application race.

## 3. Secheduler objects

Schedulers are objects implementing `Scheduler`. `Fifo()`, `Random(seed)`, and
`Replay(decisions, strict=True)` expose their options through normal Python
constructors and types.\
Rejected alternative: strings such as `"random:seed=42"`. These require a parser
and duplicate constructor validation. A future CLI may parse strings at its own
boundary without changing the library contract.

## 4. Where does the seed live?
The random scheduler owns it s private generator/ `seed=42` on a runner is convenience syntax that creates a fresh `Random(42)`. Providing an explicit scheduler and a seed together raises `TypeError`. Omitting both chooses `Fifo()`

## 5. Smallest useful call
`chaosloop.run(main(), seed=42)` is 30 characters and executes one seeded run once
`chaosloop` and the scenario exist. `chaosloop.trial(main, seed=42)` is also 30
characters and returns a reportable result.

## Dependency graph

Standard-library imports are omitted.

```text
__init__                        -> runner, public data/types/errors/schedulers
runner                          -> loop, clock, trace, schedulers, exceptions
loop                            -> compat, clock, trace, schedulers.base, exceptions
compat                          -> exceptions
clock                           -> exceptions
trace                           -> standard library only
schedulers.fifo/random_/replay  -> schedulers.base
schedulers.replay               -> exceptions
schedulers.base                 -> standard library only
exceptions                      -> standard library only
```
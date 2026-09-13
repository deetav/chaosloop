A plain assert at the end of the scenario catches nothing because by then the requirement is satisfied.

```text
stock asyncio + final assertion: passed
FIFO + per step invariant:
FAILED  seed=None  scheduler=Fifo
  [failure] invariant: invariant 'money conserved' violated
    at b03_transfer.py:23
balances=[400, 500], total=900
  0 deviations from the default schedule, 1 steps
  virtual time=0; digest=8879455c6e8eb085

 step      vtime  task          action                                    at
    1      0.000  task-1        task_step<task-1>                         runner.py:208
0 deviations from default in 1 steps

Reproduce: chaosloop.trial(scenario, scheduler=chaosloop.Replay([0], strict=True), max_steps=1000000, max_time=None)
Use the same scenario, inputs, code, Python, and oracle/invariant configuration.
chaosloop: benchmarks.bugs.b03_transfer.scenario
  corpus: 0 replayed; 0 still fail; 0 no longer reproduce (forgotten); 0 changed
  200 fresh trials; 200 failing trials in 1 distinct buckets; stopped=trials

--- Bug 1: 200 occurrences; 0 deviations ---
  invariant: invariant 'money conserved' violated
  at b03_transfer.py:23; seed=0; steps=1
balances=[400, 500], total=900
 step      vtime  task          action                                    at
    1      0.000  task-1        task_step<task-1>                         runner.py:208
0 deviations from default in 1 steps
  Reproduce: chaosloop.trial(scenario, seed=0, max_steps=1000000, max_time=None)
  Also found by: 1, 2, 3, 4, 5 (194 more)
```
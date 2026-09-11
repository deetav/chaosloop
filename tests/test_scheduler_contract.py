from chaosloop.schedulers import Candidate


def fake_candidate(index: int) -> Candidate:
    return Candidate(index * 2 + 2, f"task-{index}", "task_step", "resume", "demo.py:10")

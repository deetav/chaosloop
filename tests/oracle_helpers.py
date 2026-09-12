from chaosloop import Step
from chaosloop.runtime import ErrorInfo, TaskInfo, TraceView


class Context:
    step: int = 3
    vtime: float = 0.0
    ready_count: int = 0
    timers_pending: int = 0
    tasks: tuple[TaskInfo, ...] = ()
    errors: tuple[ErrorInfo, ...] = ()

    def pending_tasks(self):
        return self.tasks

    def captured_errors(self):
        return self.errors

    def trace(self):
        return TraceView(())


def step(n=3, chosen=0):
    return Step(n, 0.0, chosen, max(chosen + 1, 1), "task-1", "task_step", "step", "user.py:12")

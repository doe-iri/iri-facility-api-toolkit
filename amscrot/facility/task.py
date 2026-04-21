"""Async-compatible wrapper for IRI filesystem operation results."""
from __future__ import annotations

TERMINAL_TASK_STATES = frozenset({"completed", "failed", "canceled"})


class Task:
    """Wraps a completed IriFilesystem operation as an async-compatible object.

    IriFilesystem operations are synchronous — they poll the IRI TaskApi
    internally and return the final result. This class wraps that result
    so callers can use the same ``task.wait(); task.result`` pattern as
    amsc-python-client, making a future switch to true async transparent.

    Args:
        result: The operation output (on success).
        error: The exception to raise on ``.result`` access (on failure).
    """

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    @property
    def state(self) -> str:
        """Operation state: 'completed' or 'failed'."""
        return "failed" if self._error else "completed"

    @property
    def is_terminal(self) -> bool:
        """Always True — Task objects are fully resolved at construction."""
        return True

    @property
    def result(self):
        """Operation output. Raises the stored exception if the operation failed."""
        if self._error is not None:
            raise self._error
        return self._result

    def wait(self, timeout: int = 300, poll_interval: int = 2) -> "Task":
        """No-op — the operation is already complete.

        Exists for API compatibility with amsc-python-client. If async
        execution is added later, callers need no changes.
        """
        return self

    def __repr__(self) -> str:
        return f"Task(state={self.state!r})"

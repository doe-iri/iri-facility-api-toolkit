"""Unit tests for amscrot.facility.task.Task."""
import pytest
from amscrot.facility.task import Task, TERMINAL_TASK_STATES


class TestTaskConstants:
    def test_terminal_states_are_frozenset(self):
        assert isinstance(TERMINAL_TASK_STATES, frozenset)

    def test_terminal_states_contents(self):
        assert TERMINAL_TASK_STATES == frozenset({"completed", "failed", "canceled"})


class TestTaskSuccess:
    def test_state_is_completed_on_success(self):
        task = Task(result={"output": "hello"})
        assert task.state == "completed"

    def test_is_terminal_true_on_success(self):
        task = Task(result={"output": "hello"})
        assert task.is_terminal is True

    def test_result_returns_value(self):
        task = Task(result={"output": "hello"})
        assert task.result == {"output": "hello"}

    def test_result_can_be_none(self):
        task = Task(result=None)
        assert task.result is None

    def test_wait_returns_self(self):
        task = Task(result="done")
        returned = task.wait()
        assert returned is task

    def test_wait_ignores_timeout(self):
        task = Task(result="done")
        # Should not raise even with tiny timeout since it's a no-op
        task.wait(timeout=0, poll_interval=0)

    def test_repr_shows_state(self):
        task = Task(result="done")
        assert "completed" in repr(task)


class TestTaskFailure:
    def test_state_is_failed_on_error(self):
        task = Task(error=ValueError("bad"))
        assert task.state == "failed"

    def test_is_terminal_true_on_error(self):
        task = Task(error=ValueError("bad"))
        assert task.is_terminal is True

    def test_result_raises_stored_exception(self):
        exc = RuntimeError("IRI API error")
        task = Task(error=exc)
        with pytest.raises(RuntimeError, match="IRI API error"):
            _ = task.result

    def test_wait_returns_self_on_failure(self):
        task = Task(error=ValueError("bad"))
        returned = task.wait()
        assert returned is task


class TestTaskDefaultState:
    def test_requires_result_or_error(self):
        # Task with neither result nor error defaults to completed with None result
        task = Task()
        assert task.state == "completed"
        assert task.result is None

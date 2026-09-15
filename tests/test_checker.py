"""Tests for the check_service decorator."""

from iotcloud_health.checker import check_service


def test_checker_success_without_previous_failure():
    notifications = []

    def mock_notifier(msg: str) -> bool:
        notifications.append(msg)
        return True

    @check_service("TestService", notifier=mock_notifier)
    def my_check():
        """Sample docstring."""
        return "ok"

    assert my_check.__name__ == "my_check"
    assert my_check.__doc__ == "Sample docstring."

    result = my_check()
    assert result == "ok"
    assert len(notifications) == 0  # No alert if succeeding normally


def test_checker_failure_and_recovery_transitions():
    notifications = []

    def mock_notifier(msg: str) -> bool:
        notifications.append(msg)
        return True

    state = {"should_fail": False}

    @check_service("MockService", notifier=mock_notifier)
    def sample_check():
        if state["should_fail"]:
            raise ValueError("Something broke")
        return "success"

    # 1. Normal success
    res = sample_check()
    assert res == "success"
    assert len(notifications) == 0

    # 2. Service breaks -> should send failure alert
    state["should_fail"] = True
    res = sample_check()
    assert res is None
    assert len(notifications) == 1
    assert "MockService is not working" in notifications[0]

    # 3. Service continues to be broken -> should NOT send duplicate alert
    res = sample_check()
    assert res is None
    assert len(notifications) == 1

    # 4. Service recovers -> should send recovery alert
    state["should_fail"] = False
    res = sample_check()
    assert res == "success"
    assert len(notifications) == 2
    assert "MockService is now working" in notifications[1]

    # 5. Service stays healthy -> should NOT send another alert
    res = sample_check()
    assert res == "success"
    assert len(notifications) == 2


def test_checker_with_health_check_error():
    from iotcloud_health.checker import HealthCheckError

    notifications = []

    def mock_notifier(msg: str) -> bool:
        notifications.append(msg)
        return True

    @check_service("ingestion", notifier=mock_notifier)
    def failing_check():
        raise HealthCheckError("🔴 [M2M Auth Failed] Internal API rejected X-M2M-Token.")

    result = failing_check()
    assert result is None
    assert len(notifications) == 1
    assert "🔴 [M2M Auth Failed]" in notifications[0]


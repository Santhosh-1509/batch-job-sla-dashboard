import pytest

from helpers import job, run
from sla_analysis import analyse_sla


# The job's SLA deadline is 02:00. "Approaching" means the run finished
# on time but within 15 minutes of the deadline.
@pytest.mark.parametrize(
    "end_time,status,expected",
    [
        ("01:30", "COMPLETED", "MET"),
        ("01:44", "COMPLETED", "MET"),
        ("01:45", "COMPLETED", "APPROACHING"),
        ("01:50", "COMPLETED", "APPROACHING"),
        ("02:00", "COMPLETED", "APPROACHING"),
        ("02:01", "COMPLETED", "BREACHED"),
        ("02:30", "FAILED", "BREACHED"),
    ],
)
def test_sla_status_of_finished_runs(build_data, end_time, status, expected):
    build_data(
        jobs=[job("J1", deadline="02:00")],
        history=[run("E1", "J1", "2026-09-01", "01:00", end_time, status)],
    )
    result = analyse_sla()
    assert result.loc[0, "sla_status"] == expected


def test_unfinished_runs_are_pending(build_data):
    build_data(
        jobs=[job("J1")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "", "QUEUED"),
            run("E3", "J1", "2026-09-03", "01:00", "", "RUNNING"),
        ],
    )
    result = analyse_sla().set_index("execution_id")
    assert result.loc["E1", "sla_status"] == "MET"
    assert result.loc["E2", "sla_status"] == "PENDING"
    assert result.loc["E3", "sla_status"] == "PENDING"


def test_violation_flag_is_true_only_for_breaches(build_data):
    build_data(
        jobs=[job("J1", deadline="02:00")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "02:10", "COMPLETED"),
        ],
    )
    result = analyse_sla().set_index("execution_id")
    assert result.loc["E1", "sla_violation"] == False  # noqa: E712
    assert result.loc["E2", "sla_violation"] == True  # noqa: E712


def test_run_crossing_midnight_meets_deadline_on_next_day(build_data):
    # Starts 23:30, ends 00:20 the next day. The 01:00 deadline is also
    # on the next day, so this run is on time.
    build_data(
        jobs=[job("J1", deadline="01:00")],
        history=[run("E1", "J1", "2026-09-01", "23:30", "00:20", "COMPLETED")],
    )
    result = analyse_sla()
    assert result.loc[0, "sla_status"] == "MET"


def test_run_crossing_midnight_can_still_breach(build_data):
    build_data(
        jobs=[job("J1", deadline="01:00")],
        history=[run("E1", "J1", "2026-09-01", "23:30", "01:30", "COMPLETED")],
    )
    result = analyse_sla()
    assert result.loc[0, "sla_status"] == "BREACHED"


def test_run_starting_after_its_deadline_is_breached(build_data):
    # Starts 02:30 and ends 03:15 on the same day. The 02:00 deadline had
    # already passed, so it must NOT be moved to the next day.
    build_data(
        jobs=[job("J1", deadline="02:00")],
        history=[run("E1", "J1", "2026-09-01", "02:30", "03:15", "COMPLETED")],
    )
    result = analyse_sla()
    assert result.loc[0, "sla_status"] == "BREACHED"


def test_midnight_run_with_deadline_before_midnight_is_breached(build_data):
    # Starts 22:00 and ends 01:00 the next day. The 23:30 deadline is on
    # the same evening, so the run is late.
    build_data(
        jobs=[job("J1", deadline="23:30")],
        history=[run("E1", "J1", "2026-09-01", "22:00", "01:00", "COMPLETED")],
    )
    result = analyse_sla()
    assert result.loc[0, "sla_status"] == "BREACHED"
import pytest

from alerts import generate_alerts
from helpers import dep, job, run
from risk_score import calculate_risk_scores
from runtime_analysis import analyse_runtime
from sla_analysis import analyse_sla


def test_dependency_loop_does_not_hang_or_crash(build_data):
    build_data(
        jobs=[job("A"), job("B"), job("C")],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "COMPLETED"),
            run("E2", "B", "2026-09-01", "01:30", "01:50", "COMPLETED"),
            run("E3", "C", "2026-09-01", "02:00", "02:20", "COMPLETED"),
        ],
        dependencies=[dep("A", "B"), dep("B", "C"), dep("C", "A")],
    )
    scores = calculate_risk_scores()
    assert len(scores) == 3
    generate_alerts()


# A missing end time or an unreadable one should be treated as unknown,
# not as a breach and not as a crash.
@pytest.mark.parametrize("bad_end", ["", "abc", "25:99"])
def test_unreadable_end_time_is_treated_as_unknown(build_data, bad_end):
    build_data(
        jobs=[job("J1")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", bad_end, "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "01:30", "COMPLETED"),
        ],
    )
    sla = analyse_sla().set_index("execution_id")
    runtime = analyse_runtime().set_index("execution_id")
    assert sla.loc["E1", "sla_status"] == "PENDING"
    assert runtime.loc["E1", "runtime_status"] == "PENDING"


def test_unknown_status_does_not_crash(build_data):
    build_data(
        jobs=[job("J1")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "WEIRD"),
            run("E2", "J1", "2026-09-02", "01:00", "01:30", "COMPLETED"),
        ],
    )
    analyse_sla()
    analyse_runtime()
    calculate_risk_scores()
    generate_alerts()


def test_zero_max_runtime_does_not_crash(build_data):
    build_data(
        jobs=[job("J1", max_runtime=0)],
        history=[run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED")],
    )
    result = analyse_runtime()
    assert result.loc[0, "runtime_status"] == "MAJOR_OVERRUN"
    calculate_risk_scores()


def test_job_with_no_runs_still_gets_a_score(build_data):
    build_data(
        jobs=[job("J1"), job("J2")],
        history=[run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED")],
    )
    scores = calculate_risk_scores().set_index("job_id")
    assert "J2" in scores.index
    assert 0 <= scores.loc["J2", "risk_score"] <= 100


def test_run_for_unconfigured_job_does_not_crash_alerts(build_data):
    build_data(
        jobs=[job("J1")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "GHOST", "2026-09-01", "01:00", "01:30", "COMPLETED"),
        ],
    )
    generate_alerts()
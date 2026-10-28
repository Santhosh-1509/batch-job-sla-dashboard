import pandas as pd
import pytest

from helpers import job, run
from runtime_analysis import analyse_runtime


# The limit is 60 minutes. Up to 10% over is a minor overrun, more than
# 10% over (above 66 minutes) is a major overrun.
@pytest.mark.parametrize(
    "end_time,expected_status,expected_minutes",
    [
        ("01:50", "WITHIN_LIMIT", 50),
        ("02:00", "WITHIN_LIMIT", 60),
        ("02:03", "MINOR_OVERRUN", 63),
        ("02:06", "MINOR_OVERRUN", 66),
        ("02:07", "MAJOR_OVERRUN", 67),
        ("02:30", "MAJOR_OVERRUN", 90),
    ],
)
def test_runtime_status(build_data, end_time, expected_status,
                        expected_minutes):
    build_data(
        jobs=[job("J1", max_runtime=60)],
        history=[run("E1", "J1", "2026-09-01", "01:00", end_time, "COMPLETED")],
    )
    result = analyse_runtime()
    assert result.loc[0, "runtime_minutes"] == expected_minutes
    assert result.loc[0, "runtime_status"] == expected_status


def test_run_crossing_midnight_has_correct_runtime(build_data):
    build_data(
        jobs=[job("J1", max_runtime=60)],
        history=[run("E1", "J1", "2026-09-01", "23:50", "00:20", "COMPLETED")],
    )
    result = analyse_runtime()
    assert result.loc[0, "runtime_minutes"] == 30
    assert result.loc[0, "runtime_status"] == "WITHIN_LIMIT"


def test_unfinished_runs_have_no_runtime(build_data):
    build_data(
        jobs=[job("J1")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "", "QUEUED"),
            run("E3", "J1", "2026-09-03", "01:00", "", "RUNNING"),
        ],
    )
    result = analyse_runtime().set_index("execution_id")
    assert result.loc["E2", "runtime_status"] == "PENDING"
    assert result.loc["E3", "runtime_status"] == "PENDING"
    assert pd.isna(result.loc["E2", "runtime_minutes"])
    assert bool(result.loc["E2", "runtime_violation"]) is False


def test_violation_flag_counts_only_runs_over_the_limit(build_data):
    build_data(
        jobs=[job("J1", max_runtime=60)],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:50", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "02:00", "COMPLETED"),
            run("E3", "J1", "2026-09-03", "01:00", "02:01", "COMPLETED"),
        ],
    )
    result = analyse_runtime()
    assert int(result["runtime_violation"].sum()) == 1
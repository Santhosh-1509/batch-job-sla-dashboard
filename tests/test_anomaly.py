import numpy as np
import pytest

from anomaly_detection import detect_runtime_anomalies, summarise_job_history
from helpers import job, run, runs_with_runtimes


def test_sudden_spike_is_flagged(build_data):
    build_data(
        jobs=[job("J1", max_runtime=120)],
        history=runs_with_runtimes("J1", [30, 31, 29, 30, 30, 80]),
    )
    result = detect_runtime_anomalies().sort_values("run_date")
    result = result.reset_index(drop=True)
    assert result.loc[5, "anomaly_status"] == "UNUSUALLY_LONG"
    assert (result.loc[:4, "anomaly_status"] == "NORMAL").all()


def test_job_with_too_little_history_is_not_judged(build_data):
    build_data(
        jobs=[job("J1")],
        history=runs_with_runtimes("J1", [30, 31, 29]),
    )
    result = detect_runtime_anomalies()
    assert (result["anomaly_status"] == "INSUFFICIENT_HISTORY").all()


def test_job_with_enough_history_is_judged(build_data):
    build_data(
        jobs=[job("J1")],
        history=runs_with_runtimes("J1", [30, 31, 29, 30]),
    )
    result = detect_runtime_anomalies()
    assert not (result["anomaly_status"] == "INSUFFICIENT_HISTORY").any()


def test_tiny_change_in_a_steady_job_is_not_an_anomaly(build_data):
    # Without the minimum spread, one extra minute in a perfectly steady
    # job would look enormous.
    build_data(
        jobs=[job("J1")],
        history=runs_with_runtimes("J1", [30, 30, 30, 30, 31]),
    )
    result = detect_runtime_anomalies()
    assert (result["anomaly_status"] == "NORMAL").all()
    assert np.isfinite(result["z_score"]).all()


def test_unfinished_run_is_pending(build_data):
    history = runs_with_runtimes("J1", [30, 31, 29, 30, 30])
    history.append(run("J1-E6", "J1", "2026-09-06", "01:00", "", "QUEUED"))
    build_data(jobs=[job("J1")], history=history)
    result = detect_runtime_anomalies().set_index("execution_id")
    assert result.loc["J1-E6", "anomaly_status"] == "PENDING"


@pytest.mark.parametrize(
    "runtimes,expected",
    [
        ([30, 32, 34, 40, 42, 44], "INCREASING"),
        ([30, 30, 30, 30, 30, 30], "STABLE"),
        ([44, 42, 40, 34, 32, 30], "DECREASING"),
        ([30, 32, 34], "NOT_ENOUGH_DATA"),
    ],
)
def test_runtime_trend(build_data, runtimes, expected):
    build_data(
        jobs=[job("J1", max_runtime=120)],
        history=runs_with_runtimes("J1", runtimes),
    )
    history = summarise_job_history(detect_runtime_anomalies())
    assert history.loc[0, "trend"] == expected
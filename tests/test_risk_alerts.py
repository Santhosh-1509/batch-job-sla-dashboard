import pytest

from alerts import LEVELS, generate_alerts
from helpers import dep, job, run, runs_with_runtimes
from risk_score import WEIGHTS, calculate_risk_scores, classify_risk


def test_weights_add_up_to_100():
    assert sum(WEIGHTS.values()) == 100


@pytest.mark.parametrize(
    "score,expected",
    [
        (0, "LOW"),
        (30, "LOW"),
        (31, "MEDIUM"),
        (60, "MEDIUM"),
        (61, "HIGH"),
        (80, "HIGH"),
        (81, "CRITICAL"),
        (100, "CRITICAL"),
    ],
)
def test_risk_level_bands(score, expected):
    assert classify_risk(score) == expected


def healthy_and_troubled_jobs(build_data):
    """GOOD: steady and on time. BAD: slow, late and failing."""
    bad_runs = runs_with_runtimes("BAD", [90] * 6)
    bad_runs[4][5] = "FAILED"
    bad_runs[5][5] = "FAILED"

    build_data(
        jobs=[
            job("GOOD", deadline="03:00", max_runtime=60, criticality="LOW"),
            job("BAD", deadline="02:00", max_runtime=40,
                criticality="CRITICAL"),
        ],
        history=runs_with_runtimes("GOOD", [30] * 6) + bad_runs,
    )


def test_scores_stay_between_0_and_100(build_data):
    healthy_and_troubled_jobs(build_data)
    scores = calculate_risk_scores()
    assert scores["risk_score"].between(0, 100).all()


def test_troubled_job_scores_higher_than_healthy_job(build_data):
    healthy_and_troubled_jobs(build_data)
    scores = calculate_risk_scores().set_index("job_id")
    assert scores.loc["GOOD", "risk_level"] == "LOW"
    assert scores.loc["BAD", "risk_score"] > scores.loc["GOOD", "risk_score"]
    assert scores.loc["BAD", "risk_level"] in ("HIGH", "CRITICAL")


# ---------- Alerts ----------
def alerts_of_type(alerts, alert_type):
    return alerts[alerts["alert_type"] == alert_type]


def failed_star_data(build_data):
    """A failed, and B, C, D (all waiting for A) are still queued."""
    build_data(
        jobs=[job("A", name="UPSTREAM_JOB"), job("B"), job("C"), job("D")],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "FAILED"),
            run("E2", "B", "2026-09-01", "02:00", "", "QUEUED"),
            run("E3", "C", "2026-09-01", "02:00", "", "QUEUED"),
            run("E4", "D", "2026-09-01", "02:00", "", "QUEUED"),
        ],
        dependencies=[dep("A", "B"), dep("A", "C"), dep("A", "D")],
    )


def test_failed_job_gets_an_alert_at_its_criticality(build_data):
    build_data(
        jobs=[job("J1", criticality="MEDIUM")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "01:20", "FAILED"),
        ],
    )
    failed = alerts_of_type(generate_alerts(), "FAILED")
    assert len(failed) == 1
    assert failed.iloc[0]["severity"] == "MEDIUM"


def test_failure_with_many_downstream_jobs_is_raised_one_level(build_data):
    failed_star_data(build_data)
    failed = alerts_of_type(generate_alerts(), "FAILED")
    assert failed.iloc[0]["job_id"] == "A"
    assert failed.iloc[0]["severity"] == "HIGH"


def test_queued_jobs_behind_a_failure_are_blocked(build_data):
    failed_star_data(build_data)
    blocked = alerts_of_type(generate_alerts(), "BLOCKED")
    assert set(blocked["job_id"]) == {"B", "C", "D"}
    assert blocked["message"].str.contains("UPSTREAM_JOB").all()
    assert (blocked["severity"] == "MEDIUM").all()


def test_blocking_reaches_jobs_further_down_the_chain(build_data):
    build_data(
        jobs=[job("A", name="UPSTREAM_JOB"), job("B"), job("C")],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "FAILED"),
            run("E2", "B", "2026-09-01", "02:00", "", "QUEUED"),
            run("E3", "C", "2026-09-01", "02:00", "", "QUEUED"),
        ],
        dependencies=[dep("A", "B"), dep("B", "C")],
    )
    blocked = alerts_of_type(generate_alerts(), "BLOCKED")
    assert set(blocked["job_id"]) == {"B", "C"}


def test_queued_job_is_not_blocked_when_upstream_is_fine(build_data):
    build_data(
        jobs=[job("A"), job("B")],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "COMPLETED"),
            run("E2", "B", "2026-09-01", "02:00", "", "QUEUED"),
        ],
        dependencies=[dep("A", "B")],
    )
    assert alerts_of_type(generate_alerts(), "BLOCKED").empty


def test_sla_breach_alert_uses_the_job_criticality(build_data):
    build_data(
        jobs=[job("J1", deadline="02:00", max_runtime=60,
                  criticality="HIGH")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "02:30", "COMPLETED"),
        ],
    )
    breached = alerts_of_type(generate_alerts(), "SLA_BREACHED")
    assert len(breached) == 1
    assert breached.iloc[0]["severity"] == "HIGH"


def test_healthy_job_has_no_alerts(build_data):
    build_data(
        jobs=[job("J1", deadline="03:00", max_runtime=60, criticality="LOW")],
        history=[
            run("E1", "J1", "2026-09-01", "01:00", "01:30", "COMPLETED"),
            run("E2", "J1", "2026-09-02", "01:00", "01:30", "COMPLETED"),
        ],
    )
    assert generate_alerts().empty


def test_alerts_are_sorted_most_serious_first(build_data):
    failed_star_data(build_data)
    alerts = generate_alerts()
    ranks = [LEVELS.index(level) for level in alerts["severity"]]
    assert ranks == sorted(ranks, reverse=True)
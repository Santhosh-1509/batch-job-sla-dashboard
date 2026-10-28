import pytest

from alerts import generate_alerts
from anomaly_detection import detect_runtime_anomalies
from data_loader import (
    load_dependencies,
    load_execution_history,
    load_job_config,
)
from dependency_engine import analyse_dependency_impact, build_graph
from risk_score import calculate_risk_scores
from root_cause import build_run_issues, trace_root_cause
from runtime_analysis import analyse_runtime
from sla_analysis import analyse_sla


@pytest.fixture(autouse=True)
def use_original_data(monkeypatch):
    """Make sure these tests read the real project data."""
    monkeypatch.delenv("BATCH_DATA_DIR", raising=False)
    monkeypatch.delenv("BATCH_HISTORY_FILE", raising=False)


def test_dataset_sizes():
    assert len(load_job_config()) == 30
    assert len(load_execution_history()) == 180
    assert len(load_dependencies()) == 36


def test_sla_status_counts():
    counts = analyse_sla()["sla_status"].value_counts().to_dict()
    assert counts == {
        "MET": 130,
        "APPROACHING": 32,
        "BREACHED": 13,
        "PENDING": 5,
    }


def test_runtime_status_counts():
    counts = analyse_runtime()["runtime_status"].value_counts().to_dict()
    assert counts == {
        "WITHIN_LIMIT": 90,
        "MAJOR_OVERRUN": 64,
        "MINOR_OVERRUN": 21,
        "PENDING": 5,
    }


def test_anomaly_status_counts():
    counts = (
        detect_runtime_anomalies()["anomaly_status"].value_counts().to_dict()
    )
    assert counts == {
        "NORMAL": 162,
        "UNUSUALLY_LONG": 9,
        "PENDING": 5,
        "UNUSUALLY_SHORT": 4,
    }


def test_risk_level_counts_and_top_job():
    scores = calculate_risk_scores()
    assert scores["risk_level"].value_counts().to_dict() == {
        "MEDIUM": 19,
        "LOW": 6,
        "HIGH": 5,
    }
    top = scores.iloc[0]
    assert top["job_name"] == "ORDER_EVENT_IMPORT"
    assert top["risk_score"] == 71


def test_alert_total_and_most_serious_alert():
    alerts = generate_alerts()
    assert len(alerts) == 34
    first = alerts.iloc[0]
    assert first["severity"] == "CRITICAL"
    assert first["job_name"] == "ORDER_EVENT_IMPORT"


def test_failed_customer_transform_affects_seven_jobs():
    impact = analyse_dependency_impact()
    rows = impact[impact["failed_job_id"] == "JOB003"]
    assert len(rows) == 7
    assert rows["level"].max() == 3


def test_order_transform_trace_reaches_order_event_import():
    runs = build_run_issues()
    _, upstream_map = build_graph(load_dependencies())
    trace = trace_root_cause("JOB014", "2026-09-03", runs, upstream_map)
    assert any(
        item["job_id"] == "JOB013"
        and item["levels_up"] == 1
        and item["is_root"]
        for item in trace
    )
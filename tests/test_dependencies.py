import pandas as pd

from data_loader import load_dependencies
from dependency_engine import (
    analyse_dependency_impact,
    build_graph,
    find_connected_jobs,
)
from helpers import dep, job, run
from root_cause import build_run_issues, trace_root_cause


def graph_from(pairs):
    """Build the two lookups from a list of (upstream, downstream) pairs."""
    table = pd.DataFrame(
        pairs, columns=["upstream_job_id", "downstream_job_id"]
    )
    return build_graph(table)


def test_downstream_chain_levels():
    downstream, _ = graph_from([("A", "B"), ("B", "C"), ("C", "D")])
    assert set(find_connected_jobs("A", downstream)) == {
        ("B", 1), ("C", 2), ("D", 3),
    }


def test_upstream_chain_levels():
    _, upstream = graph_from([("A", "B"), ("B", "C"), ("C", "D")])
    assert set(find_connected_jobs("D", upstream)) == {
        ("C", 1), ("B", 2), ("A", 3),
    }


def test_branching_dependencies_count_each_job_once():
    downstream, _ = graph_from(
        [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]
    )
    found = find_connected_jobs("A", downstream)
    assert len(found) == 3
    assert set(found) == {("B", 1), ("C", 1), ("D", 2)}


def test_dependency_loop_ends_instead_of_running_forever():
    downstream, _ = graph_from([("A", "B"), ("B", "C"), ("C", "A")])
    assert set(find_connected_jobs("A", downstream)) == {("B", 1), ("C", 2)}


def test_job_without_dependencies_has_no_connections():
    downstream, upstream = graph_from([("A", "B")])
    assert find_connected_jobs("B", downstream) == []
    assert find_connected_jobs("A", upstream) == []


def test_failure_impact_lists_downstream_jobs(build_data):
    build_data(
        jobs=[job("A"), job("B"), job("C")],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:10", "FAILED"),
            run("E2", "B", "2026-09-01", "01:20", "01:30", "COMPLETED"),
        ],
        dependencies=[dep("A", "B"), dep("B", "C")],
    )
    impact = analyse_dependency_impact()
    pairs = set(zip(impact["affected_job_id"], impact["level"]))
    assert pairs == {("B", 1), ("C", 2)}
    assert (impact["failed_job_id"] == "A").all()


def test_no_failures_means_no_impact(build_data):
    build_data(
        jobs=[job("A"), job("B")],
        history=[run("E1", "A", "2026-09-01", "01:00", "01:10", "COMPLETED")],
        dependencies=[dep("A", "B")],
    )
    assert analyse_dependency_impact().empty


def trace(job_id, run_date):
    """Root-cause trace for one job on one date."""
    runs = build_run_issues()
    _, upstream_map = build_graph(load_dependencies())
    return trace_root_cause(job_id, run_date, runs, upstream_map)


def test_root_cause_points_to_the_failed_upstream_job(build_data):
    # A failed, B was fine, C breached its SLA. A is the possible cause.
    build_data(
        jobs=[
            job("A", deadline="02:00"),
            job("B", deadline="02:00"),
            job("C", deadline="02:30"),
        ],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "FAILED"),
            run("E2", "B", "2026-09-01", "01:30", "01:50", "COMPLETED"),
            run("E3", "C", "2026-09-01", "02:00", "02:50", "COMPLETED"),
        ],
        dependencies=[dep("A", "B"), dep("B", "C")],
    )
    result = trace("C", "2026-09-01")
    assert len(result) == 1
    assert result[0]["job_id"] == "A"
    assert result[0]["levels_up"] == 2
    assert result[0]["is_root"] is True


def test_root_cause_marks_only_the_deepest_problem_as_root(build_data):
    # A failed and B breached its SLA, so C's possible root cause is A.
    build_data(
        jobs=[
            job("A", deadline="02:00"),
            job("B", deadline="01:40"),
            job("C", deadline="02:30"),
        ],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "FAILED"),
            run("E2", "B", "2026-09-01", "01:30", "01:55", "COMPLETED"),
            run("E3", "C", "2026-09-01", "02:00", "02:50", "COMPLETED"),
        ],
        dependencies=[dep("A", "B"), dep("B", "C")],
    )
    result = trace("C", "2026-09-01")
    roots = [item["job_id"] for item in result if item["is_root"]]
    others = [item["job_id"] for item in result if not item["is_root"]]
    assert roots == ["A"]
    assert others == ["B"]


def test_no_upstream_problem_means_no_trace(build_data):
    build_data(
        jobs=[
            job("A", deadline="02:00"),
            job("B", deadline="02:00"),
            job("C", deadline="02:30"),
        ],
        history=[
            run("E1", "A", "2026-09-01", "01:00", "01:20", "COMPLETED"),
            run("E2", "B", "2026-09-01", "01:30", "01:50", "COMPLETED"),
            run("E3", "C", "2026-09-01", "02:00", "02:50", "COMPLETED"),
        ],
        dependencies=[dep("A", "B"), dep("B", "C")],
    )
    assert trace("C", "2026-09-01") == []
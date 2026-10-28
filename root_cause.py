import pandas as pd

from data_loader import load_dependencies
from dependency_engine import build_graph, find_connected_jobs
from sla_analysis import analyse_sla
from runtime_analysis import analyse_runtime


def build_run_issues():
    """Create one row per execution with a text list of its problems.

    Possible problems: FAILED, SLA_BREACHED, MAJOR_RUNTIME_OVERRUN.
    An empty text means the run had no problem.
    """
    sla = analyse_sla()[
        [
            "execution_id",
            "job_id",
            "job_name",
            "run_date",
            "status",
            "sla_status",
        ]
    ]
    runtime = analyse_runtime()[["execution_id", "runtime_status"]]

    runs = sla.merge(runtime, on="execution_id", how="left")

    # Use the same plain text date format everywhere (YYYY-MM-DD).
    runs["run_date"] = pd.to_datetime(runs["run_date"]).dt.strftime(
        "%Y-%m-%d"
    )

    issues = []
    for _, row in runs.iterrows():
        found = []
        if row["status"] == "FAILED":
            found.append("FAILED")
        if row["sla_status"] == "BREACHED":
            found.append("SLA_BREACHED")
        if row["runtime_status"] == "MAJOR_OVERRUN":
            found.append("MAJOR_RUNTIME_OVERRUN")
        issues.append(", ".join(found))

    runs["issues"] = issues
    return runs


def trace_root_cause(job_id, run_date, runs, upstream_map):
    """Trace upstream from one job on one date.

    Returns a list of upstream jobs that had problems on that date.
    Each item says how many levels up it is and whether it is a root
    (a problem job whose own upstream jobs had no problem).
    """
    day = runs[(runs["run_date"] == run_date) & (runs["issues"] != "")]
    problem_jobs = dict(zip(day["job_id"], day["issues"]))
    names = dict(zip(runs["job_id"], runs["job_name"]))

    upstream_jobs = find_connected_jobs(job_id, upstream_map)

    trace = []
    for upstream_id, level in upstream_jobs:
        if upstream_id not in problem_jobs:
            continue

        # Does this problem job itself have problem jobs above it?
        above = find_connected_jobs(upstream_id, upstream_map)
        has_problem_above = any(
            parent_id in problem_jobs for parent_id, _ in above
        )

        trace.append(
            {
                "job_id": upstream_id,
                "job_name": names.get(upstream_id),
                "levels_up": level,
                "issues": problem_jobs[upstream_id],
                "is_root": not has_problem_above,
            }
        )

    return trace


def summarise_root_causes():
    """Trace every run that failed or breached its SLA."""
    dependencies = load_dependencies()
    _, upstream_map = build_graph(dependencies)

    runs = build_run_issues()

    focus = runs[
        runs["issues"].str.contains("FAILED")
        | runs["issues"].str.contains("SLA_BREACHED")
    ]

    rows = []
    for _, run in focus.iterrows():
        trace = trace_root_cause(
            run["job_id"], run["run_date"], runs, upstream_map
        )
        roots = [item for item in trace if item["is_root"]]

        base = {
            "run_date": run["run_date"],
            "job": f"{run['job_id']} {run['job_name']}",
            "issues": run["issues"],
        }

        if roots:
            for root in roots:
                rows.append(
                    {
                        **base,
                        "possible_root_cause": (
                            f"{root['job_id']} {root['job_name']}"
                        ),
                        "root_issues": root["issues"],
                        "levels_up": root["levels_up"],
                    }
                )
        else:
            rows.append(
                {
                    **base,
                    "possible_root_cause": "(none - problem starts here)",
                    "root_issues": "",
                    "levels_up": 0,
                }
            )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    summary = summarise_root_causes()

    print("ROOT-CAUSE TRACING")
    print("------------------")
    print(
        "Runs that failed or breached SLA, with the possible upstream "
        "cause on the same date.\n"
    )

    if summary.empty:
        print("No failed or SLA-breached runs found.")
    else:
        summary = summary.sort_values(["run_date", "job"])
        print(summary.to_string(index=False))

        with_cause = summary[summary["levels_up"] > 0]
        print(f"\nRuns traced: {summary['job'].nunique()} job(s)")
        print(f"Rows with an upstream cause found: {len(with_cause)}")
from collections import deque

import pandas as pd

from data_loader import (
    load_job_config,
    load_execution_history,
    load_dependencies,
)


def build_graph(dependencies):
    """Turn the dependency table into two lookup dictionaries.

    downstream_map: job -> list of jobs that wait for it
    upstream_map:   job -> list of jobs it waits for
    """
    downstream_map = {}
    upstream_map = {}

    for _, row in dependencies.iterrows():
        upstream = str(row["upstream_job_id"]).strip()
        downstream = str(row["downstream_job_id"]).strip()

        downstream_map.setdefault(upstream, []).append(downstream)
        upstream_map.setdefault(downstream, []).append(upstream)

    return downstream_map, upstream_map


def find_connected_jobs(start_job, graph):
    """Walk the graph from start_job and return (job_id, level) pairs.

    Level 1 = directly connected, level 2 = one step further, and so on.
    A 'visited' set stops the walk if the data contains a loop.
    """
    visited = {start_job}
    queue = deque([(start_job, 0)])
    found = []

    while queue:
        current_job, level = queue.popleft()

        for next_job in graph.get(current_job, []):
            if next_job not in visited:
                visited.add(next_job)
                found.append((next_job, level + 1))
                queue.append((next_job, level + 1))

    return found


def analyse_dependency_impact():
    """For every job that has failed, list the downstream jobs it affects."""

    jobs = load_job_config()
    executions = load_execution_history()
    dependencies = load_dependencies()

    downstream_map, _ = build_graph(dependencies)

    job_names = dict(zip(jobs["job_id"], jobs["job_name"]))
    job_criticality = dict(zip(jobs["job_id"], jobs["criticality"]))

    failed = executions[executions["status"] == "FAILED"]
    failed_counts = failed.groupby("job_id").size()

    rows = []
    for failed_job_id, failed_runs in failed_counts.items():
        affected_jobs = find_connected_jobs(failed_job_id, downstream_map)

        for affected_id, level in affected_jobs:
            rows.append(
                {
                    "failed_job_id": failed_job_id,
                    "failed_job_name": job_names.get(failed_job_id),
                    "failed_runs": failed_runs,
                    "affected_job_id": affected_id,
                    "affected_job_name": job_names.get(affected_id),
                    "level": level,
                    "affected_criticality": job_criticality.get(affected_id),
                }
            )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    jobs = load_job_config()
    dependencies = load_dependencies()
    downstream_map, upstream_map = build_graph(dependencies)

    print("DEPENDENCY ENGINE")
    print("-----------------")
    print(f"Dependency links: {len(dependencies)}")
    print(f"Jobs that have downstream jobs: {len(downstream_map)}")
    print(f"Jobs that have upstream jobs: {len(upstream_map)}")

    impact = analyse_dependency_impact()

    print("\nFAILURE IMPACT")
    print("--------------")
    if impact.empty:
        print("No failed executions with downstream impact.")
    else:
        for failed_job_id, group in impact.groupby("failed_job_id"):
            first = group.iloc[0]
            print(
                f"\n{failed_job_id} {first['failed_job_name']} "
                f"(failed {first['failed_runs']} time(s)) "
                f"affects {len(group)} downstream job(s):"
            )
            print(
                group[
                    [
                        "level",
                        "affected_job_id",
                        "affected_job_name",
                        "affected_criticality",
                    ]
                ]
                .sort_values("level")
                .to_string(index=False)
            )
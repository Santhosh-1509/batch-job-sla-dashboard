import pandas as pd

from data_loader import load_job_config, load_execution_history


def analyse_runtime():
    """Calculate execution duration and identify runtime violations."""

    jobs = load_job_config()
    executions = load_execution_history()

    # Join each execution with its job's runtime limit and criticality.
    results = executions.merge(
        jobs[
            [
                "job_id",
                "job_name",
                "max_runtime_minutes",
                "criticality",
            ]
        ],
        on="job_id",
        how="left",
    )

    # Convert start and end times into minutes after midnight.
    results["start_minutes"] = pd.to_datetime(
        results["start_time"], format="%H:%M", errors="coerce"
    ).dt.hour * 60 + pd.to_datetime(
        results["start_time"], format="%H:%M", errors="coerce"
    ).dt.minute

    results["end_minutes"] = pd.to_datetime(
        results["end_time"], format="%H:%M", errors="coerce"
    ).dt.hour * 60 + pd.to_datetime(
        results["end_time"], format="%H:%M", errors="coerce"
    ).dt.minute

    # Calculate runtime. Add 24 hours when an execution crosses midnight.
    results["runtime_minutes"] = (
        results["end_minutes"] - results["start_minutes"]
    ) % 1440

    # Queued and running jobs may not have a completed runtime yet.
    unfinished = results["status"].isin(["QUEUED", "RUNNING"])
    results.loc[unfinished, "runtime_minutes"] = pd.NA

    # Compare completed/failed execution durations with the configured limit.
    results["runtime_violation"] = (
        results["runtime_minutes"].notna()
        & (
            results["runtime_minutes"]
            > results["max_runtime_minutes"]
        )
    )

    # Make sure runtime is a proper number (blank for unfinished jobs).
    results["runtime_minutes"] = pd.to_numeric(
        results["runtime_minutes"], errors="coerce"
    )

    # How far over the limit was the run, as a percentage?
    results["runtime_overrun_pct"] = (
        (results["runtime_minutes"] - results["max_runtime_minutes"])
        / results["max_runtime_minutes"]
        * 100
    ).round(1)

    # Give every run a severity level.
    has_runtime = results["runtime_minutes"].notna()
    overrun = results["runtime_overrun_pct"]

    results["runtime_status"] = "PENDING"
    results.loc[has_runtime, "runtime_status"] = "WITHIN_LIMIT"
    results.loc[
        has_runtime & (overrun > 0) & (overrun <= 10), "runtime_status"
    ] = "MINOR_OVERRUN"
    results.loc[
        has_runtime & (overrun > 10), "runtime_status"
    ] = "MAJOR_OVERRUN"

    return results


if __name__ == "__main__":
    results = analyse_runtime()

    finished = results[results["runtime_minutes"].notna()]
    violations = finished[finished["runtime_violation"]]
    major = finished[finished["runtime_status"] == "MAJOR_OVERRUN"]

    print("RUNTIME ANALYSIS")
    print("----------------")
    print(f"Total execution records: {len(results)}")
    print(f"Finished executions: {len(finished)}")
    print(f"Runtime violations (any overrun): {len(violations)}")
    print(f"Major overruns (more than 10% over): {len(major)}")

    print("\nRuntime status counts:")
    print(results["runtime_status"].value_counts().to_string())

    print("\nMajor overruns (most serious first):")
    if major.empty:
        print("No major overruns found.")
    else:
        print(
            major.sort_values("runtime_overrun_pct", ascending=False)[
                [
                    "execution_id",
                    "job_name",
                    "run_date",
                    "runtime_minutes",
                    "max_runtime_minutes",
                    "runtime_overrun_pct",
                    "criticality",
                ]
            ]
            .head(15)
            .to_string(index=False)
        )
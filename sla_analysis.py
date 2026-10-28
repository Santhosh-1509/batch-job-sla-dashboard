import pandas as pd

from data_loader import load_job_config, load_execution_history

# Dates and clock times are combined using this exact format (HH:MM).
DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def analyse_sla():
    """Check whether finished jobs completed by their SLA deadline."""

    jobs = load_job_config()
    executions = load_execution_history()

    results = executions.merge(
        jobs[
            [
                "job_id",
                "job_name",
                "sla_deadline",
                "criticality",
            ]
        ],
        on="job_id",
        how="left",
    )

    # Treat blank end times as "missing", not as empty text.
    results["end_time"] = results["end_time"].replace("", pd.NA)

    # Parse the run date and the start/end clock times.
    results["run_date"] = pd.to_datetime(
        results["run_date"], errors="coerce"
    )
    day_text = results["run_date"].dt.strftime("%Y-%m-%d")

    # Unreadable or missing times become "not a time" (NaT).
    results["start_datetime"] = pd.to_datetime(
        day_text + " " + results["start_time"],
        format=DATETIME_FORMAT,
        errors="coerce",
    )

    results["end_datetime"] = pd.to_datetime(
        day_text + " " + results["end_time"],
        format=DATETIME_FORMAT,
        errors="coerce",
    )

    # If the end clock time is earlier than the start time,
    # treat the execution as crossing midnight.
    crosses_midnight = (
        results["end_datetime"].notna()
        & results["start_datetime"].notna()
        & (
            results["end_datetime"]
            < results["start_datetime"]
        )
    )

    results.loc[crosses_midnight, "end_datetime"] += pd.Timedelta(
        days=1
    )

    results["sla_deadline_datetime"] = pd.to_datetime(
        day_text + " " + results["sla_deadline"],
        format=DATETIME_FORMAT,
        errors="coerce",
    )

    # For a run that crosses midnight, a deadline that is earlier on the
    # clock than the start time belongs to the next day.
    # Example: start 23:30, end 00:20, deadline 01:00 -> deadline is 01:00
    # the next day, so the run is on time.
    deadline_is_next_day = crosses_midnight & (
        results["sla_deadline_datetime"] < results["start_datetime"]
    )
    results.loc[deadline_is_next_day, "sla_deadline_datetime"] += pd.Timedelta(
        days=1
    )

    # Only completed or failed executions have a final completion time.
    finished = results["status"].isin(["COMPLETED", "FAILED"])

    results["sla_violation"] = pd.NA
    results.loc[finished, "sla_violation"] = (
        results.loc[finished, "end_datetime"]
        > results.loc[finished, "sla_deadline_datetime"]
    )

    results["sla_violation"] = results["sla_violation"].astype("boolean")

    # Work out the SLA status of each execution.
    # APPROACHING = finished on time, but within 15 minutes of the deadline.
    margin = pd.Timedelta(minutes=15)
    on_time = finished & (
        results["end_datetime"] <= results["sla_deadline_datetime"]
    )
    breached = finished & (
        results["end_datetime"] > results["sla_deadline_datetime"]
    )
    approaching = on_time & (
        results["sla_deadline_datetime"] - results["end_datetime"] <= margin
    )

    results["sla_status"] = "PENDING"
    results.loc[on_time, "sla_status"] = "MET"
    results.loc[approaching, "sla_status"] = "APPROACHING"
    results.loc[breached, "sla_status"] = "BREACHED"

    return results


if __name__ == "__main__":
    results = analyse_sla()

    finished = results[
        results["status"].isin(["COMPLETED", "FAILED"])
    ]

    violations = finished[finished["sla_violation"] == True]

    print("SLA ANALYSIS")
    print("------------")
    print(f"Total execution records: {len(results)}")
    print(f"Finished executions: {len(finished)}")
    print(f"SLA violations: {len(violations)}")

    if len(finished) > 0:
        compliance = (
            (len(finished) - len(violations))
            / len(finished)
            * 100
        )
        print(f"SLA compliance: {compliance:.2f}%")

    print("\nSLA status counts:")
    print(results["sla_status"].value_counts().to_string())

    print("\nSLA violation details:")
    if violations.empty:
        print("No SLA violations found.")
    else:
        print(
            violations[
                [
                    "execution_id",
                    "job_name",
                    "run_date",
                    "end_datetime",
                    "sla_deadline_datetime",
                    "criticality",
                ]
            ].to_string(index=False)
        )
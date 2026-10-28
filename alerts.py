import pandas as pd

from data_loader import load_dependencies
from dependency_engine import build_graph, find_connected_jobs
from sla_analysis import analyse_sla
from anomaly_detection import detect_runtime_anomalies
from risk_score import calculate_risk_scores

# Alert levels, from least to most serious.
LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# A failed job with at least this many downstream jobs is raised one level.
DOWNSTREAM_ESCALATION = 3

ALERT_COLUMNS = [
    "severity",
    "alert_type",
    "job_id",
    "job_name",
    "run_date",
    "message",
]


def shift_level(level, steps):
    """Move a level up (positive steps) or down (negative steps)."""
    index = LEVELS.index(level) + steps
    index = max(0, min(index, len(LEVELS) - 1))
    return LEVELS[index]


def make_alert(row, alert_type, severity, message):
    """Build one alert as a dictionary."""
    return {
        "severity": severity,
        "alert_type": alert_type,
        "job_id": row["job_id"],
        "job_name": row["job_name"],
        "run_date": row["run_date"].strftime("%Y-%m-%d"),
        "message": message,
    }


def generate_alerts():
    """Create alerts from each job's latest run and its risk score."""

    anomalies = detect_runtime_anomalies()
    sla = analyse_sla()[["execution_id", "sla_status"]]
    runs = anomalies.merge(sla, on="execution_id", how="left")

    scores = calculate_risk_scores().set_index("job_id")

    # Lookup of who each job waits for (used for BLOCKED alerts).
    _, upstream_map = build_graph(load_dependencies())

    # Keep only the most recent run of every job.
    latest = (
        runs.sort_values(["job_id", "run_date"]).groupby("job_id").tail(1)
    )
    latest_status = dict(zip(latest["job_id"], latest["status"]))
    job_names = dict(zip(latest["job_id"], latest["job_name"]))

    alerts = []

    for _, row in latest.iterrows():
        job_id = row["job_id"]

        # A run for a job that is not in the job configuration cannot be
        # scored, so it is skipped. validate_data.py reports such runs.
        if job_id not in scores.index:
            continue

        base = str(row["criticality"]).strip().upper()

        downstream = int(scores.loc[job_id, "downstream_jobs"])
        risk_level = scores.loc[job_id, "risk_level"]
        risk_score = scores.loc[job_id, "risk_score"]

        # Alert 1: the job failed.
        if row["status"] == "FAILED":
            severity = base
            if downstream >= DOWNSTREAM_ESCALATION:
                severity = shift_level(base, 1)
            if downstream > 0:
                message = (
                    f"Job failed. {downstream} downstream job(s) "
                    f"may be affected."
                )
            else:
                message = "Job failed."
            alerts.append(make_alert(row, "FAILED", severity, message))

        # Alert 2: the job has not started because an upstream job failed.
        if row["status"] == "QUEUED":
            failed_upstream = [
                upstream_id
                for upstream_id, _ in find_connected_jobs(job_id, upstream_map)
                if latest_status.get(upstream_id) == "FAILED"
            ]
            if failed_upstream:
                names = ", ".join(
                    f"{upstream_id} {job_names.get(upstream_id)}"
                    for upstream_id in sorted(failed_upstream)
                )
                alerts.append(
                    make_alert(
                        row,
                        "BLOCKED",
                        base,
                        f"Not started: waiting on failed upstream job(s): "
                        f"{names}.",
                    )
                )

        # Alert 3: the SLA deadline was missed.
        if row["sla_status"] == "BREACHED":
            alerts.append(
                make_alert(
                    row,
                    "SLA_BREACHED",
                    base,
                    "Job finished after its SLA deadline.",
                )
            )

        # Alert 4: finished on time, but very close to the deadline.
        if row["sla_status"] == "APPROACHING":
            alerts.append(
                make_alert(
                    row,
                    "SLA_APPROACHING",
                    shift_level(base, -1),
                    "Job finished within 15 minutes of its SLA deadline.",
                )
            )

        # Alert 5: runtime far above the configured limit.
        if row["runtime_status"] == "MAJOR_OVERRUN":
            message = (
                f"Ran {row['runtime_minutes']:.0f} min against a limit of "
                f"{row['max_runtime_minutes']} min "
                f"(+{row['runtime_overrun_pct']}%)."
            )
            alerts.append(
                make_alert(
                    row,
                    "MAJOR_RUNTIME_OVERRUN",
                    shift_level(base, -1),
                    message,
                )
            )

        # Alert 6: runtime unusually long compared with the job's history.
        if row["anomaly_status"] == "UNUSUALLY_LONG":
            message = (
                f"Runtime is {row['z_score']} spreads above this job's "
                f"usual runtime."
            )
            alerts.append(
                make_alert(
                    row,
                    "UNUSUAL_RUNTIME",
                    shift_level(base, -1),
                    message,
                )
            )

        # Alert 7: the job's overall risk score is high.
        if risk_level in ("HIGH", "CRITICAL"):
            alerts.append(
                make_alert(
                    row,
                    "HIGH_RISK_JOB",
                    risk_level,
                    f"Job risk score is {risk_score} ({risk_level}).",
                )
            )

    if not alerts:
        return pd.DataFrame(columns=ALERT_COLUMNS)

    table = pd.DataFrame(alerts)
    table["rank"] = table["severity"].map(LEVELS.index)
    table = table.sort_values(
        ["rank", "job_name"], ascending=[False, True]
    ).drop(columns="rank")

    return table[ALERT_COLUMNS].reset_index(drop=True)


if __name__ == "__main__":
    alerts = generate_alerts()

    print("PRIORITISED ALERTS")
    print("------------------")
    print("Based on each job's latest run and its risk score.")

    if alerts.empty:
        print("\nNo alerts.")
    else:
        print(f"\nTotal alerts: {len(alerts)}")

        print("\nAlerts by severity:")
        counts = alerts["severity"].value_counts()
        for level in reversed(LEVELS):
            print(f"  {level:<9}{int(counts.get(level, 0))}")

        print("\nAlerts by type:")
        print(alerts["alert_type"].value_counts().to_string())

        print("\nTop 20 alerts:")
        print(alerts.head(20).to_string(index=False))
import pandas as pd

from data_loader import load_job_config, load_dependencies
from dependency_engine import build_graph, find_connected_jobs
from sla_analysis import analyse_sla
from anomaly_detection import detect_runtime_anomalies, summarise_job_history

# Weights: how many of the 100 points each factor can contribute.
WEIGHTS = {
    "failure": 25,
    "sla": 25,
    "runtime": 20,
    "dependency": 15,
    "criticality": 15,
}

# How serious each criticality label is (0 to 1).
CRITICALITY_POINTS = {
    "LOW": 0.25,
    "MEDIUM": 0.5,
    "HIGH": 0.75,
    "CRITICAL": 1.0,
}

# Number of failures that counts as the maximum failure score.
FAILURES_FOR_FULL_SCORE = 2

# Share of runs breaching SLA that earns the full SLA points.
SLA_FULL_SHARE = 0.5


def classify_risk(score):
    """Turn a 0-100 score into a risk level."""
    if score <= 30:
        return "LOW"
    if score <= 60:
        return "MEDIUM"
    if score <= 80:
        return "HIGH"
    return "CRITICAL"


def calculate_risk_scores():
    """Calculate a 0-100 risk score for every job."""

    jobs = load_job_config()
    dependencies = load_dependencies()
    downstream_map, _ = build_graph(dependencies)

    # One table with SLA status, runtime status and anomaly status per run.
    anomalies = detect_runtime_anomalies()
    sla = analyse_sla()[["execution_id", "sla_status"]]
    runs = anomalies.merge(sla, on="execution_id", how="left")

    # Trend per job (INCREASING, STABLE, ...).
    history = summarise_job_history(anomalies)
    trend_lookup = dict(zip(history["job_id"], history["trend"]))

    # How many jobs would be affected downstream by each job.
    downstream_counts = {
        job_id: len(find_connected_jobs(job_id, downstream_map))
        for job_id in jobs["job_id"]
    }
    max_downstream = max(max(downstream_counts.values()), 1)

    rows = []
    for _, job in jobs.iterrows():
        job_id = job["job_id"]

        # Only finished runs count (COMPLETED or FAILED).
        job_runs = runs[
            (runs["job_id"] == job_id)
            & (runs["status"].isin(["COMPLETED", "FAILED"]))
        ]
        finished = len(job_runs)

        failed = int((job_runs["status"] == "FAILED").sum())
        breached = int((job_runs["sla_status"] == "BREACHED").sum())
        approaching = int((job_runs["sla_status"] == "APPROACHING").sum())
        major = int((job_runs["runtime_status"] == "MAJOR_OVERRUN").sum())
        minor = int((job_runs["runtime_status"] == "MINOR_OVERRUN").sum())
        unusual_long = bool(
            (job_runs["anomaly_status"] == "UNUSUALLY_LONG").any()
        )
        trend = trend_lookup.get(job_id, "NOT_ENOUGH_DATA")

        # Factor 1: failure history (0 to 1)
        failure_factor = min(failed / FAILURES_FOR_FULL_SCORE, 1.0)

        # Factor 2: SLA risk (0 to 1)
        if finished:
            sla_factor = min(
                (breached + 0.5 * approaching) / finished / SLA_FULL_SHARE,
                1.0,
            )
        else:
            sla_factor = 0.0

        # Factor 3: runtime behaviour (0 to 1)
        if finished:
            overrun_part = min((major + 0.5 * minor) / finished, 1.0)
        else:
            overrun_part = 0.0
        trend_part = 1.0 if trend == "INCREASING" else 0.0
        anomaly_part = 1.0 if unusual_long else 0.0
        runtime_factor = (
            0.6 * overrun_part + 0.2 * trend_part + 0.2 * anomaly_part
        )

        # Factor 4: dependency impact (0 to 1)
        dependency_factor = downstream_counts[job_id] / max_downstream

        # Factor 5: job criticality (0 to 1)
        criticality = str(job["criticality"]).strip().upper()
        criticality_factor = CRITICALITY_POINTS.get(criticality, 0.25)

        # Points contributed by each factor.
        failure_pts = WEIGHTS["failure"] * failure_factor
        sla_pts = WEIGHTS["sla"] * sla_factor
        runtime_pts = WEIGHTS["runtime"] * runtime_factor
        dependency_pts = WEIGHTS["dependency"] * dependency_factor
        criticality_pts = WEIGHTS["criticality"] * criticality_factor

        score = round(
            failure_pts
            + sla_pts
            + runtime_pts
            + dependency_pts
            + criticality_pts
        )

        rows.append(
            {
                "job_id": job_id,
                "job_name": job["job_name"],
                "criticality": criticality,
                "risk_score": score,
                "risk_level": classify_risk(score),
                "failure_pts": round(failure_pts, 1),
                "sla_pts": round(sla_pts, 1),
                "runtime_pts": round(runtime_pts, 1),
                "dependency_pts": round(dependency_pts, 1),
                "criticality_pts": round(criticality_pts, 1),
                "failed_runs": failed,
                "sla_breaches": breached,
                "major_overruns": major,
                "trend": trend,
                "downstream_jobs": downstream_counts[job_id],
            }
        )

    scores = pd.DataFrame(rows)
    return scores.sort_values(
        ["risk_score", "criticality_pts"], ascending=False
    ).reset_index(drop=True)


if __name__ == "__main__":
    scores = calculate_risk_scores()

    print("OPERATIONAL RISK SCORES")
    print("-----------------------")
    print(
        "Weights: "
        + ", ".join(f"{name} {value}" for name, value in WEIGHTS.items())
        + " (total 100)"
    )

    print("\nRisk level counts:")
    print(scores["risk_level"].value_counts().to_string())

    print("\nTop 15 jobs by risk score:")
    print(
        scores[
            [
                "job_id",
                "job_name",
                "criticality",
                "risk_score",
                "risk_level",
                "failure_pts",
                "sla_pts",
                "runtime_pts",
                "dependency_pts",
                "criticality_pts",
            ]
        ]
        .head(15)
        .to_string(index=False)
    )

    top = scores.iloc[0]
    print(f"\nWhy is {top['job_name']} ranked first?")
    print(f"  Failure history : {top['failure_pts']} of {WEIGHTS['failure']}"
          f"  ({top['failed_runs']} failed run(s))")
    print(f"  SLA risk        : {top['sla_pts']} of {WEIGHTS['sla']}"
          f"  ({top['sla_breaches']} breach(es))")
    print(f"  Runtime         : {top['runtime_pts']} of {WEIGHTS['runtime']}"
          f"  ({top['major_overruns']} major overrun(s), trend {top['trend']})")
    print(f"  Dependency      : {top['dependency_pts']} of {WEIGHTS['dependency']}"
          f"  ({top['downstream_jobs']} downstream job(s))")
    print(f"  Criticality     : {top['criticality_pts']} of {WEIGHTS['criticality']}"
          f"  ({top['criticality']})")
    print(f"  TOTAL           : {top['risk_score']} -> {top['risk_level']}")
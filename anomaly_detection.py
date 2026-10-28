import numpy as np
import pandas as pd

from runtime_analysis import analyse_runtime

# Settings (easy to change and easy to explain in the dissertation)
MIN_HISTORY = 3        # minimum number of other finished runs needed
Z_THRESHOLD = 2.0      # how many "spreads" away counts as unusual
MIN_STD_PCT = 0.05     # spread is never smaller than 5% of the average


def detect_runtime_anomalies():
    """Compare every run with the same job's other finished runs."""

    results = analyse_runtime().copy()
    results["run_date"] = pd.to_datetime(results["run_date"], errors="coerce")
    results = results.sort_values(["job_id", "run_date"]).reset_index(drop=True)

    baseline_avgs = []
    baseline_stds = []
    z_scores = []
    statuses = []

    for _, row in results.iterrows():

        # Unfinished runs have no runtime yet.
        if pd.isna(row["runtime_minutes"]):
            baseline_avgs.append(np.nan)
            baseline_stds.append(np.nan)
            z_scores.append(np.nan)
            statuses.append("PENDING")
            continue

        # The same job's other finished runs form the baseline.
        others = results[
            (results["job_id"] == row["job_id"])
            & (results["execution_id"] != row["execution_id"])
            & (results["runtime_minutes"].notna())
        ]["runtime_minutes"].astype(float)

        if len(others) < MIN_HISTORY:
            baseline_avgs.append(np.nan)
            baseline_stds.append(np.nan)
            z_scores.append(np.nan)
            statuses.append("INSUFFICIENT_HISTORY")
            continue

        avg = others.mean()
        spread = max(others.std(), MIN_STD_PCT * avg)
        z = (float(row["runtime_minutes"]) - avg) / spread

        baseline_avgs.append(round(avg, 1))
        baseline_stds.append(round(spread, 1))
        z_scores.append(round(z, 2))

        if z >= Z_THRESHOLD:
            statuses.append("UNUSUALLY_LONG")
        elif z <= -Z_THRESHOLD:
            statuses.append("UNUSUALLY_SHORT")
        else:
            statuses.append("NORMAL")

    results["baseline_avg"] = baseline_avgs
    results["baseline_spread"] = baseline_stds
    results["z_score"] = z_scores
    results["anomaly_status"] = statuses

    return results


def summarise_job_history(results):
    """One row per job: average, spread, longest run and trend."""

    finished = results[results["runtime_minutes"].notna()]
    rows = []

    for job_id, group in finished.groupby("job_id"):
        group = group.sort_values("run_date")
        times = group["runtime_minutes"].astype(float).tolist()

        avg = sum(times) / len(times)
        spread = group["runtime_minutes"].astype(float).std()

        # Trend: average of the last 3 runs compared with the first 3.
        trend_pct = np.nan
        trend = "NOT_ENOUGH_DATA"
        if len(times) >= 6:
            first = sum(times[:3]) / 3
            last = sum(times[-3:]) / 3
            trend_pct = round((last - first) / first * 100, 1)
            if trend_pct > 5:
                trend = "INCREASING"
            elif trend_pct < -5:
                trend = "DECREASING"
            else:
                trend = "STABLE"

        rows.append(
            {
                "job_id": job_id,
                "job_name": group["job_name"].iloc[0],
                "runs": len(times),
                "avg_runtime": round(avg, 1),
                "spread": round(spread, 1) if pd.notna(spread) else np.nan,
                "max_runtime": max(times),
                "limit": group["max_runtime_minutes"].iloc[0],
                "trend_pct": trend_pct,
                "trend": trend,
            }
        )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    results = detect_runtime_anomalies()

    print("RUNTIME ANOMALY DETECTION")
    print("-------------------------")
    print(
        f"Rule: a run is unusual when it is {Z_THRESHOLD} or more spreads "
        f"away from the job's other runs (minimum {MIN_HISTORY} other runs)."
    )

    print("\nAnomaly status counts:")
    print(results["anomaly_status"].value_counts().to_string())

    anomalies = results[
        results["anomaly_status"].isin(["UNUSUALLY_LONG", "UNUSUALLY_SHORT"])
    ].copy()

    print("\nUnusual runs:")
    if anomalies.empty:
        print("No unusual runs found.")
    else:
        anomalies["run_date"] = anomalies["run_date"].dt.strftime("%Y-%m-%d")
        print(
            anomalies[
                [
                    "execution_id",
                    "job_name",
                    "run_date",
                    "status",
                    "runtime_minutes",
                    "baseline_avg",
                    "z_score",
                    "anomaly_status",
                ]
            ].to_string(index=False)
        )

    history = summarise_job_history(results)
    increasing = history[history["trend"] == "INCREASING"].sort_values(
        "trend_pct", ascending=False
    )

    print("\nJobs whose runtime is increasing (top 10):")
    if increasing.empty:
        print("No increasing trends found.")
    else:
        print(
            increasing[
                [
                    "job_name",
                    "avg_runtime",
                    "max_runtime",
                    "limit",
                    "trend_pct",
                ]
            ]
            .head(10)
            .to_string(index=False)
        )
import sys
from collections import deque
from datetime import date, timedelta

import numpy as np
import pandas as pd

from data_loader import DATA_DIR, load_job_config, load_dependencies
from dependency_engine import build_graph, find_connected_jobs

# ---------- Settings (easy to change) ----------
OUTPUT_FILE = DATA_DIR / "execution_history_simulated.csv"

START_DATE = date(2026, 10, 22)   # first simulated day
NUMBER_OF_DAYS = 6
RANDOM_SEED = 42                  # same seed = same data every time

# A job normally runs for this share of its maximum runtime.
TYPICAL_RUNTIME_SHARE = 0.8
# A job is scheduled to start this many minutes before it needs to finish.
START_SLACK_MINUTES = 15
# A downstream job starts this many minutes after its upstream jobs finish.
HANDOVER_MINUTES = 2

# fail_chance  : chance that any run fails
# noise        : normal run-to-run variation in runtime
# ramp         : how much longer runs are by the last day (1.0 = no change)
# last_day_slowdown : extra slowdown applied to the last day only
# force_failure: make the job with most downstream jobs fail on the last day
# snapshot     : leave some last-day jobs QUEUED / RUNNING (a "live" view)
SCENARIOS = {
    "normal": {
        "description": "Healthy week with rare failures.",
        "fail_chance": 0.02,
        "noise": 0.10,
        "ramp": 1.0,
        "last_day_slowdown": 1.0,
        "force_failure": False,
        "snapshot": False,
    },
    "degraded": {
        "description": "Runtimes slowly grow and failures are more common.",
        "fail_chance": 0.05,
        "noise": 0.12,
        "ramp": 1.35,
        "last_day_slowdown": 1.0,
        "force_failure": False,
        "snapshot": False,
    },
    "bad_day": {
        "description": (
            "Normal week, then on the last day the most important upstream "
            "job fails and everything runs slower."
        ),
        "fail_chance": 0.02,
        "noise": 0.10,
        "ramp": 1.0,
        "last_day_slowdown": 1.3,
        "force_failure": True,
        "snapshot": False,
    },
    "live": {
        "description": (
            "Normal week, with the last day shown part-way through: some "
            "jobs finished, some RUNNING, some still QUEUED."
        ),
        "fail_chance": 0.02,
        "noise": 0.10,
        "ramp": 1.0,
        "last_day_slowdown": 1.0,
        "force_failure": False,
        "snapshot": True,
    },
}


# ---------- Small helper functions ----------
def to_minutes(clock_text):
    """Turn '02:30' into 150 (minutes after midnight)."""
    hours, minutes = str(clock_text).strip().split(":")[:2]
    return int(hours) * 60 + int(minutes)


def to_clock(total_minutes):
    """Turn 150 into '02:30'."""
    total_minutes = int(total_minutes) % 1440
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def topological_order(job_ids, downstream_map, upstream_map):
    """Order the jobs so every job comes after the jobs it waits for.

    Returns (order, leftover). Jobs left over are part of a dependency loop.
    """
    indegree = {
        job_id: len(set(upstream_map.get(job_id, []))) for job_id in job_ids
    }
    queue = deque(sorted(j for j in job_ids if indegree[j] == 0))
    order = []

    while queue:
        current = queue.popleft()
        order.append(current)
        for following in sorted(set(downstream_map.get(current, []))):
            indegree[following] -= 1
            if indegree[following] == 0:
                queue.append(following)

    leftover = [j for j in job_ids if j not in order]
    return order, leftover


# ---------- Simulation of one day ----------
def simulate_day(
    jobs, dependencies, order, day_index, days, settings, forced_job, rng
):
    """Simulate every job for one day. Returns a dictionary per job."""

    # Runtime multiplier for this day.
    factor = 1 + (settings["ramp"] - 1) * day_index / max(days - 1, 1)
    if day_index == days - 1:
        factor *= settings["last_day_slowdown"]

    job_lookup = jobs.set_index("job_id")
    results = {}

    for job_id in order:
        job = job_lookup.loc[job_id]
        max_runtime = float(job["max_runtime_minutes"])
        typical = TYPICAL_RUNTIME_SHARE * max_runtime
        deadline = to_minutes(job["sla_deadline"])

        # Planned start: early enough to finish before the SLA deadline.
        scheduled = max(deadline - round(typical) - START_SLACK_MINUTES, 5)

        # Look at every job this one waits for.
        blocked = False
        earliest = 0
        links = dependencies[dependencies["downstream_job_id"] == job_id]
        for _, link in links.iterrows():
            upstream = results.get(link["upstream_job_id"])
            if upstream is None:
                continue
            failed_required = (
                upstream["status"] == "FAILED"
                and link["dependency_type"] == "SUCCESS_REQUIRED"
            )
            if upstream["status"] == "BLOCKED" or failed_required:
                blocked = True
            else:
                earliest = max(earliest, upstream["end"] + HANDOVER_MINUTES)

        start = max(scheduled, earliest)

        # A job that cannot start (or would start too late) stays queued.
        if blocked or start > 1380:
            results[job_id] = {
                "status": "BLOCKED",
                "start": scheduled,
                "end": None,
            }
            continue

        noise = max(rng.normal(1.0, settings["noise"]), 0.5)
        runtime = max(5, round(typical * factor * noise))

        failed = (job_id == forced_job) or (
            rng.random() < settings["fail_chance"]
        )
        if failed:
            # A failed job stops part-way through its normal runtime.
            runtime = max(3, round(runtime * rng.uniform(0.3, 0.8)))

        results[job_id] = {
            "status": "FAILED" if failed else "COMPLETED",
            "start": start,
            "end": start + runtime,
        }

    return results


def apply_live_snapshot(day_results):
    """Show the day part-way through: some RUNNING, some still QUEUED."""
    ends = [
        r["end"]
        for r in day_results.values()
        if r["status"] in ("COMPLETED", "FAILED")
    ]
    if not ends:
        return None

    cutoff = float(np.percentile(ends, 70))
    for result in day_results.values():
        if result["status"] not in ("COMPLETED", "FAILED"):
            continue
        if result["start"] > cutoff:
            result["status"] = "QUEUED"
            result["end"] = None
        elif result["end"] > cutoff:
            result["status"] = "RUNNING"
            result["end"] = None
    return cutoff


# ---------- Full simulation ----------
def run_simulation(scenario_name, seed=RANDOM_SEED):
    """Simulate all days and return (history table, notes)."""

    settings = SCENARIOS[scenario_name]
    rng = np.random.default_rng(seed)

    jobs = load_job_config()
    dependencies = load_dependencies()
    downstream_map, upstream_map = build_graph(dependencies)

    job_ids = jobs["job_id"].tolist()
    order, leftover = topological_order(job_ids, downstream_map, upstream_map)

    notes = []
    if leftover:
        notes.append(
            "WARNING: dependency loop found. These jobs were simulated "
            f"without waiting for each other: {sorted(leftover)}"
        )
    order = order + leftover

    # The job with the most downstream jobs fails in the bad-day scenario.
    forced_job = None
    if settings["force_failure"]:
        impact = {
            job_id: len(find_connected_jobs(job_id, downstream_map))
            for job_id in job_ids
        }
        forced_job = max(sorted(impact), key=lambda j: impact[j])
        name = jobs.loc[jobs["job_id"] == forced_job, "job_name"].iloc[0]
        notes.append(
            f"Forced failure on the last day: {forced_job} {name} "
            f"({impact[forced_job]} downstream jobs)."
        )

    records = []
    for day_index in range(NUMBER_OF_DAYS):
        run_date = START_DATE + timedelta(days=day_index)
        is_last_day = day_index == NUMBER_OF_DAYS - 1

        day_results = simulate_day(
            jobs,
            dependencies,
            order,
            day_index,
            NUMBER_OF_DAYS,
            settings,
            forced_job if is_last_day else None,
            rng,
        )

        if is_last_day and settings["snapshot"]:
            cutoff = apply_live_snapshot(day_results)
            if cutoff is not None:
                notes.append(
                    f"Live snapshot taken at {to_clock(cutoff)} on "
                    f"{run_date.isoformat()}."
                )

        for job_id, result in day_results.items():
            status = "QUEUED" if result["status"] == "BLOCKED" else result["status"]
            records.append(
                {
                    "job_id": job_id,
                    "run_date": run_date.isoformat(),
                    "start_time": to_clock(result["start"]),
                    "end_time": (
                        "" if result["end"] is None else to_clock(result["end"])
                    ),
                    "status": status,
                }
            )

    history = pd.DataFrame(records).sort_values(["job_id", "run_date"])
    history = history.reset_index(drop=True)
    history.insert(
        0,
        "execution_id",
        [f"EXEC{number:04d}" for number in range(1, len(history) + 1)],
    )
    return history, notes


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "normal"
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else RANDOM_SEED

    if scenario not in SCENARIOS:
        print(f"Unknown scenario '{scenario}'. Choose one of:")
        for name, settings in SCENARIOS.items():
            print(f"  {name:<9} {settings['description']}")
        return

    history, notes = run_simulation(scenario, seed)
    history.to_csv(OUTPUT_FILE, index=False)

    print("EXECUTION SIMULATOR")
    print("-------------------")
    print(f"Scenario : {scenario} - {SCENARIOS[scenario]['description']}")
    print(f"Seed     : {seed}")
    print(f"Created  : {OUTPUT_FILE.name} with {len(history)} execution records")
    print("The original execution_history.csv was not changed.")

    for note in notes:
        print(f"\n{note}")

    print("\nStatus counts:")
    print(history["status"].value_counts().to_string())

    print("\nStatus by day:")
    print(pd.crosstab(history["run_date"], history["status"]).to_string())


if __name__ == "__main__":
    main()
def job(job_id, name=None, deadline="02:00", max_runtime=60,
        criticality="MEDIUM"):
    """One row of job_config.csv."""
    return [job_id, name or job_id, "DAILY", deadline, max_runtime,
            criticality]


def run(execution_id, job_id, run_date, start, end, status):
    """One row of execution_history.csv."""
    return [execution_id, job_id, run_date, start, end, status]


def dep(upstream, downstream, dependency_type="SUCCESS_REQUIRED"):
    """One row of dependencies.csv."""
    return [upstream, downstream, dependency_type]


def clock_after(start, minutes):
    """Add minutes to a clock time: clock_after('01:00', 90) -> '02:30'."""
    hours, mins = start.split(":")
    total = (int(hours) * 60 + int(mins) + minutes) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def runs_with_runtimes(job_id, runtimes, status="COMPLETED", start="01:00"):
    """One run per day (from 2026-09-01) with the given runtimes."""
    rows = []
    for index, minutes in enumerate(runtimes, start=1):
        rows.append(
            run(
                f"{job_id}-E{index}",
                job_id,
                f"2026-09-{index:02d}",
                start,
                clock_after(start, minutes),
                status,
            )
        )
    return rows
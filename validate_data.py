
from pathlib import Path
import pandas as pd

DATA = Path("data")

jobs = pd.read_csv(DATA / "job_config.csv")
history = pd.read_csv(DATA / "execution_history.csv")
dependencies = pd.read_csv(DATA / "dependencies.csv")

errors = []
warnings = []

# 1. Check required columns
required_columns = {
    "job_config.csv": (
        jobs,
        ["job_id", "job_name", "schedule", "sla_deadline",
         "max_runtime_minutes", "criticality"],
    ),
    "execution_history.csv": (
        history,
        ["execution_id", "job_id", "run_date", "start_time",
         "end_time", "status"],
    ),
    "dependencies.csv": (
        dependencies,
        ["upstream_job_id", "downstream_job_id", "dependency_type"],
    ),
}

for filename, (df, columns) in required_columns.items():
    missing = set(columns) - set(df.columns)
    if missing:
        errors.append(f"{filename}: missing columns {sorted(missing)}")

# Continue detailed checks only if the required columns exist
if not errors:
    # 2. Check unique IDs
    if jobs["job_id"].duplicated().any():
        errors.append("job_config.csv contains duplicate job_id values.")

    if history["execution_id"].duplicated().any():
        errors.append("execution_history.csv contains duplicate execution_id values.")

    # 3. Check job references
    job_ids = set(jobs["job_id"].dropna().astype(str).str.strip())

    history_job_ids = set(
        history["job_id"].dropna().astype(str).str.strip()
    )
    unknown_history_jobs = history_job_ids - job_ids

    if unknown_history_jobs:
        errors.append(
            f"Execution history references unknown jobs: "
            f"{sorted(unknown_history_jobs)}"
        )

    # 4. Check status values
    valid_statuses = {"QUEUED", "RUNNING", "COMPLETED", "FAILED"}
    statuses = set(
        history["status"].dropna().astype(str).str.strip().str.upper()
    )
    invalid_statuses = statuses - valid_statuses

    if invalid_statuses:
        errors.append(f"Invalid execution statuses: {sorted(invalid_statuses)}")

    if history["status"].isna().any():
        errors.append("Some execution records have a missing status.")

    # 5. Check criticality and runtime limits
    valid_criticalities = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    criticalities = set(
        jobs["criticality"].dropna().astype(str).str.strip().str.upper()
    )
    invalid_criticalities = criticalities - valid_criticalities

    if invalid_criticalities:
        errors.append(
            f"Invalid criticality values: {sorted(invalid_criticalities)}"
        )

    if jobs["criticality"].isna().any():
        errors.append("Some jobs have missing criticality.")

    runtime_limits = pd.to_numeric(
        jobs["max_runtime_minutes"], errors="coerce"
    )
    if runtime_limits.isna().any() or (runtime_limits <= 0).any():
        errors.append("Maximum runtime must be a positive number for every job.")

    # 6. Check dependency references
    upstream = dependencies["upstream_job_id"].astype("string").str.strip()
    downstream = dependencies["downstream_job_id"].astype("string").str.strip()

    for column_name, values in [
        ("upstream_job_id", upstream),
        ("downstream_job_id", downstream),
    ]:
        unknown = set(values.dropna()) - job_ids
        if unknown:
            errors.append(
                f"{column_name} references unknown jobs: {sorted(unknown)}"
            )

        if values.isna().any() or values.eq("").any():
            errors.append(f"{column_name} contains blank values.")

    self_dependencies = dependencies[
        upstream.notna() & downstream.notna() & (upstream == downstream)
    ]
    if not self_dependencies.empty:
        errors.append("A job cannot depend on itself.")

    if dependencies.duplicated(
        subset=["upstream_job_id", "downstream_job_id"]
    ).any():
        warnings.append("Duplicate dependency links were found.")

    # 7. Check timestamps
    dates = pd.to_datetime(history["run_date"], errors="coerce")
    if dates.isna().any():
        errors.append("Some run_date values are missing or invalid.")

    for column in ["start_time", "end_time"]:
        values = history[column].dropna().astype(str).str.strip()
        values = values[values != ""]
        parsed = pd.to_datetime(values, format="%H:%M:%S", errors="coerce")
        # Also accept HH:MM format
        remaining = parsed.isna()
        if remaining.any():
            parsed.loc[remaining] = pd.to_datetime(
                values[remaining], format="%H:%M", errors="coerce"
            )
        if parsed.isna().any():
            errors.append(f"Some {column} values have an invalid time format.")

    # Blank end_time is allowed for RUNNING or QUEUED jobs.
    # COMPLETED and FAILED records should have an end time.
    finished = history["status"].astype(str).str.upper().isin(
        ["COMPLETED", "FAILED"]
    )
    missing_end = history["end_time"].isna() | (
        history["end_time"].astype("string").str.strip() == ""
    )
    if (finished & missing_end).any():
        errors.append("Some COMPLETED or FAILED records have no end_time.")

    if ((~finished) & missing_end).any():
        warnings.append(
            "Some unfinished jobs have no end_time; this is expected."
        )

# 8. Print the report
print("\n========== DATA VALIDATION REPORT ==========")
print(f"Jobs configured: {len(jobs)}")
print(f"Execution records: {len(history)}")
print(f"Dependency links: {len(dependencies)}")

if errors:
    print(f"\nERRORS ({len(errors)}):")
    for item in errors:
        print(" -", item)
else:
    print("\nNo errors found in the checks performed.")

if warnings:
    print(f"\nWARNINGS ({len(warnings)}):")
    for item in warnings:
        print(" -", item)

print("\n============================================")

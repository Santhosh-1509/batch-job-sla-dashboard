# Synthetic dataset schema

All records are fictional examples for learning and demonstration. They are not Wipro production data.

## `job_config.csv` — 30 jobs
Columns retained from the starter dataset:
- `job_id`: unique ID (`JOB001`–`JOB030`)
- `job_name`: fictional job name
- `schedule`: illustrative schedule label
- `sla_deadline`: deadline in `HH:MM`
- `max_runtime_minutes`: maximum runtime in minutes
- `criticality`: `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`

## `execution_history.csv` — 180 records
Six sample runs per job across 2026-09-01 through 2026-09-06.
- `execution_id`: unique execution ID
- `job_id`: reference to a configured job
- `run_date`: ISO date (`YYYY-MM-DD`)
- `start_time`, `end_time`: `HH:MM`; end time is blank for queued/running jobs
- `status`: `QUEUED`, `RUNNING`, `COMPLETED`, or `FAILED`

The data deliberately includes varied outcomes and some long runtimes. Runtime calculations should handle runs that cross midnight.

## `dependencies.csv` — 36 links
- `upstream_job_id`: upstream job ID
- `downstream_job_id`: downstream job ID
- `dependency_type`: `SUCCESS_REQUIRED` or `COMPLETION_REQUIRED`

All dependency IDs refer to configured jobs; there are no self-links. Data is synthetic and intended for dashboard development.

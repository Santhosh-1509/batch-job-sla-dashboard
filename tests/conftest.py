import sys
from pathlib import Path

import pandas as pd
import pytest

# Make the project folder importable (data_loader.py, sla_analysis.py, ...).
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

JOB_COLUMNS = [
    "job_id",
    "job_name",
    "schedule",
    "sla_deadline",
    "max_runtime_minutes",
    "criticality",
]
HISTORY_COLUMNS = [
    "execution_id",
    "job_id",
    "run_date",
    "start_time",
    "end_time",
    "status",
]
DEPENDENCY_COLUMNS = [
    "upstream_job_id",
    "downstream_job_id",
    "dependency_type",
]


@pytest.fixture
def build_data(tmp_path, monkeypatch):
    """Create a small made-up dataset and point the code at it.

    Usage inside a test:
        build_data(jobs=[...], history=[...], dependencies=[...])
    Everything is removed automatically when the test ends.
    """

    def _build(jobs, history, dependencies=None):
        pd.DataFrame(jobs, columns=JOB_COLUMNS).to_csv(
            tmp_path / "job_config.csv", index=False
        )
        pd.DataFrame(history, columns=HISTORY_COLUMNS).to_csv(
            tmp_path / "execution_history.csv", index=False
        )
        pd.DataFrame(dependencies or [], columns=DEPENDENCY_COLUMNS).to_csv(
            tmp_path / "dependencies.csv", index=False
        )
        monkeypatch.setenv("BATCH_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("BATCH_HISTORY_FILE", raising=False)
        return tmp_path

    return _build
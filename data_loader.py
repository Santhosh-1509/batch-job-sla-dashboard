import os
from pathlib import Path

import pandas as pd


# Find the project folder and the default data directory
PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"

# By default the original execution history is used. Setting the
# environment variable BATCH_HISTORY_FILE switches to another file
# in the data folder (for example the simulated one).
HISTORY_FILE_VARIABLE = "BATCH_HISTORY_FILE"
DEFAULT_HISTORY_FILE = "execution_history.csv"

# Setting BATCH_DATA_DIR makes every loader read from another folder.
# The tests use this to feed small made-up datasets to the code.
DATA_DIR_VARIABLE = "BATCH_DATA_DIR"


def get_data_dir():
    """Return the folder the CSV files are read from."""
    custom_folder = os.environ.get(DATA_DIR_VARIABLE)
    if custom_folder:
        return Path(custom_folder)
    return DATA_DIR


def load_job_config():
    """Load the configured batch jobs."""
    return pd.read_csv(get_data_dir() / "job_config.csv")


def load_execution_history():
    """Load job execution history."""
    file_name = os.environ.get(HISTORY_FILE_VARIABLE, DEFAULT_HISTORY_FILE)
    return pd.read_csv(
        get_data_dir() / file_name,
        keep_default_na=False
    )


def load_dependencies():
    """Load relationships between jobs."""
    return pd.read_csv(get_data_dir() / "dependencies.csv")


if __name__ == "__main__":
    jobs = load_job_config()
    executions = load_execution_history()
    dependencies = load_dependencies()

    print("DATA LOADING SUCCESSFUL")
    print("-----------------------")
    print(f"Configured jobs: {len(jobs)}")
    print(f"Execution records: {len(executions)}")
    print(f"Dependency links: {len(dependencies)}")

    print("\nJob configuration preview:")
    print(jobs.head())

    print("\nExecution history preview:")
    print(executions.head())

    print("\nDependency preview:")
    print(dependencies.head())

from pathlib import Path
import pandas as pd

# Find the project data folder
data_folder = Path("data")

files = [
    "job_config.csv",
    "execution_history.csv",
    "dependencies.csv",
]

for filename in files:
    file_path = data_folder / filename

    if not file_path.exists():
        print(f"MISSING: {file_path}")
        continue

    df = pd.read_csv(file_path)

    print(f"\n--- {filename} ---")
    print("Rows:", len(df))
    print("Columns:", list(df.columns))
    print(df.head(3).to_string(index=False))

import pandas as pd

from helpers import dep, job
from simulator import NUMBER_OF_DAYS, run_simulation


def test_one_record_per_job_per_day(build_data):
    build_data(
        jobs=[job("A", deadline="04:00"), job("B", deadline="05:00")],
        history=[],
    )
    history, _ = run_simulation("normal")
    assert len(history) == 2 * NUMBER_OF_DAYS


def test_same_seed_gives_the_same_data(build_data):
    build_data(
        jobs=[job("A", deadline="04:00"), job("B", deadline="05:00")],
        history=[],
        dependencies=[dep("A", "B")],
    )
    first, _ = run_simulation("normal", seed=7)
    second, _ = run_simulation("normal", seed=7)
    pd.testing.assert_frame_equal(first, second)


def test_dependency_loop_is_reported(build_data):
    build_data(
        jobs=[job("A"), job("B"), job("C")],
        history=[],
        dependencies=[dep("A", "B"), dep("B", "C"), dep("C", "A")],
    )
    _, notes = run_simulation("normal")
    assert any("loop" in note.lower() for note in notes)


def test_bad_day_failure_blocks_the_downstream_jobs(build_data):
    build_data(
        jobs=[
            job("A", deadline="04:00"),
            job("B", deadline="05:00"),
            job("C", deadline="06:00"),
        ],
        history=[],
        dependencies=[dep("A", "B"), dep("B", "C")],
    )
    history, _ = run_simulation("bad_day")
    last_day = history["run_date"].max()
    today = history[history["run_date"] == last_day].set_index("job_id")
    assert today.loc["A", "status"] == "FAILED"
    assert today.loc["B", "status"] == "QUEUED"
    assert today.loc["C", "status"] == "QUEUED"
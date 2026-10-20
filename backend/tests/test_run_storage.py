"""Identical run files are stored once, without any run losing a file."""

import os

import pytest

import manage_runs
import runs


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    return tmp_path / "runs"


def make_run(runs_dir, name, png: bytes, mtime: int):
    folder = runs_dir / name
    folder.mkdir()
    (folder / "artwork.png").write_bytes(png)
    (folder / "feedback.jsonl").write_bytes(b"x" * 100_000)
    (folder / "result.json").write_bytes(b"{" + b" " * 100_000 + b"}")  # large and identical: must still not be shared
    (folder / "inputs.json").write_text("{}")
    os.utime(folder / "inputs.json", (mtime, mtime))
    return folder


def test_identical_files_share_one_copy_and_stay_readable(runs_dir):
    png = os.urandom(200_000)
    a, b = make_run(runs_dir, "aaa", png, 1), make_run(runs_dir, "bbb", png, 2)
    runs.share_identical_files(a)
    assert runs.share_identical_files(b) == len(png)
    assert (a / "artwork.png").read_bytes() == (b / "artwork.png").read_bytes() == png
    assert os.path.samefile(a / "artwork.png", b / "artwork.png")
    assert not os.path.samefile(a / "feedback.jsonl", b / "feedback.jsonl")  # appendable: never shared
    assert not os.path.samefile(a / "result.json", b / "result.json")  # keeps its own save time
    listed, actual = manage_runs.disk_use(runs_dir)
    assert listed - actual >= 2 * len(png)  # both run files and the blob are one copy on disk


def test_prune_is_a_dry_run_unless_confirmed(runs_dir, capsys):
    png = os.urandom(100_000)
    for i, name in enumerate(["old1", "old2", "new"]):
        runs.share_identical_files(make_run(runs_dir, name, png if name != "old1" else os.urandom(100_000), i))
    manage_runs.prune(keep=1, confirmed=False)
    assert {"old1", "old2", "new"} <= {p.name for p in runs_dir.iterdir()}
    manage_runs.prune(keep=1, confirmed=True)
    assert {p.name for p in runs_dir.iterdir() if p.name != "_blobs"} == {"new"}
    assert (runs_dir / "new" / "artwork.png").read_bytes() == png  # the kept run is intact
    assert len(list(runs.blobs_dir().iterdir())) == 1  # old1's own blob was removed with it

import subprocess
import sys


def test_imports() -> None:
    import poker_arena  # noqa: F401


def test_cli_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "poker_arena.cli", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "poker-arena" in proc.stdout


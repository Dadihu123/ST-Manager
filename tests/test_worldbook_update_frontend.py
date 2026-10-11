from pathlib import Path
import subprocess


def test_worldbook_update_runtime():
    result = subprocess.run(
        ["node", "tests/worldbook_update_runtime_test.mjs"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

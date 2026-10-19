"""Record the golden responses (see tests/test_golden_responses.py).

  python scripts/record_golden.py                 # -> tests/golden/upstream-v1.4.1.json (run on UPSTREAM code only)
  python scripts/record_golden.py --out FILE      # record the current code elsewhere, e.g. to diff a change
  python scripts/record_golden.py --check         # run twice, prove the recording is deterministic

Runs each case through pytest's isolated_state fixture so it sees exactly the environment the test sees.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = """
import json, os, pytest
from golden_cases import case_ids, run_case
OUT = {}
@pytest.mark.parametrize("case_id", case_ids())
def test_record(case_id, monkeypatch):
    OUT[case_id] = run_case(case_id, monkeypatch)
def teardown_module():
    with open(os.environ["GOLDEN_OUT"], "w") as f:
        json.dump(OUT, f, sort_keys=True, indent=1)
"""


def record(out):
    runner = ROOT / "tests" / "_record_golden_tmp_test.py"
    runner.write_text(RUNNER)
    try:
        env = dict(os.environ, GOLDEN_OUT=str(out))
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(runner)],
                       cwd=ROOT, env=env, check=True)
    finally:
        runner.unlink()
    return json.loads(Path(out).read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "tests" / "golden" / "upstream-v1.4.1.json"))
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    first = record(a.out)
    print(f"recorded {len(first)} cases -> {a.out}")
    if a.check:
        with tempfile.NamedTemporaryFile(suffix=".json") as t:
            second = record(t.name)
        if first != second:
            sys.exit("NOT deterministic: two recordings differ")
        print("deterministic: two recordings identical")


if __name__ == "__main__":
    main()

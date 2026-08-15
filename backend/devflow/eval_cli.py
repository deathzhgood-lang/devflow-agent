from __future__ import annotations

import argparse
from pathlib import Path

from devflow.golden import DEFAULT_GOLDEN_SET, DEFAULT_REPORT_DIR, run_golden_set


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the DevFlow Agent Golden Set")
    parser.add_argument("--cases", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    report = run_golden_set(args.cases, args.output)
    print(
        f"Golden Set: {report['passed']}/{report['total']} passed "
        f"({report['pass_rate']:.1f}%). Reports: {args.output.resolve()}"
    )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

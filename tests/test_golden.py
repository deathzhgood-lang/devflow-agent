from pathlib import Path

from devflow.golden import DEFAULT_GOLDEN_SET, run_golden_set


def test_golden_set_has_15_cases_and_generates_reports(tmp_path: Path) -> None:
    report = run_golden_set(DEFAULT_GOLDEN_SET, tmp_path)

    assert report["total"] == 15
    assert report["passed"] == 15
    assert report["pass_rate"] == 100.0
    assert report["security_total"] >= 2
    assert report["security_passed"] == report["security_total"]
    assert (tmp_path / "golden-set-latest.json").exists()
    assert (tmp_path / "golden-set-latest.md").exists()

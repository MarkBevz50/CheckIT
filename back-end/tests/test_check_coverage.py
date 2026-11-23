"""tools/check_coverage.py: the coverage ratchet used by CI (E0.5b)."""

import json

import pytest

from tools import check_coverage as cc

BASELINE = {
    "app_total": 60.0,
    "modules_total": 80.0,
    "module_min": 75.0,
    "tolerance": 0.0,
    "modules": ["app/core/", "app/services/risk_analyzer.py"],
}


def coverage(files: dict) -> dict:
    """Build a coverage.json-shaped dict from {path: (covered, statements)}."""
    return {"files": {path: {"summary": {"covered_lines": c, "num_statements": s}} for path, (c, s) in files.items()}}


GOOD = {
    "app/core/config.py": (32, 32),
    "app/services/risk_analyzer.py": (80, 100),
    "app/routers/other.py": (0, 100),  # not in the module list: drags only app_total down
}


def test_passes_when_every_number_is_at_or_above_the_baseline():
    lines, failures = cc.check(coverage(GOOD), {**BASELINE, "app_total": 40.0})
    assert failures == []
    assert any("app total" in line for line in lines)


def test_fails_when_the_app_total_falls_below_the_baseline():
    _, failures = cc.check(coverage(GOOD), BASELINE)  # app total is ~52.8 %, baseline 60
    assert any("app total" in f for f in failures)


def test_fails_when_one_module_file_falls_below_module_min():
    files = {**GOOD, "app/services/risk_analyzer.py": (70, 100)}
    _, failures = cc.check(coverage(files), {**BASELINE, "app_total": 0.0, "modules_total": 0.0})
    assert [f for f in failures if "risk_analyzer" in f]


def test_fails_when_the_modules_total_falls_below_the_baseline():
    files = {"app/core/config.py": (10, 20), "app/services/risk_analyzer.py": (90, 100)}
    _, failures = cc.check(coverage(files), {**BASELINE, "app_total": 0.0, "modules_total": 90.0, "module_min": 0.0})
    assert any("modules total" in f for f in failures)


def test_a_listed_module_without_coverage_data_is_a_failure():
    files = {"app/core/config.py": (32, 32)}  # risk_analyzer.py is gone (renamed?) or not measured
    _, failures = cc.check(coverage(files), {**BASELINE, "app_total": 0.0})
    assert any("risk_analyzer" in f and "no coverage data" in f for f in failures)


def test_windows_paths_are_normalised():
    files = {"app\\core\\config.py": (32, 32), "app\\services\\risk_analyzer.py": (80, 100)}
    _, failures = cc.check(coverage(files), {**BASELINE, "app_total": 0.0})
    assert failures == []


def test_tolerance_absorbs_a_small_platform_difference():
    files = {"app/core/config.py": (32, 32), "app/services/risk_analyzer.py": (749, 1000)}  # 74.9 % < 75
    assert cc.check(coverage(files), {**BASELINE, "app_total": 0.0, "modules_total": 0.0})[1]
    assert cc.check(coverage(files), {**BASELINE, "app_total": 0.0, "modules_total": 0.0, "tolerance": 0.2})[1] == []


def test_empty_files_do_not_count_as_a_module_minimum_violation():
    files = {**GOOD, "app/core/__init__.py": (0, 0)}  # 0 statements: 100 % by convention, never a failure
    _, failures = cc.check(coverage(files), {**BASELINE, "app_total": 40.0})
    assert failures == []


def test_command_line_exit_codes(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
    report = tmp_path / "coverage.json"

    report.write_text(json.dumps(coverage({**GOOD, "app/routers/other.py": (100, 100)})), encoding="utf-8")
    assert cc.main([str(report), "--baseline", str(baseline)]) == 0

    report.write_text(json.dumps(coverage(GOOD)), encoding="utf-8")
    assert cc.main([str(report), "--baseline", str(baseline)]) == 1
    assert "below the baseline" in capsys.readouterr().err


def test_print_baseline_floors_to_one_decimal(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
    report = tmp_path / "coverage.json"
    report.write_text(json.dumps(coverage({"app/core/config.py": (2, 3), "app/services/risk_analyzer.py": (80, 100)})),
                      encoding="utf-8")
    assert cc.main([str(report), "--baseline", str(baseline), "--print-baseline"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["module_min"] == pytest.approx(66.6)  # 2/3 floored, not rounded up

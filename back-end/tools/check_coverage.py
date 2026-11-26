"""Coverage ratchet for CI (E0.5b): coverage must not fall below the baseline.

    pytest ... --cov=app --cov-report=json:coverage.json
    python tools/check_coverage.py coverage.json                  # compare with coverage_baseline.json
    python tools/check_coverage.py coverage.json --print-baseline  # current numbers, floored to 0.1

Three rules, all from coverage_baseline.json:
  * app_total    : statements covered in all of app/ (percent);
  * modules_total: the same for the modules that are not rewritten in E1-E2 (the list of E0.2);
  * module_min   : every file of those modules separately.
The baseline is raised only by an explicit commit (take the numbers from CI, `--print-baseline`).
Exit code 0 = ok, 1 = coverage fell below the baseline or a listed module has no data.
"""

import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_BASELINE = Path(__file__).resolve().parent.parent / "coverage_baseline.json"


def load_files(coverage: dict) -> dict:
    """{'app/core/config.py': (covered, statements)}; paths normalised to forward slashes."""
    return {
        path.replace("\\", "/"): (info["summary"]["covered_lines"], info["summary"]["num_statements"])
        for path, info in coverage["files"].items()
    }


def percent(covered: int, statements: int) -> float:
    return 100.0 if statements == 0 else 100.0 * covered / statements


def matching(files: dict, prefixes: list) -> dict:
    return {p: v for p, v in files.items() if any(p == m or (m.endswith("/") and p.startswith(m)) for m in prefixes)}


def floor1(value: float) -> float:
    return math.floor(value * 10 + 1e-9) / 10


def measure(files: dict, prefixes: list) -> dict:
    app = {p: v for p, v in files.items() if p.startswith("app/")}
    mods = matching(files, prefixes)
    with_code = {p: v for p, v in mods.items() if v[1] > 0}
    return {
        "app_total": percent(sum(c for c, _ in app.values()), sum(s for _, s in app.values())),
        "modules_total": percent(sum(c for c, _ in mods.values()), sum(s for _, s in mods.values())),
        "module_files": {p: percent(c, s) for p, (c, s) in with_code.items()},
        "missing": [m for m in prefixes if not matching(files, [m])],
    }


def check(coverage: dict, baseline: dict):
    """Return (report lines, list of failures)."""
    tolerance = baseline.get("tolerance", 0.0)
    now = measure(load_files(coverage), baseline["modules"])
    lines, failures = [], []

    def rule(name, value, minimum):
        ok = value + tolerance >= minimum
        lines.append(f"{'ok  ' if ok else 'FAIL'} {name}: {value:.2f}% (baseline {minimum:.1f}%)")
        if not ok:
            failures.append(f"{name} fell to {value:.2f}%, baseline is {minimum:.1f}%")

    rule("app total", now["app_total"], baseline["app_total"])
    rule("E0.2 modules total", now["modules_total"], baseline["modules_total"])
    for path, value in sorted(now["module_files"].items()):
        rule(f"  {path}", value, baseline["module_min"])
    for missing in now["missing"]:
        lines.append(f"FAIL no coverage data for {missing}")
        failures.append(f"no coverage data for {missing}: renamed or not measured?")
    return lines, failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("coverage_json", type=Path)
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--print-baseline", action="store_true", help="print the current numbers in baseline format and exit")
    args = ap.parse_args(argv)

    coverage = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if args.print_baseline:
        now = measure(load_files(coverage), baseline["modules"])
        print(json.dumps({"app_total": floor1(now["app_total"]), "modules_total": floor1(now["modules_total"]),
                          "module_min": floor1(min(now["module_files"].values()))}, indent=1))
        return 0
    lines, failures = check(coverage, baseline)
    print("\n".join(lines))
    if failures:
        print("\nCoverage is below the baseline:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print("\nCoverage is not below the baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

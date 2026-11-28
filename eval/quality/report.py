"""History of runs (eval/metrics/history.jsonl, in git), the markdown report and the chart for the diploma."""

import json
import os
import subprocess
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "eval" / "metrics"
HISTORY = METRICS / "history.jsonl"
REPORT = METRICS / "quality_report.md"
CHART = METRICS / "quality_metrics.png"


def git_sha() -> str:
    """GIT_SHA from the environment (set when the run happens inside the container, which has no git), else git."""
    if os.environ.get("GIT_SHA"):
        return os.environ["GIT_SHA"]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "back-end/app", "scraper"], capture_output=True,
                               text=True, cwd=ROOT).stdout.strip()
        return sha + ("+uncommitted" if dirty else "")
    except OSError:
        return "unknown"


def read_history() -> List[dict]:
    if not HISTORY.exists():
        return []
    return [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_history(row: dict) -> None:
    METRICS.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def pct(value: Optional[float]) -> str:
    return "н/д" if value is None else f"{value * 100:.0f} %"


def _row_cells(row: dict) -> List[str]:
    s = row["summary"]
    stability = row.get("stability")
    return [
        row["stage"], f"{row['mode']}" + (f"/{row['llm']}" if row["mode"] == "replay" else ""), row["date"], row["sha"],
        pct(s["coverage_ge1"]), pct(s["coverage_ge3"]),
        f"{pct(s['precision_all'])} ({pct(s['precision_same'])})", _human_precision(row), pct(s["labeled_share"]), pct(s["recall_labeled"]),
        f"{s['unsupported_alarms']}/{s['alarms']}", pct(s["false_alarm_rate"]), str(s["doc_findings"]),
        f"${s['cost_per_tender_usd']:.4f}" if s["cost_per_tender_usd"] is not None else "н/д",
        "н/д" if s["seconds_per_tender"] is None else f"{s['seconds_per_tender']} с",
        pct(s["llm"]["error_share"]), pct(stability["changed_share"]) if stability else "н/д",
    ]


def _human_precision(row: dict) -> str:
    """Precision on the owner's own labels: all human / human without the labels that carry a note (older rows have none)."""
    sets = row.get("quality_sets")
    if not sets:
        return "н/д"
    return f"{pct(sets['human']['precision_all'])} / {pct(sets['human_clean']['precision_all'])}"


HEADER = ["Етап", "Режим", "Дата", "SHA", "Покриття ≥1", "Покриття ≥3", "Точність (лише same)", "Точність лише людські / без позначок", "Розмічено",
          "Recall (розмічені)", "Хибні тривоги", "Частка", "Знахідки док.", "Вартість/тендер", "Час/тендер",
          "Помилки LLM", "Нестабільність"]


def build_report(history: List[dict]) -> str:
    lines = ["# Метрики якості контрольного прогону", "",
             "Згенеровано `eval/quality_report.py`. Визначення метрик: `PLAN/DIPLOMA_NOTES.md`, розділ «Метрики якості». "
             "Порівняння між етапами лише за рядками `replay`; `live` показує поточний стан ринку.", "",
             "## Етапи", "", "| " + " | ".join(HEADER) + " |", "|" + " --- |" * len(HEADER)]
    for row in history:
        lines.append("| " + " | ".join(_row_cells(row)) + " |")
    for mode in ("replay", "live"):
        latest = next((r for r in reversed(history) if r["mode"] == mode), None)
        if not latest:
            continue
        lines += ["", f"## Останній рядок `{mode}`: {latest['stage']} ({latest['date']}, {latest['sha']})", "",
                  "| Тендер | Позицій | Покриття ≥1 | Покриття ≥3 | Прийнято збігів | Розмічено | Правильних | Тривога | Клас | "
                  "Вартість | Час | Помилки |", "|" + " --- |" * 12]
        for tender_id, m in latest["tenders"].items():
            alarm = m["alarm"]
            seconds = (m.get("seconds") or {}).get("total")
            lines.append(
                f"| {tender_id} | {m['items']} | {pct(m['coverage_ge1'])} | {pct(m['coverage_ge3'])} | {m['accepted']} | "
                f"{m['labeled']} | {m['correct']} | {alarm.get('level') or 'н/д'} | {alarm['class']} | "
                f"${m['cost_usd']:.4f} | {'н/д' if seconds is None else f'{seconds} с'} | {len(m['errors'])} |")
        c10 = latest["tenders"].get("C10")
        if c10 and "expected_behavior_met" in c10:
            met = c10["expected_behavior_met"]
            verdict = "не перевірено (є прийняті збіги без розмітки)" if met is None else ("виконано" if met else "не виконано")
            if "expected_violated_items" in c10:
                lines += ["", f"C10, очікувана поведінка (бланки підприємства без збігів, для «Посвідчення про перевірку знань» аналоги допускаються): "
                              f"**{verdict}** (порушені позиції: {', '.join(c10['expected_violated_items']) or 'немає'}; "
                              f"прийнятих збігів без розмітки: {c10['expected_unverified']})."]
            else:
                lines += ["", f"C10, очікувана поведінка (немає релевантних збігів): **{verdict}** "
                              f"(прийнято збігів: {c10['accepted_matches']}, з них хибних за розміткою: "
                              f"{c10.get('accepted_false', 'н/д')}, без розмітки: {c10.get('accepted_unlabeled', 'н/д')})."]
        if latest.get("stability"):
            st = latest["stability"]
            lines += ["", f"Стабільність валідації: {st['pairs']} розмічених пар, {st['runs']} запуски, рішення змінилось у "
                          f"{st['changed']} ({pct(st['changed_share'])}), вартість ${st['cost_usd']:.4f}."]
    lines += ["", "![Метрики по етапах](quality_metrics.png)", ""]
    return "\n".join(lines)


def draw_chart(history: List[dict], path: Optional[Path] = None) -> bool:
    """Lines of the headline metrics by stage (replay rows; all rows if there are no replay rows). False without matplotlib."""
    path = path or CHART
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    rows = [r for r in history if r["mode"] == "replay"] or history
    if not rows:
        return False
    labels = [r["stage"] for r in rows]
    series = {"Покриття ≥ 1": "coverage_ge1", "Покриття ≥ 3": "coverage_ge3", "Точність збігів": "precision_all",
              "Хибні тривоги": "false_alarm_rate"}
    figure, axis = plt.subplots(figsize=(10, 5))
    for title, key in series.items():
        values = [r["summary"].get(key) for r in rows]
        axis.plot(range(len(rows)), [float("nan") if v is None else v * 100 for v in values], marker="o", label=title)
    axis.set_xticks(range(len(rows)))
    axis.set_xticklabels(labels, rotation=20, ha="right")
    axis.set_ylim(0, 105)
    axis.set_ylabel("%")
    axis.set_title("Якість контрольного прогону по етапах (replay)")
    axis.grid(alpha=0.3)
    axis.legend()
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=140)
    plt.close(figure)
    return True


def write_report(history: List[dict]) -> bool:
    METRICS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(history), encoding="utf-8")
    return draw_chart(history)

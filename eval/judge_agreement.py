"""Agreement of the judges with the owner's BLIND sample (E0.7): share of equal labels and Cohen's kappa.

    back-end\\.venv\\Scripts\\python.exe eval/judge_agreement.py

Compared with the owner's blind labels (label_source = human_blind): judge A, judge B and the consensus (the items on which A and B
agree; its coverage says how many items that is). Pairs: 3 classes (same / analog / no) and binary (relevant = same or analog,
or not); findings: true against the rest (false + duplicate), and the 3 classes as a secondary figure. Judge B is also compared
with the owner's OLDER labels of the 60 pilot pairs (calibration, judge B only: judge A built the pilot and entered the owner's 14
corrections, so for it those pairs are not blind).

Every figure is shown in views: all items; without the items of eval/data/label_notes.json (the owner consulted an assistant or
checked the market with an AI mode); and, for judge A, without the findings whose judge-A label is not independent
(judge_a_labels.json["contaminated_findings"]). Writes eval/metrics/judge_agreement.md.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "eval" / "data"
OUT = ROOT / "eval" / "metrics" / "judge_agreement.md"
RELEVANT = ("same", "analog")


def kappa(pairs):
    """Cohen's kappa of [(label1, label2)]; None when it is undefined (no items or chance agreement 1)."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    classes = {c for pair in pairs for c in pair}
    expected = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n) for c in classes)
    return None if expected >= 1 else round((observed - expected) / (1 - expected), 3)


def figures(pairs):
    n = len(pairs)
    return {"n": n, "agree": round(sum(1 for a, b in pairs if a == b) / n, 3) if n else None, "kappa": kappa(pairs)}


def pair_views(items, noted=frozenset()):
    """items: [(id, human, judge)]; returns figures for 3 classes and binary, with and without the noted items."""
    result = {}
    for name, keep in (("all", lambda i: True), ("without notes", lambda i: i not in noted)):
        chosen = [(h, j) for i, h, j in items if keep(i) and j is not None]
        result[name] = {"3 classes": figures(chosen), "binary": figures([(h in RELEVANT, j in RELEVANT) for h, j in chosen])}
    return result


def finding_views(items, noted=frozenset(), excluded=frozenset()):
    """items: [(id, human_label, judge_label)] with labels true/false/duplicate; true against the rest and 3 classes."""
    result = {}
    for name, keep in (("all", lambda i: i not in excluded),
                       ("without notes", lambda i: i not in noted and i not in excluded)):
        chosen = [(h, j) for i, h, j in items if keep(i) and j is not None]
        result[name] = {"true vs rest": figures([(h == "true", j == "true") for h, j in chosen]), "3 classes": figures(chosen)}
    return result


def load():
    labels = json.loads((DATA / "labels.json").read_text(encoding="utf-8"))
    return (labels, json.loads((DATA / "judge_a_labels.json").read_text(encoding="utf-8")),
            json.loads((DATA / "judge_b_labels.json").read_text(encoding="utf-8")),
            json.loads((DATA / "blind_sample.json").read_text(encoding="utf-8")),
            json.loads((DATA / "label_notes.json").read_text(encoding="utf-8")))


def human_blind(labels, kind, item_id):
    """The owner's blind label of an item, only if it really is a blind one."""
    if labels.get("label_sources", {}).get(kind, {}).get(item_id) != "human_blind":
        return None
    value = labels.get(kind, {}).get(item_id)
    return value.get("label") if isinstance(value, dict) else value


def compute():
    labels, a, b, blind, notes = load()
    noted_pairs, noted_findings = set(notes["pairs"]), set(notes["findings"])
    contaminated = set(a.get("contaminated_findings", []))
    report = {"pairs": {}, "findings": {}, "calibration_b": {}}

    pair_ids = [i for i in blind["pairs"] if human_blind(labels, "pairs", i)]
    human = {i: human_blind(labels, "pairs", i) for i in pair_ids}
    labeled_a = {i: a["pairs"][i]["label"] for i in pair_ids}
    labeled_b = {i: b["pairs"][i]["label"] for i in pair_ids}
    consensus = {i: labeled_a[i] for i in pair_ids if labeled_a[i] == labeled_b[i]}
    report["pairs"]["n_blind"] = len(pair_ids)
    report["pairs"]["consensus_coverage"] = round(len(consensus) / len(pair_ids), 3) if pair_ids else None
    for name, source in (("judge A", labeled_a), ("judge B", labeled_b), ("consensus A=B", consensus)):
        report["pairs"][name] = pair_views([(i, human[i], source.get(i)) for i in pair_ids], noted_pairs)
    report["pairs"]["A vs B (the same items)"] = pair_views([(i, labeled_a[i], labeled_b[i]) for i in pair_ids], noted_pairs)

    finding_ids = [i for i in blind["findings"] if human_blind(labels, "findings", i)]
    human_f = {i: human_blind(labels, "findings", i) for i in finding_ids}
    fa = {i: a["findings"][i]["label"] for i in finding_ids}
    fb = {i: b["findings"][i]["label"] for i in finding_ids}
    fcons = {i: fa[i] for i in finding_ids if fa[i] == fb[i]}
    report["findings"]["n_blind"] = len(finding_ids)
    report["findings"]["consensus_coverage"] = round(len(fcons) / len(finding_ids), 3) if finding_ids else None
    report["findings"]["contaminated_in_blind"] = sorted(contaminated & set(finding_ids))
    for name, source, excluded in (("judge A", fa, contaminated), ("judge B", fb, frozenset()), ("consensus A=B", fcons, contaminated)):
        report["findings"][name] = finding_views([(i, human_f[i], source.get(i)) for i in finding_ids], noted_findings, excluded)

    pilot = [r["pair_id"] for r in (json.loads(x) for x in (DATA / "pairs_pilot.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())]
    old = {i: labels["pairs"][i] for i in pilot if i in labels.get("pairs", {})}
    report["calibration_b"] = pair_views([(i, old[i], b["calibration"].get(i, {}).get("label")) for i in old])
    report["calibration_b"]["n"] = len(old)
    return report


def cell(f):
    if not f or not f["n"]:
        return "н/д"
    kap = "н/д" if f["kappa"] is None else f"{f['kappa']:.2f}"
    return f"{f['agree'] * 100:.0f} % (κ {kap}, n {f['n']})"


def render(report):
    lines = ["# Узгодженість суддів зі сліпою розміткою власника", "",
             "Частка збігів, коефіцієнт Коена (κ) і кількість пунктів. «Без позначок» виключає пункти з `eval/data/label_notes.json` "
             "(консультація з асистентом Claude, перевірка ринку через режим ШІ в Google); для знахідок суддя А і консенсус додатково без "
             "пунктів із неналежно незалежною міткою А.", ""]
    p = report["pairs"]
    lines += [f"## Пари (сліпа вибірка: {p['n_blind']}; збіг суддів між собою: {p['consensus_coverage'] * 100:.0f} % пунктів)", "",
              "| Суддя | 3 класи | Бінарно (релевантна / ні) | 3 класи без позначок | Бінарно без позначок |", "| --- | --- | --- | --- | --- |"]
    for name in ("judge A", "judge B", "consensus A=B", "A vs B (the same items)"):
        v = p[name]
        lines.append(f"| {name} | {cell(v['all']['3 classes'])} | {cell(v['all']['binary'])} | {cell(v['without notes']['3 classes'])} | {cell(v['without notes']['binary'])} |")
    f = report["findings"]
    lines += ["", f"## Знахідки (сліпа вибірка: {f['n_blind']}; збіг суддів між собою: {f['consensus_coverage'] * 100:.0f} % пунктів; "
                  f"пунктів зі спірною міткою А у вибірці: {len(f['contaminated_in_blind'])})", "",
              "| Суддя | true проти решти | 3 класи | true проти решти без позначок | 3 класи без позначок |", "| --- | --- | --- | --- | --- |"]
    for name in ("judge A", "judge B", "consensus A=B"):
        v = f[name]
        lines.append(f"| {name} | {cell(v['all']['true vs rest'])} | {cell(v['all']['3 classes'])} | {cell(v['without notes']['true vs rest'])} | {cell(v['without notes']['3 classes'])} |")
    c = report["calibration_b"]
    lines += ["", f"## Калібрування судді Б на {c['n']} пілотних парах (старі мітки власника; суддя А тут не калібрується)", "",
              "| 3 класи | Бінарно |", "| --- | --- |", f"| {cell(c['all']['3 classes'])} | {cell(c['all']['binary'])} |", ""]
    return "\n".join(lines)


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    report = compute()
    text = render(report)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    (OUT.with_suffix(".json")).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

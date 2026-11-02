"""Score each model's extraction against your hand-written answer keys.

Reads:   samples/workshop_XX_*.txt, samples/answer_key_XX.json,
         eval/outputs/<model>/XX_runN.json, eval/memo_rubric.csv (optional)
Writes:  eval/results/scorecard.md   (paste into the README)
         eval/results/scorecard.csv  (per transcript/run detail)
         eval/results/match_review.csv (check borderline fuzzy matches here)

Usage:   python eval/score_models.py
"""
import csv
import json
import re
from pathlib import Path
from statistics import mean

from rapidfuzz import fuzz

# ---- Settings -------------------------------------------------------------------------
MATCH_THRESHOLD = 55   # 0-100 similarity needed to count two items as "the same".
                       # Check match_review.csv: raise it if wrong pairs match, lower it
                       # if obvious paraphrases are missed.
WEIGHTS = {            # how much each metric counts toward the overall /10 score
    "decision_f1": 0.25,
    "no_false_decisions": 0.20,
    "action_f1": 0.15,
    "owner_accuracy": 0.15,
    "risk_recall": 0.10,
    "dependency_recall": 0.05,
    "schema_valid": 0.05,
    "memo_quality": 0.05,
}
# ---------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
SAMPLES, OUTPUTS = ROOT / "samples", ROOT / "eval" / "outputs"
RESULTS, RUBRIC = ROOT / "eval" / "results", ROOT / "eval" / "memo_rubric.csv"
BASELINE = ROOT / "eval" / "time_baseline.csv"  # optional: your manual write-up times

TEXT_OF = {  # the field compared for each category
    "decisions": lambda x: x.get("decision", ""),
    "open_issues": lambda x: x.get("issue", ""),
    "actions": lambda x: x.get("action", ""),
    "risks": lambda x: x.get("risk", ""),
    "dependencies": lambda x: f"{x.get('dependent', '')} depends on {x.get('depends_on', '')}",
}
REQUIRED_KEYS = ["workshop_summary", *TEXT_OF]
UNASSIGNED = {"", "unassigned", "none", "null", "tbd", "n/a", "unknown"}
RUBRIC_CRITERIA = ["accuracy", "clarity", "actionability", "concision"]


# ---- Helpers --------------------------------------------------------------------------
def similarity(a: str, b: str) -> float:
    """Average of two fuzzy scores: tolerant of reordering, not fooled by short subsets."""
    a, b = a.lower(), b.lower()
    return (fuzz.token_sort_ratio(a, b) + fuzz.token_set_ratio(a, b)) / 2


def match(key_items: list, out_items: list, text_of) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching, best pairs first."""
    pairs = sorted(((similarity(text_of(k), text_of(o)), i, j)
                    for i, k in enumerate(key_items) for j, o in enumerate(out_items)),
                   reverse=True)
    used_k, used_o, matches = set(), set(), []
    for score, i, j in pairs:
        if score < MATCH_THRESHOLD:
            break
        if i not in used_k and j not in used_o:
            used_k.add(i), used_o.add(j)
            matches.append((i, j, score))
    return matches


def f1(n_match: int, n_key: int, n_out: int) -> float:
    precision = n_match / n_out if n_out else float(n_key == 0)
    recall = n_match / n_key if n_key else 1.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def recall(n_match: int, n_key: int) -> float:
    return n_match / n_key if n_key else 1.0


def is_unassigned(owner) -> bool:
    return owner is None or str(owner).strip().lower() in UNASSIGNED


def owner_in_transcript(owner: str, transcript: str) -> bool:
    words = [w for w in re.findall(r"[a-zæøåäö]+", owner.lower()) if len(w) > 2]
    return any(w in transcript for w in words)


def load_extraction(record: dict):
    ext = record.get("extraction")
    if isinstance(ext, str):  # some models return the JSON as a string
        try:
            ext = json.loads(ext)
        except json.JSONDecodeError:
            return None
    return ext if isinstance(ext, dict) else None


def load_rubric() -> dict:
    if not RUBRIC.exists():
        return {}
    scores = {}
    with RUBRIC.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = [float(row[c]) for c in RUBRIC_CRITERIA if row.get(c, "").strip()]
            if vals:
                # zfill: Excel turns "01" into "1" when it saves a CSV
                key = (row["transcript_id"].zfill(2), row["model"], row["run"].strip())
                scores[key] = mean(vals) / 5
    return scores


# ---- Scoring --------------------------------------------------------------------------
def score_run(key: dict, ext, transcript: str, review: list, label: dict) -> dict:
    valid = isinstance(ext, dict) and all(k in ext for k in REQUIRED_KEYS) and all(
        isinstance(ext[k], list) for k in TEXT_OF)
    if not valid:  # failed or malformed run: scores zero rather than "nothing wrong found"
        zero = {k: 0.0 for k in WEIGHTS if k != "memo_quality"}
        return {**zero, "false_decisions": 0, "owner_errors": 0}

    m = {}
    for cat, text_of in TEXT_OF.items():
        k_items, o_items = key.get(cat, []), ext.get(cat, [])
        pairs = match(k_items, o_items, text_of)
        m[cat] = pairs
        matched_k = {i: (j, s) for i, j, s in pairs}
        matched_o = {j for _, j, _ in pairs}
        for i, item in enumerate(k_items):
            j, s = matched_k.get(i, (None, None))
            review.append({**label, "category": cat, "type": "expected",
                           "answer_key": text_of(item),
                           "model_output": text_of(o_items[j]) if j is not None else "",
                           "similarity": round(s, 1) if s else "",
                           "result": "matched" if j is not None else "MISSED"})
        for j, item in enumerate(o_items):
            if j not in matched_o:
                review.append({**label, "category": cat, "type": "extra", "answer_key": "",
                               "model_output": text_of(item), "similarity": "",
                               "result": "EXTRA (not in answer key)"})

    # Open issues the model wrongly presented as agreed decisions (the governance error)
    false_decisions = match(key.get("open_issues", []), ext.get("decisions", []),
                            lambda x: x.get("issue") or x.get("decision", ""))
    n_open = len(key.get("open_issues", []))

    # Owners: invented names, or a name where the answer key says nobody owns it
    out_actions, key_actions = ext.get("actions", []), key.get("actions", [])
    key_owner_of = {j: key_actions[i].get("owner") for i, j, _ in m["actions"]}
    owner_errors = 0
    for j, act in enumerate(out_actions):
        owner = act.get("owner")
        if is_unassigned(owner):
            continue
        if not owner_in_transcript(str(owner), transcript) or (
                j in key_owner_of and is_unassigned(key_owner_of[j])):
            owner_errors += 1

    def n(cat):
        return len(key.get(cat, [])), len(ext.get(cat, [])), len(m[cat])

    dk, do, dm = n("decisions")
    ak, ao, am = n("actions")
    return {
        "decision_f1": f1(dm, dk, do),
        "no_false_decisions": 1 - len(false_decisions) / n_open if n_open else 1.0,
        "action_f1": f1(am, ak, ao),
        "owner_accuracy": 1 - owner_errors / len(out_actions) if out_actions else None,
        "risk_recall": recall(len(m["risks"]), len(key.get("risks", []))),
        "dependency_recall": recall(len(m["dependencies"]), len(key.get("dependencies", []))),
        "schema_valid": float(valid),
        "false_decisions": len(false_decisions),
        "owner_errors": owner_errors,
    }


def overall(metrics: dict) -> float:
    used = {k: w for k, w in WEIGHTS.items() if metrics.get(k) is not None}
    return 10 * sum(metrics[k] * w for k, w in used.items()) / sum(used.values())


def main() -> None:
    rubric = load_rubric()
    rows, review = [], []
    for key_path in sorted(SAMPLES.glob("answer_key_*.json")):
        tid = key_path.stem.split("_")[-1]
        if not tid.isdigit():
            continue  # skips answer_key_TEMPLATE.json
        key = json.loads(key_path.read_text(encoding="utf-8"))
        t_files = list(SAMPLES.glob(f"workshop_{tid}_*.txt"))
        transcript = t_files[0].read_text(encoding="utf-8").lower() if t_files else ""
        for out_path in sorted(OUTPUTS.glob(f"*/{tid}_run*.json")):
            rec = json.loads(out_path.read_text(encoding="utf-8"))
            label = {"model": rec["model"], "transcript_id": tid, "run": str(rec["run"])}
            metrics = score_run(key, load_extraction(rec), transcript, review, label)
            metrics["memo_quality"] = rubric.get((tid, rec["model"], str(rec["run"])))
            metrics["overall_10"] = overall(metrics)
            rows.append({**label, **metrics, "latency_s": rec.get("latency_s"),
                         "error": rec.get("error") or ""})

    if not rows:
        raise SystemExit("Nothing to score. Add samples/answer_key_01.json etc. "
                         "and run eval/run_eval.py first.")

    RESULTS.mkdir(parents=True, exist_ok=True)
    write_csv(RESULTS / "scorecard.csv", rows)
    write_csv(RESULTS / "match_review.csv", review)
    md = scorecard_markdown(rows) + time_impact_markdown(rows)
    (RESULTS / "scorecard.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\nDetail: {RESULTS / 'scorecard.csv'}\nCheck matches: {RESULTS / 'match_review.csv'}")


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def scorecard_markdown(rows: list[dict]) -> str:
    models = sorted({r["model"] for r in rows})
    labels = {
        "decision_f1": "Decisions found (F1)",
        "no_false_decisions": "Open issues NOT passed off as decisions",
        "action_f1": "Actions found (F1)",
        "owner_accuracy": "Owner accuracy (no invented owners)",
        "risk_recall": "Risks found (recall)",
        "dependency_recall": "Dependencies found (recall)",
        "schema_valid": "Valid output structure",
        "memo_quality": "Memo quality (your 1-5 rubric)",
    }

    def avg(model, metric):
        vals = [r[metric] for r in rows if r["model"] == model and r[metric] not in (None, "")]
        return mean(vals) if vals else None

    def pct(v):
        return "n/a" if v is None else f"{v:.0%}"

    lines = ["| Metric | Weight | " + " | ".join(models) + " |",
             "|---|---|" + "---|" * len(models)]
    for metric, label in labels.items():
        lines.append(f"| {label} | {WEIGHTS[metric]:.0%} | "
                     + " | ".join(pct(avg(m, metric)) for m in models) + " |")
    totals = {m: avg(m, "overall_10") for m in models}
    lines.append("| **Overall score** | | " + " | ".join(f"**{totals[m]:.1f} / 10**"
                                                     for m in models) + " |")
    lines.append("| Avg response time | | " + " | ".join(f"{avg(m, 'latency_s'):.1f}s"
                                                     for m in models) + " |")
    lines.append("| Failed runs | | " + " | ".join(
        str(sum(1 for r in rows if r["model"] == m and r["error"])) for m in models) + " |")
    ranked = sorted(models, key=lambda m: totals[m], reverse=True)
    lines.append(f"\n**Ranking:** " + " > ".join(f"{m} ({totals[m]:.1f})" for m in ranked))
    return "\n".join(lines)


def time_impact_markdown(rows: list[dict]) -> str:
    """Compare your manual write-up time with pipeline time + your review time."""
    if not BASELINE.exists():
        return ""
    base = {}
    with BASELINE.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("manual_minutes", "").strip():
                base[r["transcript_id"].zfill(2)] = (float(r["manual_minutes"]),
                                                     float(r.get("review_minutes") or 0))
    if not base:
        return ""
    manual = mean(m for m, _ in base.values())
    review = mean(rv for _, rv in base.values())
    lines = ["\n\n**Time per workshop write-up** "
             f"(average of {len(base)} transcript(s) you timed)\n",
             "| Model | Manual write-up | Pipeline + your review | Time saved |",
             "|---|---|---|---|"]
    for model in sorted({r["model"] for r in rows}):
        lat = [r["latency_s"] for r in rows
               if r["model"] == model and r["transcript_id"] in base and not r["error"]]
        if lat:
            pipeline = mean(lat) / 60 + review
            lines.append(f"| {model} | {manual:.0f} min | {pipeline:.1f} min | "
                         f"{1 - pipeline / manual:.0%} |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()

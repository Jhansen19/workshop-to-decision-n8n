"""Send every sample transcript through the local n8n eval webhook, once per model.

Saves one JSON file per transcript/model/run to eval/outputs/<model>/, a memo .md next to it,
and adds any new rows to eval/memo_rubric.csv for manual memo scoring.

Usage (n8n must be running locally and the "Eval - Extract" workflow active):
    python eval/run_eval.py              # both models
    python eval/run_eval.py groq         # one model only (handy when the other hits a quota)
"""
import csv
import json
import sys
import time
from pathlib import Path

import requests

# ---- Settings -------------------------------------------------------------------------
WEBHOOK_URL = "http://localhost:5678/webhook/eval-extract"
MODELS = sys.argv[1:] or ["gemini", "groq"]  # values the Model Selector routes on
                                             # (pass one on the command line to run just that model)
RUNS = 1                          # >1 lets you check consistency (same input, repeated)
PAUSE_SECONDS = 65                # free tiers cap tokens per MINUTE (Groq ~8k for gpt-oss-120b);
                                  # one run uses several thousand, so wait for the limit to reset
TIMEOUT_SECONDS = 180
# ---------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
OUTPUTS = ROOT / "eval" / "outputs"
RUBRIC = ROOT / "eval" / "memo_rubric.csv"
RUBRIC_FIELDS = ["transcript_id", "model", "run", "memo_file",
                 "accuracy", "clarity", "actionability", "concision", "notes"]


def transcript_id(path: Path) -> str:
    """workshop_01_replenishment.txt -> '01'"""
    return path.stem.split("_")[1]


def call_webhook(text: str, model: str) -> dict:
    start = time.perf_counter()
    try:
        resp = requests.post(WEBHOOK_URL, json={"transcript": text, "model": model},
                             timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        body, error = resp.json(), None
    except Exception as exc:  # network error, HTTP error, invalid JSON
        body, error = {}, str(exc)
    return {"latency_s": round(time.perf_counter() - start, 2), "error": error,
            "extraction": body.get("extraction", {}), "memo": body.get("memo", "")}


def update_rubric(rows: list[dict]) -> None:
    """Append rows for new runs; never overwrite scores you've already entered."""
    existing = []
    if RUBRIC.exists():
        with RUBRIC.open(newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    seen = {(r["transcript_id"], r["model"], r["run"]) for r in existing}
    new = [r for r in rows if (r["transcript_id"], r["model"], r["run"]) not in seen]
    with RUBRIC.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUBRIC_FIELDS)
        writer.writeheader()
        writer.writerows(existing + new)


def main() -> None:
    transcripts = sorted(SAMPLES.glob("workshop_*.txt"))
    if not transcripts:
        sys.exit(f"No transcripts found in {SAMPLES} (expected workshop_01_<topic>.txt etc.)")

    rubric_rows = []
    for path in transcripts:
        tid, text = transcript_id(path), path.read_text(encoding="utf-8")
        for model in MODELS:
            for run in range(1, RUNS + 1):
                result = call_webhook(text, model)
                record = {"transcript_id": tid, "model": model, "run": run, **result}

                out_dir = OUTPUTS / model
                out_dir.mkdir(parents=True, exist_ok=True)
                stem = f"{tid}_run{run}"
                (out_dir / f"{stem}.json").write_text(
                    json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
                memo_file = out_dir / f"{stem}_memo.md"
                memo_file.write_text(record["memo"] or "(no memo returned)", encoding="utf-8")

                rubric_rows.append({"transcript_id": tid, "model": model, "run": str(run),
                                    "memo_file": str(memo_file.relative_to(ROOT))})
                status = "ERROR: " + result["error"] if result["error"] else "ok"
                print(f"[{model:>6}] transcript {tid} run {run}: {result['latency_s']}s  {status}")
                time.sleep(PAUSE_SECONDS)

    update_rubric(rubric_rows)
    print(f"\nDone. Optional: score the memos 1-5 in {RUBRIC.relative_to(ROOT)}, "
          "then run: python eval/score_models.py")


if __name__ == "__main__":
    main()

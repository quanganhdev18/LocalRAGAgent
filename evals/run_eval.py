"""Run the golden set: index the synthetic corpus, query it, report Recall@10 / MRR@10 / latency.

    python evals/run_eval.py [--no-ocr] [--no-fail] [--out evals/results]

Thresholds are the spec's (section 9). They are never lowered silently: groups that cannot be
measured (e.g. OCR without Tesseract) are reported as SKIPPED, not as passed.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from localrag.config import load_config  # noqa: E402
from localrag.core import Core  # noqa: E402
from localrag.ocr import find_tesseract  # noqa: E402
import make_golden  # noqa: E402

THRESHOLDS = {  # group -> (metric, minimum)
    "overall": ("recall", 0.85), "exact": ("recall", 0.95), "nodiacritic": ("recall", 0.85),
    "vi2en": ("recall", 0.70), "pptx": ("recall", 0.85), "ocr": ("recall", 0.70),
    "mrr": ("mrr", 0.60), "p95_latency_s": ("latency", 5.0),
}


def evaluate(core: Core, queries: list[dict], doc_by_file: dict[str, str]) -> list[dict]:
    rows = []
    for q in queries:
        t0 = time.perf_counter()
        hits = core.search.search(q["query"], limit=10)
        dt = time.perf_counter() - t0
        ranked = [doc_by_file.get(h.file_name) for h in hits]
        rank = next((i + 1 for i, d in enumerate(ranked) if d == q["doc"]), None) if q["doc"] else None
        rows.append({**q, "rank": rank, "latency_s": dt, "top": ranked[:3]})
    return rows


def summarize(rows: list[dict], ocr_ran: bool) -> dict:
    ans = [r for r in rows if r["doc"] and (ocr_ran or r["doc_group"] != "ocr")]  # unmeasurable groups are excluded
    def rec(sel):
        return round(sum(1 for r in sel if r["rank"]) / len(sel), 3) if sel else None
    groups = {
        "overall": rec(ans),
        "exact": rec([r for r in ans if r["type"] == "exact"]),
        "nodiacritic": rec([r for r in ans if r["type"] == "nodiacritic"]),
        "vi2en": rec([r for r in ans if r["type"] == "vi2en"]),
        "pptx": rec([r for r in ans if r["doc_group"] == "pptx"]),
        "ocr": rec([r for r in ans if r["doc_group"] == "ocr"]) if ocr_ran else None,
    }
    scored = ans
    groups["mrr"] = round(sum(1 / r["rank"] for r in scored if r["rank"]) / len(scored), 3)
    lat = sorted(r["latency_s"] for r in rows)
    groups["p50_latency_s"] = round(lat[len(lat) // 2], 3)
    groups["p95_latency_s"] = round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 3)
    # "no answer" queries: informational (no threshold in the spec)
    none = [r for r in rows if r["type"] == "none"]
    groups["none_queries"] = len(none)
    return groups


def verdict(g: dict) -> dict:
    out = {}
    for k, (kind, thr) in THRESHOLDS.items():
        v = g.get(k)
        if v is None:
            out[k] = "SKIPPED"
        else:
            out[k] = "PASS" if (v <= thr if kind == "latency" else v >= thr) else "FAIL"
    return out


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--no-fail", action="store_true")
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()

    gen = HERE / "_generated"
    expected = make_golden.generate(gen)
    doc_by_file = {d["file"]: d["id"] for d in expected["docs"]}

    cfg = load_config()
    tmp = Path(tempfile.mkdtemp(prefix="localrag_eval_"))
    cfg.data["paths"]["data_dir"] = str(tmp / "data")
    cfg.data["paths"]["index_dir"] = str(tmp / "idx")
    core = Core(cfg)
    for p in core.startup_model_check():
        sys.exit("Model embedding chưa sẵn sàng: " + p)
    tess = None if a.no_ocr else find_tesseract(cfg)
    core.db.add_folder(str(gen), "always" if tess else "never")
    t0 = time.time()
    core.indexer.start()
    core.indexer.wait()
    if tess:
        core.ocr.wait()
    index_s = time.time() - t0
    core.indexer.close()

    rows = evaluate(core, expected["queries"], doc_by_file)
    g = summarize(rows, ocr_ran=bool(tess))
    v = verdict(g)
    statuses = dict(core.db.index_status()["by_status"])
    result = {"ocr_engine": str(tess) if tess else None, "index_seconds": round(index_s, 1),
              "statuses": statuses, "metrics": g, "verdict": v,
              "misses": [{k: r[k] for k in ("doc", "type", "query", "top")} for r in rows if r["doc"] and not r["rank"] and (tess or r["doc_group"] != "ocr")]}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# Kết quả golden set", "", f"OCR: {'Tesseract' if tess else 'KHÔNG CHẠY (thiếu Tesseract hoặc --no-ocr)'}  ",
          f"Index: {result['index_seconds']} giây · trạng thái: {statuses}", "",
          "| Chỉ số | Giá trị | Ngưỡng | Kết quả |", "|---|---|---|---|"]
    for k, (_, thr) in THRESHOLDS.items():
        md.append(f"| {k} | {g.get(k)} | {thr} | {v[k]} |")
    md += ["", f"Truy vấn trượt: {len(result['misses'])}"]
    md += [f"- [{m['type']}] {m['query']} (cần {m['doc']}, top: {m['top']})" for m in result["misses"]]
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    failed = [k for k, x in v.items() if x == "FAIL"]
    return 0 if (a.no_fail or not failed) else 1


if __name__ == "__main__":
    sys.exit(main())

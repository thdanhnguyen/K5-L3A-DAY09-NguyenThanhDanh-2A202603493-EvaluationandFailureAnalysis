"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def _ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Kiểm tra ratchet: trên cùng eval_set_version, spec mới không được nới lỏng hơn base_spec."""
    if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
        return []
    problems: list[str] = []
    # 1) Kiểm tra danh sách metrics
    spec_metrics = {m["id"]: m for m in (spec.get("metrics") or [])}
    for bm in base_spec.get("metrics") or []:
        mid = bm["id"]
        if mid not in spec_metrics:
            problems.append(f"ratchet: metric {mid!r} disappeared from spec")
            continue
        pm = spec_metrics[mid]
        if bm.get("blocking") and not pm.get("blocking"):
            problems.append(f"ratchet: blocking metric {mid!r} became non-blocking")
        bth = bm.get("threshold") or {}
        pth = pm.get("threshold") or {}
        if "max" in bth and ("max" not in pth or pth["max"] > bth["max"]):
            problems.append(f"ratchet: {mid}.max loosened ({pth.get('max')} > {bth['max']})")
        if "min" in bth and ("min" not in pth or pth["min"] < bth["min"]):
            problems.append(f"ratchet: {mid}.min loosened ({pth.get('min')} < {bth['min']})")
        if "max_increase" in bth and ("max_increase" not in pth or pth["max_increase"] > bth["max_increase"]):
            problems.append(f"ratchet: {mid}.max_increase loosened ({pth.get('max_increase')} > {bth['max_increase']})")
        if bth.get("no_significant_drop") and not pth.get("no_significant_drop"):
            problems.append(f"ratchet: {mid}.no_significant_drop dropped")
    # 2) Kiểm tra danh sách slices
    spec_slices = {(s["name"], s["metric"]): s for s in (spec.get("slices") or [])}
    for bs in base_spec.get("slices") or []:
        key = (bs["name"], bs["metric"])
        if key not in spec_slices:
            problems.append(f"ratchet: slice {key[0]}/{key[1]} disappeared from spec")
            continue
        ps = spec_slices[key]
        if bs.get("blocking") and not ps.get("blocking"):
            problems.append(f"ratchet: blocking slice {key[0]}/{key[1]} became non-blocking")
        if "min" in bs and ("min" not in ps or ps["min"] < bs["min"]):
            problems.append(f"ratchet: slice {key[0]}/{key[1]}.min loosened ({ps.get('min')} < {bs['min']})")
        if "max" in bs and ("max" not in ps or ps["max"] > bs["max"]):
            problems.append(f"ratchet: slice {key[0]}/{key[1]}.max loosened ({ps.get('max')} > {bs['max']})")
        if bs.get("no_significant_drop") and not ps.get("no_significant_drop"):
            problems.append(f"ratchet: slice {key[0]}/{key[1]}.no_significant_drop dropped")
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate."""
    problems: list[str] = []
    # 1) Chặn NaN / Inf trong metrics tổng hợp (NaN < min trả False nên gate ngây thơ sẽ cho qua)
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"non-finite metric {k}={v!r}")
    # 2) Chặn nếu có bất kỳ evaluator nào crash trong quá trình chạy (kể cả khi điểm vẫn xanh)
    failures = pr.get("evaluator_failures") or []
    if failures:
        problems.append(f"{len(failures)} evaluator failure(s): {failures[0]}")
    pr_rows = pr.get("rows") or []
    base_rows = base.get("rows") or []
    # 3) Mọi metric mức dòng phải có giá trị hợp lệ (không None / NaN) ở tất cả row
    row_keys = set(GRADERS) | (set(base_rows[0].keys()) if base_rows else set())
    graded_ids = [m["id"] for m in (spec.get("metrics") or []) if m.get("id") in row_keys]
    for idx, r in enumerate(pr_rows):
        for mid in graded_ids:
            val = r.get(mid)
            if val is None or (isinstance(val, float) and not math.isfinite(val)):
                problems.append(f"row {r.get('item_id')}@{r.get('seed')} (#{idx}) missing/invalid {mid}={val!r}")
                break
    # 4) Số dòng phải khớp manifest (items * seeds) và khớp với baseline (chống drop/duplicate dòng)
    manifest = pr.get("manifest") or {}
    expected_n = int(manifest.get("items") or 0) * len(manifest.get("seeds") or [])
    if len(pr_rows) != expected_n:
        problems.append(f"row count {len(pr_rows)} != manifest {manifest.get('items')}x{len(manifest.get('seeds') or [])}={expected_n}")
    if len(pr_rows) != len(base_rows):
        problems.append(f"row count {len(pr_rows)} != baseline {len(base_rows)}")
    # 5) Tập (item_id, seed) không được trùng lặp (dòng trùng) và phải khớp 1-1 với baseline (chống cherry-pick seed)
    pr_pairs = [(r.get("item_id"), r.get("seed")) for r in pr_rows]
    base_pairs = [(r.get("item_id"), r.get("seed")) for r in base_rows]
    if len(pr_pairs) != len(set(pr_pairs)):
        problems.append(f"duplicate (item_id, seed) rows ({len(pr_pairs)} total, {len(set(pr_pairs))} unique)")
    if set(pr_pairs) != set(base_pairs):
        missing = sorted(set(base_pairs) - set(pr_pairs))[:3]
        extra = sorted(set(pr_pairs) - set(base_pairs))[:3]
        problems.append(f"(item_id, seed) set differs from baseline (missing={missing}, extra={extra})")
    # 6) Nhãn slice trên từng item không được thay đổi so với baseline (chống gán nhãn lại để né slice gate)
    base_slices = {(r.get("item_id"), r.get("seed")): sorted(r.get("slices") or []) for r in base_rows}
    for r in pr_rows:
        key = (r.get("item_id"), r.get("seed"))
        if key in base_slices and sorted(r.get("slices") or []) != base_slices[key]:
            problems.append(f"slice tags changed for {key[0]}@{key[1]}: {r.get('slices')} != {base_slices[key]}")
            break
    # 7) Ratchet: không cho nới ngưỡng hay bỏ slice/metric trên cùng eval_set_version
    if base_spec is not None:
        problems.extend(_ratchet_problems(spec, base_spec))
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked: list[str] = []
    lines: list[str] = []
    bs = spec.get("bootstrap", {})
    for sl in spec.get("slices") or []:
        name = sl["name"]
        metric = sl["metric"]
        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        raw_val = (sum(a.values()) / len(a)) if a else None
        disp_val = round(raw_val, 4) if raw_val is not None else None
        verdict, note = "ok", ""
        if raw_val is None:
            verdict = "missing"
        else:
            if "min" in sl and raw_val < sl["min"]:
                verdict = "fail"
            if "max" in sl and raw_val > sl["max"]:
                verdict = "fail"
        if sl.get("no_significant_drop") and raw_val is not None:
            keys = sorted(set(a) & set(b))
            if keys:
                # Chạy paired bootstrap trên riêng các item thuộc slice đó
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in keys],
                    [b[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000),
                    rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(f"slice:{name}/{metric}")
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        th = {k: sl[k] for k in ("min", "max", "no_significant_drop") if k in sl}
        lines.append(f"  slice:{name}/{metric:<12} {disp_val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

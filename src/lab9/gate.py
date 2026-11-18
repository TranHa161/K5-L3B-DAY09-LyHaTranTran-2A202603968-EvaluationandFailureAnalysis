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
from lab9.eval import SPEC, aggregate, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    from lab9.graders import GRADERS

    problems: list[str] = []
    rows = pr.get("rows") or []
    man, bman = pr.get("manifest") or {}, base.get("manifest") or {}

    # 1. Non-finite metric values: NaN < min is False, so a naive comparison lets NaN through.
    for k, v in (pr.get("metrics") or {}).items():
        if isinstance(v, float) and not math.isfinite(v):
            problems.append(f"metric {k} is {v} (not finite)")

    # 2. Row count and duplicates: every (item, seed) exactly once.
    want_n = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want_n:
        problems.append(f"{len(rows)} rows, manifest promises {man.get('items')} items x "
                        f"{len(man.get('seeds') or [])} seeds = {want_n}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"{len(dups)} duplicated (item, seed) row(s), e.g. {dups[0][0]}@{dups[0][1]}")

    # 3. Same trial set and manifest as the baseline (no cherry-picked seeds or items).
    bkeys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != bkeys:
        miss, extra = len(bkeys - set(keys)), len(set(keys) - bkeys)
        problems.append(f"(item, seed) set differs from baseline: {miss} missing, {extra} extra")
    for f in ("items", "seeds"):
        if man.get(f) != bman.get(f):
            problems.append(f"manifest {f} {man.get(f)!r} != baseline {bman.get(f)!r}")

    # 4. Crashed graders: evaluator failures, or a graded metric that is None / absent on a row.
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s), "
                        f"first: {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for mid in graded:
        n_none = sum(r.get(mid) is None for r in rows)
        if n_none:
            problems.append(f"{n_none} row(s) have no value for graded metric {mid}")

    # 5. Reported metrics must be what the rows say (hand-edited report / metric dropped).
    #    Recompute with the same aggregate() that wrote the report, so pass_5, pass_hat_k and
    #    cost_per_success are covered too, not only the graded metrics.
    on_rows = [mid for mid in graded if rows and all(r.get(mid) is not None for r in rows)]
    try:
        want_all = aggregate(rows, on_rows, k_values=spec.get("pass_k", []))
    except (KeyError, TypeError, ValueError):
        # rows without cost (hand-built reports): fall back to the graded metrics only
        want_all = {mid: (sum(bool(r[mid]) for r in rows) if mid in ("secret_leak", "approval_bypass")
                          else round(sum(bool(r[mid]) for r in rows) / len(rows), 4)) for mid in on_rows}
    reported = pr.get("metrics") or {}
    for mid in on_rows:
        if mid not in reported:
            problems.append(f"metric {mid} graded on rows but missing from report metrics")
    for mid, want in want_all.items():
        if mid not in reported or want is None:
            continue
        got = reported[mid]
        if not isinstance(got, (int, float)) or isinstance(got, bool) or not math.isfinite(got) \
                or abs(got - want) > 1e-4:
            problems.append(f"metric {mid} = {got} but rows give {want}")

    # 6. Slice tags must match the baseline's for every item (no relabelling out of a slice).
    def tags(rep: dict) -> dict[str, set[frozenset]]:
        out: dict[str, set[frozenset]] = {}
        for r in rep.get("rows") or []:
            out.setdefault(r.get("item_id"), set()).add(frozenset(r.get("slices") or []))
        return out
    pt, bt = tags(pr), tags(base)
    for item in sorted(set(pt) & set(bt), key=str):
        if pt[item] != bt[item]:
            problems.append(f"{item}: slice tags {sorted(map(sorted, pt[item]))} != baseline "
                            f"{sorted(map(sorted, bt[item]))}")

    # 7. Ratchet: on the same eval-set version thresholds may only get stricter.
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        problems += _ratchet(base_spec, spec)
    return problems


def _looser(what: str, old: dict, new: dict, old_blocking: bool, new_blocking: bool) -> list[str]:
    out = []
    if old_blocking and not new_blocking:
        out.append(f"ratchet: {what} no longer blocking")
    for k in ("max", "max_increase"):
        if k in old and (k not in new or new[k] > old[k]):
            out.append(f"ratchet: {what} {k} {old[k]} -> {new.get(k, 'removed')}")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"ratchet: {what} min {old['min']} -> {new.get('min', 'removed')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"ratchet: {what} dropped no_significant_drop")
    return out


def _ratchet(old: dict, new: dict) -> list[str]:
    out = []
    new_m = {m["id"]: m for m in new.get("metrics") or []}
    for m in old.get("metrics") or []:
        n = new_m.get(m["id"])
        if n is None:
            out.append(f"ratchet: metric {m['id']} removed")
            continue
        out += _looser(f"metric {m['id']}", m.get("threshold") or {}, n.get("threshold") or {},
                       bool(m.get("blocking")), bool(n.get("blocking")))
    new_s = {(s["name"], s["metric"]): s for s in new.get("slices") or []}
    for s in old.get("slices") or []:
        n = new_s.get((s["name"], s["metric"]))
        if n is None:
            out.append(f"ratchet: slice {s['name']}/{s['metric']} removed")
            continue
        out += _looser(f"slice {s['name']}/{s['metric']}", s, n, bool(s.get("blocking")), bool(n.get("blocking")))
    return out


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
        name, metric = sl["name"], sl["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note = "ok", ""
        if not a:
            # An empty slice cannot vouch for anything: treat it as missing, never as a pass.
            val, verdict = None, "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in sl and val < sl["min"]:
                verdict = "fail"
            if sl.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027),
                                                       confidence=bs.get("confidence", 0.95))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
                else:
                    verdict, note = "missing", "no shared items with baseline"
        if verdict != "ok" and sl.get("blocking"):
            blocked.append(sid)
        th = {k: sl[k] for k in ("min", "no_significant_drop") if k in sl}
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if sl.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
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

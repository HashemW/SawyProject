"""Measure how well search finds the record each test question was written for: the share of
questions whose record comes back first, in the top 5, 10, 20 and 50 (recall@k), and the mean
reciprocal rank over the top 100 (MRR), for each search component alone and for fused combinations.

Input:  --index    index folder (build_index.py)
        --queries  eval/retrieval.jsonl (merge_queries.py)
Output: tables on stdout; --out a JSON file with every question's rank under every configuration

Run: .venv/Scripts/python -I -X utf8 scripts/eval_retrieval.py --index data/work/index --queries eval/retrieval.jsonl --split dev

A record counts as found only if it is the one the question was written for. Another fatwa that
answers the question as well (the Sheikh often answered the same issue several times) counts as a
miss, so the numbers are a lower bound.
"""
import argparse
import collections
import itertools
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from search import Index  # noqa: E402

FIELDS = ("ar", "ar_short", "en")
KS = (1, 5, 10, 20, 50)
DEPTH = 100


def metrics(ranks):
    n = len(ranks)
    out = {f"R@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS}
    out["MRR"] = sum(1 / r for r in ranks if r) / n
    return out


def components(meta):
    out = [f"bm25:{b['field']}:{b['stemmer']}" for b in meta["bm25"]]
    return out + [f"dense:{f}:{d['model']}" for d in meta["dense"] for f in ("q", "p")]


def configs(comps):
    """Default fusion configurations, {name: {component: weight}}: each component alone; each kind
    over both fields; keyword search plus embeddings, both fields each."""
    bm25 = sorted({c.split(":")[2] for c in comps if c.startswith("bm25")})
    dense = sorted({c.split(":")[2] for c in comps if c.startswith("dense")})
    out = {c: {c: 1.0} for c in comps}
    for s in bm25:
        out[f"bm25 q+p {s}"] = {f"bm25:q:{s}": 1.0, f"bm25:p:{s}": 1.0}
    for m in dense:
        out[f"dense q+p {m}"] = {f"dense:q:{m}": 1.0, f"dense:p:{m}": 1.0}
    for s, m in itertools.product(bm25, dense):
        out[f"hybrid {s} + {m}"] = {f"bm25:q:{s}": 1.0, f"bm25:p:{s}": 1.0, f"dense:q:{m}": 1.0, f"dense:p:{m}": 1.0}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=pathlib.Path, required=True)
    ap.add_argument("--queries", type=pathlib.Path, required=True)
    ap.add_argument("--split", default="dev", choices=("dev", "test", "all"))
    ap.add_argument("--only", help="comma-separated configuration names to report (default: all)")
    ap.add_argument("--configs", type=pathlib.Path, help="JSON file {name: {component: weight}} to evaluate instead")
    ap.add_argument("--out", type=pathlib.Path)
    args = ap.parse_args()
    index = Index(args.index)
    rec_of = {rid: i for i, rid in enumerate(index.ids)}
    rows = [q for q in map(json.loads, open(args.queries, encoding="utf-8")) if args.split in ("all", q["split"])]
    confs = json.loads(args.configs.read_text(encoding="utf-8")) if args.configs else configs(components(index.meta))
    if args.only:
        confs = {k: v for k, v in confs.items() if k in args.only.split(",")}
    # A configuration is {component: weight}, or {"weights": {component: weight}, "k": RRF constant}.
    confs = {name: (c["weights"], c.get("k", 60)) if "weights" in c else (c, 60) for name, c in confs.items()}
    comps = sorted({c for w, _ in confs.values() for c in w})
    models = sorted({c.split(":")[2] for c in comps if c.startswith("dense")})
    vectors = {(m, field): index.query_vectors([q[field] for q in rows], m) for m in models for field in FIELDS}
    print("questions embedded", file=sys.stderr, flush=True)
    ranks = collections.defaultdict(dict)        # (config, field) -> {record id: rank or None}
    for n, q in enumerate(rows, 1):
        target = rec_of[q["id"]]
        for field in FIELDS:
            lists = index.rankings(q[field], comps, depth=DEPTH, vectors={m: vectors[m, field][n - 1] for m in models})
            for name, (cs, rrf_k) in confs.items():
                use = {c: lists[c] for c in cs if c in lists}
                if not use:
                    continue                     # keyword search alone, on a question with no Arabic
                order, _ = index.fuse(use, cs, k=rrf_k)
                order = order[:DEPTH]
                ranks[name, field][q["id"]] = order.index(target) + 1 if target in order else None
        if n % 25 == 0:
            print(f"{n}/{len(rows)} questions", file=sys.stderr, flush=True)
    types = {q["id"]: q["type"] for q in rows}
    report = {}
    for field in FIELDS:
        print(f"\n## {field} ({args.split}, {len(rows)} questions)\n")
        print("| configuration | " + " | ".join(f"R@{k}" for k in KS) + " | MRR |")
        print("|---|" + "---|" * (len(KS) + 1))
        for name in confs:
            if (name, field) not in ranks:
                continue
            m = metrics(list(ranks[name, field].values()))
            by_type = {t: metrics([r for rid, r in ranks[name, field].items() if types[rid] == t])
                       for t in sorted(set(types.values()))}
            report[f"{name} | {field}"] = dict(all=m, by_type=by_type, ranks=ranks[name, field])
            print(f"| {name} | " + " | ".join(f"{m[f'R@{k}']:.2f}" for k in KS) + f" | {m['MRR']:.3f} |")
    print(f"\n## mean over {', '.join(FIELDS)} ({args.split})\n")
    print("| configuration | " + " | ".join(f"R@{k}" for k in KS) + " | MRR |")
    print("|---|" + "---|" * (len(KS) + 1))
    for name in confs:
        ms = [report[f"{name} | {f}"]["all"] for f in FIELDS if f"{name} | {f}" in report]
        if len(ms) == len(FIELDS):               # keyword search alone has no English results
            avg = {key: sum(m[key] for m in ms) / len(ms) for key in ms[0]}
            print(f"| {name} | " + " | ".join(f"{avg[f'R@{k}']:.2f}" for k in KS) + f" | {avg['MRR']:.3f} |")
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

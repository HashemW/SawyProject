"""Measure reranking: each test question's first N search candidates (search.DEFAULT) are scored by
the cross-encoder (rerank.py) on each of their texts, and the rank of the record the question was
written for is compared under the search order and under orders built from the reranker's scores.

Input:  --index, --records, --queries eval/retrieval.jsonl
Output: tables on stdout; --out a JSON file with every question's candidates and scores, so other
        orders can be computed without running the model again (--scores reads such a file)

Run: .venv/Scripts/python -I -X utf8 scripts/eval_rerank.py --split dev --out data/work/index/eval_rerank_dev.json

As in eval_retrieval.py, only the record the question was written for counts as found, so the
numbers are a lower bound.
"""
import argparse
import collections
import json
import pathlib
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from rerank import Reranker, load_corpus, unit_texts  # noqa: E402
from search import DEFAULT, ROOT, Index, dense_text  # noqa: E402

FIELDS = ("ar", "ar_short", "en")
KS = (1, 3, 5, 10, 15, 20, 30, 50)


def orders(cands):
    """Candidate orders to compare, {name: [record id, ...]}, from one question's scored candidates
    (search order, with each candidate's best «q» and best «p» reranker score)."""
    search = [c["id"] for c in cands]
    srank = {c["id"]: i for i, c in enumerate(cands)}
    out = {"search": search}
    q = {c["id"]: c["q"] for c in cands}
    p = {c["id"]: c["p"] for c in cands}
    both = {c["id"]: max(c["q"], c["p"]) for c in cands}
    for name, s in (("rerank q", q), ("rerank p", p), ("rerank max(q,p)", both)):
        out[name] = sorted(s, key=lambda i: (-s[i], srank[i]))
    # Reciprocal rank fusion of the search order and the reranker's, at two weights.
    rr = {i: r for r, i in enumerate(out["rerank max(q,p)"])}
    for w in (1.0, 2.0):
        f = {i: 1 / (10 + srank[i] + 1) + w / (10 + rr[i] + 1) for i in srank}
        out[f"rrf search + {w:g}x rerank"] = sorted(f, key=lambda i: (-f[i], srank[i]))
    return out


def metrics(ranks, n):
    out = {f"R@{k}": sum(1 for r in ranks if r and r <= k) / n for k in KS}
    out["MRR"] = sum(1 / r for r in ranks if r) / n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=pathlib.Path, default=ROOT / "data" / "work" / "index")
    ap.add_argument("--records", type=pathlib.Path, default=ROOT / "data" / "work" / "records")
    ap.add_argument("--queries", type=pathlib.Path, default=ROOT / "eval" / "retrieval.jsonl")
    ap.add_argument("--split", default="dev", choices=("dev", "test", "all"))
    ap.add_argument("-n", type=int, default=50, help="search candidates reranked")
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--scores", type=pathlib.Path, help="an --out file of an earlier run: report it again without the model")
    args = ap.parse_args()
    rows = [q for q in map(json.loads, open(args.queries, encoding="utf-8")) if args.split in ("all", q["split"])]
    if args.scores:
        scored = json.loads(args.scores.read_text(encoding="utf-8"))
    else:
        index = Index(args.index)
        if index.stale():
            sys.exit("the corpus changed after this index was built; run build_index.py")
        corpus = load_corpus(args.records / "corpus.jsonl")
        models = sorted({c.split(":")[2] for c in DEFAULT if c.startswith("dense")})
        vectors = {(m, f): index.query_vectors([q[f] for q in rows], m) for m in models for f in FIELDS}
        index.unload_models()
        reranker = Reranker()
        scored, t0, pairs = [], time.time(), 0
        for n, q in enumerate(rows):
            for f in FIELDS:
                hits = index.search(q[f], args.n, vectors={m: vectors[m, f][n] for m in models})
                texts = [(h, kind, text) for h in hits for kind, _, text in unit_texts(index, corpus, h["rec"], h["passage"])]
                s = reranker.scores([(dense_text(q[f]), t) for _, _, t in texts])
                pairs += len(texts)
                best = collections.defaultdict(lambda: {"q": -np.inf, "p": -np.inf})
                for (h, kind, _), x in zip(texts, s):
                    best[h["id"]][kind] = max(best[h["id"]][kind], float(x))
                scored.append(dict(id=q["id"], field=f, type=q["type"],
                                   cands=[dict(id=h["id"], q=best[h["id"]]["q"], p=best[h["id"]]["p"]) for h in hits]))
            if (n + 1) % 25 == 0:
                print(f"{n + 1}/{len(rows)} questions, {pairs:,} pairs, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
        if args.out:
            args.out.write_text(json.dumps(scored, ensure_ascii=False), encoding="utf-8")
    ranks = collections.defaultdict(list)        # (order, field, type) -> ranks
    for item in scored:
        for name, order in orders(item["cands"]).items():
            r = order.index(item["id"]) + 1 if item["id"] in order else None
            ranks[name, item["field"], "all"].append(r)
            ranks[name, item["field"], item["type"]].append(r)
            ranks[name, "mean", "all"].append(r)
    names = list(orders(scored[0]["cands"]))
    for f in (*FIELDS, "mean"):
        print(f"\n## {f} ({args.split}, top {args.n} reranked)\n")
        print("| order | " + " | ".join(f"R@{k}" for k in KS) + " | MRR |")
        print("|---|" + "---|" * (len(KS) + 1))
        for name in names:
            rs = ranks[name, f, "all"]
            m = metrics(rs, len(rs))
            print(f"| {name} | " + " | ".join(f"{m[f'R@{k}']:.2f}" for k in KS) + f" | {m['MRR']:.3f} |")
    types = sorted({t for _, _, t in ranks if t != "all"})
    print(f"\n## by kind of record, mean over {', '.join(FIELDS)}: R@10 / R@20 / MRR\n")
    print("| order | " + " | ".join(types) + " |")
    print("|---|" + "---|" * len(types))
    for name in names:
        cells = []
        for t in types:
            rs = [r for f in FIELDS for r in ranks[name, f, t]]
            m = metrics(rs, len(rs))
            cells.append(f"{m['R@10']:.2f} / {m['R@20']:.2f} / {m['MRR']:.3f} (n={len(rs)})")
        print(f"| {name} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()

"""Rerank search candidates with a cross-encoder: a model that reads the question and a candidate's
text together and scores how well they match (BAAI/bge-reranker-v2-m3, Apache-2.0). It runs locally,
like the embedding models, so nothing is sent anywhere or billed.

A candidate is scored on the texts it was searched by (build_index.py): its title and question, and
each passage of its answer preceded by its title (a book section: its book and headings), and
takes its best score. That order is fused with the search order by reciprocal rank fusion (k = 10,
equal weights): measured on the dev questions (eval_rerank.py, docs/selection.md), the fusion puts
the record in the first 10 for 91% of questions against 87% for search alone, while the reranker's
own order is no better than search.

Run: .venv/Scripts/python -I -X utf8 scripts/rerank.py --index data/work/index "السؤال"
"""
import argparse
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from build_index import heading  # noqa: E402
from search import ROOT, Index, dense_text  # noqa: E402  (search sets HF_HOME to data/models)

RERANKER = dict(repo="BAAI/bge-reranker-v2-m3", revision="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
MAX_TOKENS = 1024
MAX_PASSAGES = 8          # passages scored per record: the one search matched first, then in order
FUSE_K = 10               # RRF constant of the fusion with the search order


def load_corpus(path):
    """The corpus records in index order (build_index.py writes the index in corpus order)."""
    return [json.loads(l) for l in open(path, encoding="utf-8")]


class Reranker:
    def __init__(self):
        import torch
        from sentence_transformers import CrossEncoder
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = CrossEncoder(RERANKER["repo"], revision=RERANKER["revision"], device=device, max_length=MAX_TOKENS)
        # Half precision on the GPU, float32 on the CPU (as for the embedding models).
        self.model.model.half() if device == "cuda" else self.model.model.float()
        self.tokenizer = self.model.tokenizer

    def scores(self, pairs, batch_size=16):
        """Relevance of each (question, text) pair, as logits (higher is better). Pairs are run in order
        of length, so a batch is padded little."""
        if not pairs:
            return np.zeros(0, np.float32)
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][1]))
        out = self.model.predict([pairs[i] for i in order], batch_size=batch_size, activation_fn=None,
                                 convert_to_numpy=True, show_progress_bar=False)
        s = np.empty(len(pairs), np.float32)
        s[order] = np.asarray(out, np.float32).ravel()
        return s


def unit_texts(index, corpus, rec, first=None):
    """What a record is scored on: («q», None, text) for its title and question, («p», passage, text)
    for each of its passages (up to MAX_PASSAGES, the one search matched first)."""
    r = corpus[rec]
    context = r["title"] if r["kind"] != "section" else heading(r)
    out = [("q", None, dense_text(heading(r)))]
    ps = index.record_passages(rec)
    if first is not None:
        ps = [first] + [p for p in ps if p is not first]
    for p in ps[:MAX_PASSAGES]:
        out.append(("p", p, dense_text(context) + "\n" + dense_text(r["answer"][p["start"]:p["end"]])))
    return out


def rerank(reranker, index, corpus, question, hits):
    """The hits (in search order) reordered: the reranker's order, by each record's best unit, fused
    with the search order. Each hit gets «rerank» (its best score), «rerank_units» ({kind: best score
    of that kind}) and «rerank_passage» (its passage that scored best)."""
    pairs, owner = [], []
    for h in hits:
        for kind, p, text in unit_texts(index, corpus, h["rec"], h.get("passage")):
            pairs.append((dense_text(question), text))
            owner.append((h, kind, p))
    s = reranker.scores(pairs)
    for h in hits:
        h["rerank_units"], h["rerank_passage"] = {}, None
    for (h, kind, p), x in zip(owner, s):
        if x > h["rerank_units"].get(kind, -np.inf):
            h["rerank_units"][kind] = float(x)
            if kind == "p":
                h["rerank_passage"] = p
    for h in hits:
        h["rerank"] = max(h["rerank_units"].values())
    by_score = sorted(range(len(hits)), key=lambda i: (-hits[i]["rerank"], i))
    fused = {i: 1 / (FUSE_K + i + 1) for i in range(len(hits))}
    for r, i in enumerate(by_score):
        fused[i] += 1 / (FUSE_K + r + 1)
    return [hits[i] for i in sorted(fused, key=lambda i: (-fused[i], i))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=pathlib.Path, default=ROOT / "data" / "work" / "index")
    ap.add_argument("--records", type=pathlib.Path, default=ROOT / "data" / "work" / "records")
    ap.add_argument("-n", type=int, default=50, help="search candidates to rerank")
    ap.add_argument("-k", type=int, default=10, help="results to show")
    ap.add_argument("query")
    args = ap.parse_args()
    index = Index(args.index)
    if index.stale():
        print("warning: the corpus changed after this index was built; run build_index.py", file=sys.stderr)
    corpus = load_corpus(args.records / "corpus.jsonl")
    hits = index.search(args.query, args.n)
    for n, h in enumerate(rerank(Reranker(), index, corpus, args.query, hits)[:args.k], 1):
        units = " ".join(f"{k}={v:.2f}" for k, v in h["rerank_units"].items())
        print(f"{n:2}. {h['id']:12} {h['rerank']:6.2f}  {h['title'][:70]}  [search {hits.index(h) + 1}; {units}]")


if __name__ == "__main__":
    main()

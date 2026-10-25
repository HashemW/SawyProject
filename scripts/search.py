"""Find the records that may answer a question: keyword search (BM25 over normalized, stemmed Arabic
words) and multilingual embeddings, over a record's title and question and over its answer in
passages, fused by rank (reciprocal rank fusion). build_index.py builds the index this reads; the
evaluation and the answer service use it.

Search only ranks the Sheikh's records. Whether one of them answers the question is decided after
it (step 4), and an answer is always a record's own text.

Run: .venv/Scripts/python -I -X utf8 scripts/search.py --index data/work/index "السؤال"
"""
import argparse
import collections
import functools
import hashlib
import json
import os
import pathlib
import re
import sys
import unicodedata

import numpy as np
import scipy.sparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from dedupe import DIACRITICS, FOLD as LETTERS, search_text  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Models live in the project's data folder (gitignored, on the data drive), not in the user cache.
os.environ.setdefault("HF_HOME", str(ROOT / "data" / "models"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# Arabic-Indic and Persian digits as ASCII; Persian kaf and yeh as Arabic (questions typed on other keyboards).
KEYBOARD = str.maketrans({**{chr(0x660 + i): str(i) for i in range(10)}, **{chr(0x6F0 + i): str(i) for i in range(10)},
                          "ک": "ك", "ی": "ي"})
WORD = re.compile(r"[ء-ي]+|[a-z]+|[0-9]+")
ARABIC = re.compile(r"[ء-ي]")


def tokens(s):
    """Words of the normalized search copy (dedupe.search_text), digits as ASCII, Latin in lower case."""
    return WORD.findall(search_text(s.translate(KEYBOARD)).lower())


ARTICLES = ("وال", "بال", "كال", "فال", "لل", "ال")
SUFFIXES = ("ها", "ان", "ات", "ون", "ين", "يه", "ه", "ي")


@functools.lru_cache(maxsize=None)
def light10(w, bare_waw=True):
    """Light10 (Larkey, Ballesteros and Connell 2007) on normalized words (ة written ه, ى written ي):
    «و» off if 3 letters remain, then one article if 2 remain, then each suffix in turn if 2 remain.
    Without bare_waw a «و» stays unless an article follows it: in وضوء, وصية, ورثة it is the word's own."""
    if bare_waw and len(w) >= 4 and w[0] == "و":
        w = w[1:]
    for p in ARTICLES:
        if w.startswith(p) and len(w) - len(p) >= 2:
            w = w[len(p):]
            break
    for s in SUFFIXES:
        if w.endswith(s) and len(w) - len(s) >= 2:
            w = w[:-len(s)]
    return w


@functools.lru_cache(maxsize=None)
def _snowball():
    import Stemmer
    return Stemmer.Stemmer("arabic")


STEMMERS = ("none", "light10", "light10-keepwaw", "snowball")


def terms(s, stem):
    """The terms keyword search matches on: words as they are, or stemmed (light10, Snowball). Snowball's
    Arabic stemmer expects ة, ى and hamzas as written, so it gets the words before letters are unified."""
    if stem == "snowball":
        raw = WORD.findall(dense_text(s.translate(KEYBOARD)).lower())
        return [t.translate(LETTERS) for t in _snowball().stemWords(raw)]
    w = tokens(s)
    if stem == "light10":
        return [light10(t) for t in w]
    if stem == "light10-keepwaw":
        return [light10(t, False) for t in w]
    return w


def dense_text(s):
    """Text for the embedding models: no diacritics, tatweel, invisible marks or footnote numbers;
    letters as written (the models know standard spelling)."""
    s = "".join(c for c in unicodedata.normalize("NFC", s) if unicodedata.category(c) != "Cf")
    s = DIACRITICS.sub("", s).replace("ٱ", "ا")
    return " ".join(re.sub(r"\(\d+\)", " ", s).split())


class BM25:
    """Okapi BM25 (Lucene's idf), kept as a sparse unit-by-term matrix of term weights, so a query
    scores every unit with one column sum."""

    def __init__(self, vocab, weights):
        self.vocab, self.weights = vocab, weights

    @classmethod
    def build(cls, docs, k1=1.2, b=0.75):
        vocab, rows, cols, tfs = {}, [], [], []
        for i, d in enumerate(docs):
            for t, n in collections.Counter(d).items():
                rows.append(i)
                cols.append(vocab.setdefault(t, len(vocab)))
                tfs.append(n)
        rows, cols, tf = np.array(rows), np.array(cols), np.array(tfs, np.float32)
        dl = np.array([len(d) for d in docs], np.float32)
        df = np.bincount(cols, minlength=len(vocab))
        idf = np.log1p((len(docs) - df + 0.5) / (df + 0.5)).astype(np.float32)
        w = idf[cols] * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl[rows] / max(dl.mean(), 1)))
        return cls(vocab, scipy.sparse.csc_matrix((w, (rows, cols)), shape=(len(docs), len(vocab)), dtype=np.float32))

    def scores(self, query_terms):
        cols = sorted({self.vocab[t] for t in query_terms if t in self.vocab})
        if not cols:
            return np.zeros(self.weights.shape[0], np.float32)
        return np.asarray(self.weights[:, cols].sum(axis=1)).ravel()

    def save(self, path):
        scipy.sparse.save_npz(f"{path}.npz", self.weights)
        pathlib.Path(f"{path}.json").write_text(json.dumps(self.vocab, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path):
        return cls(json.loads(pathlib.Path(f"{path}.json").read_text(encoding="utf-8")), scipy.sparse.load_npz(f"{path}.npz").tocsc())


# Embedding models (licenses: MIT, MIT, Apache-2.0), at pinned revisions. A query gets the model's
# instruction; records are embedded as they are.
INSTRUCTION = "Given a question about an Islamic ruling, retrieve the fatwa or passage that answers it"
MODELS = {
    "bge-m3": dict(repo="BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181", query=""),
    "e5-large-instruct": dict(repo="intfloat/multilingual-e5-large-instruct", revision="274baa43b0e13e37fafa6428dbc7938e62e5c439",
                              query=f"Instruct: {INSTRUCTION}\nQuery: "),
    "qwen3-0.6b": dict(repo="Qwen/Qwen3-Embedding-0.6B", revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
                       query=f"Instruct: {INSTRUCTION}\nQuery:"),
}
MAX_TOKENS = 512


def load_model(name):
    import torch
    from sentence_transformers import SentenceTransformer
    m = MODELS[name]
    model = SentenceTransformer(m["repo"], revision=m["revision"], device="cuda" if torch.cuda.is_available() else "cpu")
    model.max_seq_length = MAX_TOKENS
    # Half precision on the GPU; float32 on the CPU, where half precision is slow (transformers
    # otherwise keeps the checkpoint's own dtype).
    return model.half() if model.device.type == "cuda" else model.float()


def embed(model, texts, batch_size=32, progress=False):
    return model.encode(texts, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=progress).astype(np.float32)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# What the search uses, with each list's weight in the fusion (chosen on the dev questions,
# docs/retrieval.md): both models over title and question at full weight and over passages at half,
# keyword search with Snowball over title and question at half; RRF constant 10, so that first
# places count more than in the usual 60.
DEFAULT = {"dense:q:bge-m3": 1.0, "dense:q:e5-large-instruct": 1.0,
           "dense:p:bge-m3": 0.5, "dense:p:e5-large-instruct": 0.5, "bm25:q:snowball": 0.5}
RRF_K = 10


class Index:
    """The index folder written by build_index.py. A component is «kind:field:variant»: kind bm25
    (variant: stemmer) or dense (variant: model); field q (title and question), p (passages of the
    answer) or doc (the whole record; keyword search only)."""

    def __init__(self, folder):
        self.folder = pathlib.Path(folder)
        self.meta = json.loads((self.folder / "index.json").read_text(encoding="utf-8"))
        recs = json.loads((self.folder / "records.json").read_text(encoding="utf-8"))
        self.ids, self.titles = [r["id"] for r in recs], [r["title"] for r in recs]
        self.n = len(self.ids)
        self.passages = [json.loads(l) for l in open(self.folder / "passages.jsonl", encoding="utf-8")]
        self.p_rec = np.array([p["rec"] for p in self.passages], np.int64)
        self._bm25, self._dense, self._models = {}, {}, {}

    def built(self, kind, **part):
        """Refuse a part of the folder that index.json does not list for its corpus (left from an older build)."""
        if not any(all(b.get(k) == v for k, v in part.items()) for b in self.meta.get(kind, [])):
            raise ValueError(f"{kind} {part} is not built for this corpus: run build_index.py")

    def stale(self):
        """True if the corpus changed after the index was built."""
        path = ROOT / self.meta["corpus"]
        return not path.exists() or sha256(path) != self.meta["corpus_sha256"]

    def bm25(self, field, stem):
        if (field, stem) not in self._bm25:
            self.built("bm25", field=field, stemmer=stem)
            self._bm25[field, stem] = BM25.load(self.folder / f"bm25_{field}_{stem}")
        return self._bm25[field, stem]

    def dense(self, field, model):
        if (field, model) not in self._dense:
            self.built("dense", model=model)
            self._dense[field, model] = np.load(self.folder / f"dense_{model}_{field}.npy").astype(np.float32)
        return self._dense[field, model]

    def model(self, name):
        if name not in self._models:
            self._models[name] = load_model(name)
        return self._models[name]

    def query_vector(self, query, model):
        return self.query_vectors([query], model)[0]

    def query_vectors(self, queries, model):
        """Embeddings of several questions at once (much faster than one by one)."""
        return embed(self.model(model), [MODELS[model]["query"] + dense_text(q) for q in queries])

    def ranking(self, component, query, vectors=None, depth=200):
        """Records best first by one component, with the passage that scored best for each (p field).
        Keyword search ranks only records that share a term with the question."""
        kind, field, variant = component.split(":")
        if kind == "bm25":
            s = self.bm25(field, variant).scores(terms(query, variant))
        else:
            v = vectors[variant] if vectors and variant in vectors else self.query_vector(query, variant)
            s = self.dense(field, variant) @ v
        if field == "p":
            best = np.full(self.n, -np.inf, np.float32)
            np.maximum.at(best, self.p_rec, s)
        else:
            best = s
        top = np.argpartition(-best, min(depth, self.n) - 1)[:depth]
        top = top[np.argsort(-best[top], kind="stable")]
        if kind == "bm25":
            top = top[best[top] > 0]
        out = [(int(i), float(best[i])) for i in top]
        if field == "p":
            unit = {}
            for j in np.flatnonzero(np.isin(self.p_rec, top)):
                r = int(self.p_rec[j])
                if r not in unit or s[j] > s[unit[r]]:
                    unit[r] = int(j)
            return out, unit
        return out, {}

    def rankings(self, query, components=DEFAULT, depth=200, vectors=None):
        """Each component's ranking. Keyword search is used only for a question with Arabic in it.
        vectors: the question's embeddings by model, if already computed."""
        arabic = bool(ARABIC.search(query))
        vectors = dict(vectors or {})
        for c in components:
            kind, _, variant = c.split(":")
            if kind == "dense" and variant not in vectors:
                vectors[variant] = self.query_vector(query, variant)
        return {c: self.ranking(c, query, vectors, depth) for c in components if arabic or not c.startswith("bm25")}

    @staticmethod
    def fuse(lists, weights=None, k=RRF_K):
        """Reciprocal rank fusion: a record scores w/(k + rank) in each list it is in, w the list's
        weight (default 1)."""
        fused = collections.defaultdict(float)
        for c, (ranked, _) in lists.items():
            w = weights.get(c, 1.0) if weights else 1.0
            for r, (i, _) in enumerate(ranked):
                fused[i] += w / (k + r + 1)
        return sorted(fused, key=lambda i: (-fused[i], i)), fused

    def search(self, query, k=20, weights=None):
        """The first k records for a question, each with its fused score, its rank in each list and
        the passage that matched best. weights: {component: weight}, by default DEFAULT."""
        weights = weights or DEFAULT
        lists = self.rankings(query, weights)
        order, fused = self.fuse(lists, weights)
        ranks = {c: {i: r + 1 for r, (i, _) in enumerate(ranked)} for c, (ranked, _) in lists.items()}
        hits = []
        for i in order[:k]:
            unit = next((u[i] for _, u in lists.values() if i in u), None)
            hits.append(dict(rec=i, id=self.ids[i], title=self.titles[i], score=round(fused[i], 5),
                             ranks={c: ranks[c].get(i) for c in lists},
                             passage=self.passages[unit] if unit is not None else None))
        return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=pathlib.Path, default=ROOT / "data" / "work" / "index")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--components", default=",".join(f"{c}={w}" for c, w in DEFAULT.items()),
                    help="comma-separated kind:field:variant, each optionally =weight")
    ap.add_argument("query")
    args = ap.parse_args()
    weights = {c.split("=")[0]: float(c.split("=")[1]) if "=" in c else 1.0 for c in args.components.split(",")}
    index = Index(args.index)
    if index.stale():
        print("warning: the corpus changed after this index was built; run build_index.py", file=sys.stderr)
    for n, h in enumerate(index.search(args.query, args.k, weights), 1):
        ranks = " ".join(f"{c.split(':', 1)[1]}={r}" for c, r in h["ranks"].items() if r)
        print(f"{n:2}. {h['id']:12} {h['score']:.4f}  {h['title'][:70]}  [{ranks}]")


if __name__ == "__main__":
    main()

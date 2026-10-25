"""Build the search index of the corpus: the answers cut into passages, keyword-search matrices per
field and stemmer, and embeddings per field and model.

Input:  --records  folder with corpus.jsonl (dedupe.py)
Output: --out      index folder: index.json (what was built, from which corpus), records.json,
                   passages.jsonl, bm25_<field>_<stemmer>.npz/.json, dense_<model>_<field>.npy

Run: .venv/Scripts/python -I -X utf8 scripts/build_index.py --records data/work/records --out data/work/index

Fields: «q» is a record's title and question (a book section: its book and headings), «p» its
answer cut into passages of up to 220 words, at paragraph ends, else sentence ends, and «doc» the
whole record (keyword search only). A passage is a span of the answer, so the one that matched can
be quoted as it stands. Paragraphs that are only the opening or closing formula are not in any
passage: every answer has them. Embedded passages start with the record's title.
"""
import argparse
import datetime
import json
import pathlib
import re
import statistics
import sys
import time

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from search import BM25, DEFAULT, MODELS, STEMMERS, dense_text, embed, load_model, sha256, terms, tokens  # noqa: E402

MAX_WORDS = 220
MIN_WORDS = 50
FORMULA = set(tokens("بسم الله الرحمن الرحيم الحمد لله والصلاة والسلام على رسول الله وعلى آله وصحبه ومن والاه أما بعد "
                     "وبعد والله تعالى أعلى وأعلم وهو سبحانه أجل"))
SENTENCE_END = re.compile(r"[.!؟?؛]+[»)\]]*(?:\s*\(\d+\))?(?=\s)")
WORD = re.compile(r"\S+")


def heading(r):
    """What a record is about by its own heading: a fatwa's title and question; a book section's book
    and headings (a heading repeated on two levels once)."""
    if r["kind"] != "section":
        return r["title"] + "\n" + r["question"]
    out = []
    for h in [r["collection"], *(r.get("path") or [r["title"]])]:
        if h and (not out or out[-1] != h):
            out.append(h)
    return " / ".join(out)


def atoms(answer):
    """The answer as (start, end, words) pieces that a passage is made of: paragraphs; a paragraph
    over the limit is cut at sentence ends, and a sentence over it every MAX_WORDS words."""
    out = []
    for m in re.finditer(r"[^\n]+", answer):
        s, e = m.start(), m.end()
        w = tokens(answer[s:e])
        if not w or (len(w) < 30 and set(w) <= FORMULA):
            continue
        n = len(answer[s:e].split())
        if n <= MAX_WORDS:
            out.append((s, e, n))
            continue
        cuts = [s] + [x.end() for x in SENTENCE_END.finditer(answer, s, e)] + [e]
        for a, z in zip(cuts, cuts[1:]):
            words = [(x.start(), x.end()) for x in WORD.finditer(answer, a, z)]
            for k in range(0, len(words), MAX_WORDS):
                chunk = words[k:k + MAX_WORDS]
                out.append((chunk[0][0], chunk[-1][1], len(chunk)))
    return out


def passages(answer):
    """Consecutive pieces packed up to MAX_WORDS; a short last passage joins the one before it."""
    out = []
    for s, e, n in atoms(answer):
        if out and out[-1][2] + n <= MAX_WORDS:
            out[-1] = (out[-1][0], e, out[-1][2] + n)
        else:
            out.append((s, e, n))
    if len(out) > 1 and out[-1][2] < MIN_WORDS and out[-2][2] + out[-1][2] <= MAX_WORDS + MIN_WORDS:
        out[-2:] = [(out[-2][0], out[-1][1], out[-2][2] + out[-1][2])]
    return out


def used(kind):
    """The variants (stemmers or models) the default search uses."""
    return ",".join(sorted({c.split(":")[2] for c in DEFAULT if c.split(":")[0] == kind}))


def part_key(b):
    return b.get("field"), b.get("stemmer"), b.get("model")


def write_if_changed(path, text):
    """Leave an identical file alone: a search may be reading it."""
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def free_gpu():
    import gc
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    # By default what search.DEFAULT uses; the comparison in docs/retrieval.md built every stemmer and model.
    ap.add_argument("--stemmers", default=used("bm25"), help=f"any of {','.join(STEMMERS)}")
    ap.add_argument("--models", default=used("dense"), help=f"any of {','.join(MODELS)}")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    corpus_path = args.records / "corpus.jsonl"
    digest = sha256(corpus_path)                    # of the corpus as read, before the long build
    corpus = [json.loads(l) for l in open(corpus_path, encoding="utf-8")]
    write_if_changed(args.out / "records.json", json.dumps(
        [dict(id=r["id"], kind=r["kind"], title=r["title"] if r["kind"] != "section" else heading(r)) for r in corpus],
        ensure_ascii=False))
    plist = []
    for i, r in enumerate(corpus):
        for n, (s, e, w) in enumerate(passages(r["answer"])):
            plist.append(dict(rec=i, n=n, start=s, end=e, words=w))
    write_if_changed(args.out / "passages.jsonl", "".join(json.dumps(p) + "\n" for p in plist))
    sizes = [p["words"] for p in plist]
    stats = dict(records=len(corpus), passages=len(plist), records_without_passage=len(corpus) - len({p["rec"] for p in plist}),
                 passage_words=dict(median=statistics.median(sizes), p90=statistics.quantiles(sizes, n=10)[-1], max=max(sizes)))
    print(json.dumps(stats), flush=True)
    # index.json lists what the folder holds for this corpus. It is updated as each part is done, so an
    # interrupted build keeps what it finished; parts built from another corpus are dropped from it.
    meta_path = args.out / "index.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    if meta.get("corpus_sha256") != digest:
        meta = {}
    meta.update(corpus=str(corpus_path), corpus_sha256=digest, max_words=MAX_WORDS, min_words=MIN_WORDS, **stats)

    def done(kind, entry):
        meta[kind] = [b for b in meta.get(kind, []) if part_key(b) != part_key(entry)] + [entry]
        meta["built"] = datetime.datetime.now().isoformat(timespec="seconds")
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    texts = dict(q=[heading(r) for r in corpus], p=[corpus[p["rec"]]["answer"][p["start"]:p["end"]] for p in plist],
                 doc=[heading(r) + "\n" + r["answer"] for r in corpus])
    for stem in filter(None, args.stemmers.split(",")):
        t0 = time.time()
        for field in ("q", "p", "doc"):
            bm = BM25.build([terms(t, stem) for t in texts[field]])
            bm.save(args.out / f"bm25_{field}_{stem}")
            done("bm25", dict(field=field, stemmer=stem, terms=len(bm.vocab)))
        print(f"bm25 {stem}: {time.time() - t0:.0f}s", flush=True)
    context = [r["title"] if r["kind"] != "section" else heading(r) for r in corpus]
    for name in filter(None, args.models.split(",")):
        t0 = time.time()
        model = load_model(name)
        for field, items in (("q", [dense_text(t) for t in texts["q"]]),
                             ("p", [dense_text(context[p["rec"]]) + "\n" + dense_text(t) for p, t in zip(plist, texts["p"])])):
            t1 = time.time()
            np.save(args.out / f"dense_{name}_{field}.npy", embed(model, items).astype(np.float16))
            print(f"dense {name} {field}: {len(items):,} texts in {time.time() - t1:.0f}s", flush=True)
        done("dense", dict(model=name, repo=MODELS[name]["repo"], revision=MODELS[name]["revision"],
                           dims=model.get_sentence_embedding_dimension(), seconds=round(time.time() - t0)))
        del model
        free_gpu()


if __name__ == "__main__":
    main()

"""Pick the records the retrieval test questions are written for, and write what a question writer
needs to see of each: the title, the asker's question and the gist of the answer.

Input:  --records  folder with corpus.jsonl (dedupe.py)
Output: --out      targets.jsonl (all picked records, with their dev/test split) and
                   batch_N.jsonl (the same records in batches, for the writers)

Run: python -I -X utf8 scripts/sample_targets.py --records data/work/records --out data/work/eval

The pick is random with a fixed seed: 125 encyclopedia fatawa, 13 book sections and 12 question-
answer records from the books (oversampled: they are 5% of the corpus); 100 go to dev, 50 to test.
"""
import argparse
import json
import pathlib
import random
import re

SEED = 20261024
OPENING = re.compile(r"^\s*بسم الله الرحمن الرحيم\s*\n\s*الحمد لله[^\n]*\n")


def gist(text, head=120, tail=40):
    w = OPENING.sub("", text).split()
    return " ".join(w) if len(w) <= head + tail else " ".join(w[:head]) + " … " + " ".join(w[-tail:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--batches", type=int, default=3)
    args = ap.parse_args()
    corpus = [json.loads(l) for l in open(args.records / "corpus.jsonl", encoding="utf-8")]
    rng = random.Random(SEED)
    fatawa = [r for r in corpus if "edition" in r]
    sections = [r for r in corpus if r["kind"] == "section"]
    book_qa = [r for r in corpus if "edition" not in r and r["kind"] != "section"]
    picked = rng.sample(fatawa, 125) + rng.sample(sections, 13) + rng.sample(book_qa, 12)
    rng.shuffle(picked)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, r in enumerate(picked):
        rows.append(dict(id=r["id"], split="dev" if k < 100 else "test",
                         type="fatwa" if "edition" in r else ("book section" if r["kind"] == "section" else "book question"),
                         collection=r["collection"], chapter=r["chapter"], title=r["title"],
                         question=" ".join(r["question"].split()[:250]), answer_gist=gist(r["answer"])))
    with open(args.out / "targets.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(id=row["id"], split=row["split"], type=row["type"], title=row["title"]), ensure_ascii=False) + "\n")
    # The writers see the records in a different order from the split, so they cannot tell dev from test.
    order = sorted(rows, key=lambda row: row["id"])
    for b in range(args.batches):
        with open(args.out / f"batch_{b + 1}.jsonl", "w", encoding="utf-8") as f:
            for row in order[b::args.batches]:
                f.write(json.dumps({k: v for k, v in row.items() if k != "split"}, ensure_ascii=False) + "\n")
    print(f"{len(rows)} targets: " + ", ".join(f"{t} {sum(r['type'] == t for r in rows)}" for t in ("fatwa", "book section", "book question")))


if __name__ == "__main__":
    main()

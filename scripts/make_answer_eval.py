"""The test questions of step 4 (choosing the answer) beyond eval/retrieval.jsonl: questions the
assistant must not answer with a fatwa, written by writers who never see the search or the checker.

  sample: pick the records the near-miss questions are written from, and write the writers' batches
  merge:  check the writers' files and join them into eval/answer.jsonl, each question with its split

Kinds of question (field «kind») and what the assistant must do:
  near_miss    a record's issue with one decisive fact changed, so that this fatwa does not settle it
               (written from a record, «from»): no fatwa, unless another record settles the new case
  unanswered   a religious question the corpus is unlikely to answer: no fatwa
  personal     the asker's own case (a particular divorce, an estate's shares, a dispute): refer to a
               person, unless a fatwa matches every fact
  offtopic     not a religious question (general knowledge, a task, a joke): no fatwa
  chat         a greeting, thanks, a question about the assistant: the fixed reply
  injection    an attempt to make the assistant say or choose something else: never a fatwa that does
               not answer the religious question in it (if any)

Run: python -I -X utf8 scripts/make_answer_eval.py sample --records data/work/records --out data/work/eval_answer
     python -I -X utf8 scripts/make_answer_eval.py merge --eval data/work/eval_answer --out eval/answer.jsonl
"""
import argparse
import json
import pathlib
import random
import re

SEED = 20261025
KINDS = ("near_miss", "unanswered", "personal", "offtopic", "chat", "injection")
EXPECT = {"near_miss": "none", "unanswered": "none", "personal": "refer", "offtopic": "none", "chat": "chat", "injection": "none"}
OPENING = re.compile(r"^\s*بسم الله الرحمن الرحيم\s*\n\s*الحمد لله[^\n]*\n")


def sample(args):
    corpus = [json.loads(l) for l in open(args.records / "corpus.jsonl", encoding="utf-8")]
    taken = {json.loads(l)["id"] for l in open(args.retrieval, encoding="utf-8")}
    rng = random.Random(SEED)
    # Fatawa from the encyclopedia only, short enough to read whole, not already a test target.
    pool = [r for r in corpus if "edition" in r and r["id"] not in taken and 40 <= len(r["answer"].split()) <= 450]
    picked = rng.sample(pool, args.n)
    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "near_miss_targets.jsonl", "w", encoding="utf-8") as f:
        for k, r in enumerate(picked):
            f.write(json.dumps(dict(id=r["id"], split="dev" if k % 3 else "test", title=r["title"]), ensure_ascii=False) + "\n")
    order = sorted(picked, key=lambda r: r["id"])
    for b in range(args.batches):
        with open(args.out / f"near_miss_batch_{b + 1}.jsonl", "w", encoding="utf-8") as f:
            for r in order[b::args.batches]:
                f.write(json.dumps(dict(id=r["id"], chapter=r["chapter"], title=r["title"],
                                        question=" ".join(r["question"].split()[:250]),
                                        answer=OPENING.sub("", r["answer"])), ensure_ascii=False) + "\n")
    print(f"{len(picked)} near-miss records in {args.batches} batches -> {args.out}")


def merge(args):
    targets = {t["id"]: t for t in map(json.loads, open(args.eval / "near_miss_targets.jsonl", encoding="utf-8"))}
    rows, seen = [], set()
    for path in sorted(args.eval.glob("written_*.jsonl")):
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            if not line.strip():
                continue
            q = json.loads(line)
            where = f"{path.name}:{n}"
            assert q.get("kind") in KINDS, f"{where} kind {q.get('kind')}"
            assert isinstance(q.get("text"), str) and q["text"].strip(), f"{where} no text"
            assert q["text"] not in seen, f"{where} repeated"
            seen.add(q["text"])
            if q["kind"] == "near_miss":
                assert q.get("from") in targets, f"{where} from {q.get('from')}"
                assert q.get("changed"), f"{where} no «changed»"
                split = targets[q["from"]]["split"]
            else:
                split = None
            rows.append(dict(kind=q["kind"], text=q["text"], lang=q.get("lang", ""), expect=EXPECT[q["kind"]],
                             split=split, **{k: q[k] for k in ("from", "changed", "note") if q.get(k)}))
    missing = sorted(set(targets) - {r.get("from") for r in rows})
    assert not missing, f"no near-miss question for {missing}"
    # Kinds not written from a record: every third to test, in a fixed shuffled order.
    rng = random.Random(SEED)
    for kind in KINDS:
        if kind == "near_miss":
            continue
        group = [r for r in rows if r["kind"] == kind]
        rng.shuffle(group)
        for k, r in enumerate(group):
            r["split"] = "test" if k % 3 == 0 else "dev"
    with open(args.out, "w", encoding="utf-8") as f:
        for k, r in enumerate(rows, 1):
            f.write(json.dumps(dict(qid=f"A{k:03d}", **r), ensure_ascii=False) + "\n")
    counts = {kind: sum(r["kind"] == kind for r in rows) for kind in KINDS}
    print(f"{len(rows)} questions -> {args.out}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--records", type=pathlib.Path, required=True)
    s.add_argument("--retrieval", type=pathlib.Path, default=pathlib.Path("eval/retrieval.jsonl"))
    s.add_argument("--out", type=pathlib.Path, required=True)
    s.add_argument("-n", type=int, default=60)
    s.add_argument("--batches", type=int, default=2)
    m = sub.add_parser("merge")
    m.add_argument("--eval", type=pathlib.Path, required=True)
    m.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    sample(args) if args.cmd == "sample" else merge(args)


if __name__ == "__main__":
    main()

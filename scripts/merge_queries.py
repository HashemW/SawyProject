"""Join the test questions written for the sampled records (sample_targets.py) into one file with
each record's dev/test split, after checking that every record has all three questions.

Input:  --eval  folder with targets.jsonl and the writers' queries_N.jsonl
Output: --out   eval/retrieval.jsonl (in git: the questions are ours, not the Sheikh's text)

Run: python -I -X utf8 scripts/merge_queries.py --eval data/work/eval --out eval/retrieval.jsonl
"""
import argparse
import json
import pathlib

FIELDS = ("ar", "ar_dialect", "ar_short", "en")
DIALECTS = {"msa", "egyptian", "levantine", "gulf", "maghrebi"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args()
    targets = {t["id"]: t for t in map(json.loads, open(args.eval / "targets.jsonl", encoding="utf-8"))}
    written = {}
    for path in sorted(args.eval.glob("queries_*.jsonl")):
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            if not line.strip():
                continue
            q = json.loads(line)
            assert q["id"] in targets and q["id"] not in written, f"{path.name}:{n} {q['id']}"
            assert all(isinstance(q.get(f), str) and q[f].strip() for f in FIELDS), f"{path.name}:{n} missing field"
            assert q["ar_dialect"] in DIALECTS, f"{path.name}:{n} dialect {q['ar_dialect']}"
            written[q["id"]] = q
    missing = sorted(set(targets) - set(written))
    assert not missing, f"no questions for {missing}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for tid, t in targets.items():
            f.write(json.dumps(dict(id=tid, split=t["split"], type=t["type"], title=t["title"],
                                    **{k: written[tid][k] for k in FIELDS}), ensure_ascii=False) + "\n")
    print(f"{len(targets)} records, {3 * len(targets)} questions -> {args.out}")


if __name__ == "__main__":
    main()

"""Measure step 4 on the test questions: the candidates the checker sees (search, then rerank), its
verdict, and whether that verdict is right.

Questions: eval/retrieval.jsonl, where the record each question was written for should be chosen
(or another record that settles the question as well: judged and kept in eval/judgments.jsonl), and
eval/answer.jsonl, whose kinds must get no fatwa, the referral, or the chat reply
(make_answer_eval.py).

Steps; the checker runs as a Message Batch (half the price of single calls, results within the hour):
  prepare  search and rerank every question; write the candidates and the batch requests (free)
  variant  the same questions and candidates for another model or effort (free)
  tokens   count the input tokens of a sample of requests (free) and estimate the cost
  submit   send the batch (billed)
  collect  fetch the verdicts once the batch has ended
  report   score them; list the verdicts that need a judgment (another record chosen, or a fatwa
           chosen where none was expected)

Run: .venv/Scripts/python -I -X utf8 scripts/eval_answer.py prepare --split dev --out data/work/eval_answer/run_dev
"""
import argparse
import collections
import hashlib
import json
import pathlib
import random
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from answer import CHECK_K, EFFORT, MODEL, SCHEMA, SEARCH_N, SYSTEM, load_env, parse, request  # noqa: E402
from rerank import Reranker, load_corpus, rerank  # noqa: E402
from search import DEFAULT, ROOT, Index  # noqa: E402

FIELDS = ("ar", "ar_short", "en")
# $ per million tokens (input, output), standard API prices; batches cost half.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}


def questions(split):
    """Every test question of the split: {qid, kind, text, expect, target?}."""
    out = []
    for q in map(json.loads, open(ROOT / "eval" / "retrieval.jsonl", encoding="utf-8")):
        if split in ("all", q["split"]):
            for f in FIELDS:
                out.append(dict(qid=f"R-{q['id']}-{f}", kind=f"answerable:{q['type']}", field=f, text=q[f], expect="answer", target=q["id"]))
    path = ROOT / "eval" / "answer.jsonl"
    if path.exists():
        for q in map(json.loads, open(path, encoding="utf-8")):
            if split in ("all", q["split"]):
                out.append(dict(qid=q["qid"], kind=q["kind"], text=q["text"], expect=q["expect"], **({"from": q["from"]} if q.get("from") else {})))
    return out


def key(text, rid):
    """A judgment's key: the question's text and the record judged."""
    return hashlib.sha1((text.strip() + "\x00" + rid).encode("utf-8")).hexdigest()[:16]


def prepare(args):
    index = Index(args.index)
    if index.stale():
        sys.exit("the corpus changed after this index was built; run build_index.py")
    corpus = load_corpus(args.records / "corpus.jsonl")
    qs = questions(args.split)
    if args.limit:
        qs = random.Random(1).sample(qs, args.limit)
    models = sorted({c.split(":")[2] for c in DEFAULT if c.startswith("dense")})
    vectors = {m: index.query_vectors([q["text"] for q in qs], m) for m in models}
    index.unload_models()
    reranker = Reranker()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with open(args.out / "items.jsonl", "w", encoding="utf-8") as fi, open(args.out / "requests.jsonl", "w", encoding="utf-8") as fr:
        for n, q in enumerate(qs):
            hits = index.search(q["text"], SEARCH_N, vectors={m: vectors[m][n] for m in models})
            search_ids = [h["id"] for h in hits]
            hits = rerank(reranker, index, corpus, q["text"], hits)[:args.k]
            cands = [(corpus[h["rec"]], h["rerank_passage"] or h["passage"]) for h in hits]
            item = dict(q, cands=[h["id"] for h in hits],
                        passages=[[p["start"], p["end"]] if r["kind"] == "section" and p else None for r, p in cands],
                        target_search_rank=search_ids.index(q["target"]) + 1 if q.get("target") in search_ids else None)
            fi.write(json.dumps(item, ensure_ascii=False) + "\n")
            fr.write(json.dumps(dict(custom_id=q["qid"], params=request(q["text"], cands, args.model, args.effort)), ensure_ascii=False) + "\n")
            if (n + 1) % 50 == 0:
                print(f"{n + 1}/{len(qs)} questions, {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    (args.out / "run.json").write_text(json.dumps(dict(split=args.split, model=args.model, effort=args.effort, k=args.k,
                                                         search_n=SEARCH_N, questions=len(qs), prompt=prompt_id()), indent=1), encoding="utf-8")
    print(f"{len(qs)} questions -> {args.out}")


def variant(args):
    """A run with the questions and candidates of another (--source), with the current prompt and
    schema (answer.SYSTEM, answer.SCHEMA), for the given model and effort."""
    args.out.mkdir(parents=True, exist_ok=True)
    shutil.copy(args.source / "items.jsonl", args.out / "items.jsonl")
    with open(args.source / "requests.jsonl", encoding="utf-8") as fi, open(args.out / "requests.jsonl", "w", encoding="utf-8") as fo:
        for line in fi:
            r = json.loads(line)
            r["params"]["model"] = args.model
            r["params"]["system"][0]["text"] = SYSTEM
            r["params"]["output_config"] = {"effort": args.effort, "format": {"type": "json_schema", "schema": SCHEMA}}
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    run = json.loads((args.source / "run.json").read_text(encoding="utf-8"))
    run.update(model=args.model, effort=args.effort, source=args.source.name, prompt=prompt_id())
    (args.out / "run.json").write_text(json.dumps(run, indent=1), encoding="utf-8")
    print(f"{args.out}: the questions of {args.source.name}, {args.model} at effort {args.effort}, prompt {run['prompt']}")


def prompt_id():
    """A short hash of the checker's prompt and schema, to tell runs apart."""
    return hashlib.sha1((SYSTEM + json.dumps(SCHEMA, sort_keys=True)).encode("utf-8")).hexdigest()[:8]


def client():
    import anthropic
    load_env()
    return anthropic.Anthropic()


def tokens(args):
    """Input tokens of a sample of the requests (token counting is free), and the cost of the batch."""
    reqs = [json.loads(l) for l in open(args.out / "requests.jsonl", encoding="utf-8")]
    run = json.loads((args.out / "run.json").read_text(encoding="utf-8"))
    c = client()
    sample = random.Random(2).sample(reqs, min(args.sample, len(reqs)))
    counts = []
    for r in sample:
        p = r["params"]
        counts.append(c.messages.count_tokens(model=p["model"], system=p["system"], messages=p["messages"],
                                              output_config={"format": p["output_config"]["format"]}).input_tokens)
    mean = sum(counts) / len(counts)
    pin, pout = PRICES[run["model"]]
    est_out = args.output_tokens
    per = (mean * pin + est_out * pout) / 1e6
    print(f"input tokens per request: mean {mean:,.0f}, min {min(counts):,}, max {max(counts):,} (sample of {len(counts)})")
    print(f"assuming {est_out:,} output tokens (thinking included) per request: ${per:.4f} per single call, "
          f"${per / 2:.4f} in a batch; this batch of {len(reqs)}: ${per / 2 * len(reqs):.2f}")


def submit(args):
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    state = args.out / "batch.json"
    if state.exists():
        sys.exit(f"already submitted: {state.read_text(encoding='utf-8')}")
    reqs = [json.loads(l) for l in open(args.out / "requests.jsonl", encoding="utf-8")]
    batch = client().messages.batches.create(requests=[Request(custom_id=r["custom_id"], params=MessageCreateParamsNonStreaming(**r["params"])) for r in reqs])
    state.write_text(json.dumps(dict(id=batch.id, submitted=time.strftime("%Y-%m-%dT%H:%M:%S"), requests=len(reqs))), encoding="utf-8")
    print(f"batch {batch.id}: {len(reqs)} requests, {batch.processing_status}")


def collect(args):
    state = json.loads((args.out / "batch.json").read_text(encoding="utf-8"))
    c = client()
    while True:
        b = c.messages.batches.retrieve(state["id"])
        if b.processing_status == "ended" or not args.wait:
            break
        print(f"{b.processing_status}: {b.request_counts.processing} processing, {b.request_counts.succeeded} done", file=sys.stderr, flush=True)
        time.sleep(60)
    if b.processing_status != "ended":
        sys.exit(f"batch {state['id']} is {b.processing_status}: {b.request_counts}")
    items = {json.loads(l)["qid"]: json.loads(l) for l in open(args.out / "items.jsonl", encoding="utf-8")}
    n = 0
    with open(args.out / "results.jsonl", "w", encoding="utf-8") as f:
        for res in c.messages.batches.results(state["id"]):
            item = items[res.custom_id]
            if res.result.type == "succeeded":
                m = res.result.message
                v = parse(m, len(item["cands"]))
                u = m.usage
                v.update(model=m.model, input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                         cache_read=getattr(u, "cache_read_input_tokens", 0) or 0, cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0)
            else:
                v = dict(decision="error", error=res.result.type)
            f.write(json.dumps(dict(qid=res.custom_id, **v), ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} results -> {args.out / 'results.jsonl'}")


def report(args):
    items = {json.loads(l)["qid"]: json.loads(l) for l in open(args.out / "items.jsonl", encoding="utf-8")}
    results = {json.loads(l)["qid"]: json.loads(l) for l in open(args.out / "results.jsonl", encoding="utf-8")}
    run = json.loads((args.out / "run.json").read_text(encoding="utf-8"))
    jpath = ROOT / "eval" / "judgments.jsonl"
    judged = {}
    if jpath.exists():
        for j in map(json.loads, open(jpath, encoding="utf-8")):
            judged[j["key"]] = j["settles"]
    corpus = {}
    for r in load_corpus(args.records / "corpus.jsonl"):
        corpus[r["id"]] = r
    table = collections.defaultdict(collections.Counter)
    review = []
    cost = [0.0, 0, 0]
    pin, pout = PRICES[run["model"]]
    for qid, it in items.items():
        v = results.get(qid)
        if not v:
            table[it["kind"]]["missing"] += 1
            continue
        if "input_tokens" in v:
            cost[0] += ((v["input_tokens"] + v["cache_write"] * 1.25 + v["cache_read"] * 0.1) * pin + v["output_tokens"] * pout) / 2e6
            cost[1] += v["input_tokens"] + v["cache_read"] + v["cache_write"]
            cost[2] += v["output_tokens"]
        d = v["decision"]
        chosen = it["cands"][v["choice"] - 1] if d == "answer" else None
        group = it["kind"].split(":")[0]
        if it["expect"] == "answer":
            if d == "answer":
                if chosen == it["target"]:
                    outcome = "answer: its record"
                else:
                    s = judged.get(key(it["text"], chosen))
                    outcome = {True: "answer: another record that settles it", False: "answer: WRONG record"}.get(s, "answer: another record (to judge)")
                    if s is None:
                        review.append((it, chosen))
            else:
                outcome = d + (" (its record was a candidate)" if it["target"] in it["cands"] else " (its record not among the candidates)")
        else:
            if d == "answer":
                s = judged.get(key(it["text"], chosen))
                outcome = {True: "answer: a record that settles it", False: "answer: WRONG (no fatwa expected)"}.get(s, "answer (to judge)")
                if chosen == it.get("from"):
                    outcome += " [the record it was written not to fit]"
                if s is None:
                    review.append((it, chosen))
            else:
                outcome = d
        table[group][outcome] += 1
        if group == "answerable":
            table[it["kind"]][outcome] += 1
    print(f"# {args.out.name}: {run['model']}, effort {run['effort']}, {run['k']} candidates, split {run['split']}, prompt {run.get('prompt', '?')}\n")
    for kind in sorted(table):
        c = table[kind]
        total = sum(c.values())
        print(f"## {kind} ({total})")
        for outcome, n in c.most_common():
            print(f"- {outcome}: {n} ({n / total:.0%})")
        print()
    print(f"tokens: {cost[1]:,} in, {cost[2]:,} out; cost of this batch about ${cost[0]:.2f}")
    if review:
        with open(args.out / "to_judge.jsonl", "w", encoding="utf-8") as f:
            for it, rid in review:
                r = corpus[rid]
                f.write(json.dumps(dict(key=key(it["text"], rid), qid=it["qid"], kind=it["kind"], question=it["text"],
                                        record=rid, title=r["title"], asker_question=r["question"], answer=r["answer"],
                                        target=it.get("target")), ensure_ascii=False) + "\n")
        print(f"{len(review)} verdicts to judge -> {args.out / 'to_judge.jsonl'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("prepare", "variant", "tokens", "submit", "collect", "report"))
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--source", type=pathlib.Path, help="variant: the run whose questions and candidates are reused")
    ap.add_argument("--index", type=pathlib.Path, default=ROOT / "data" / "work" / "index")
    ap.add_argument("--records", type=pathlib.Path, default=ROOT / "data" / "work" / "records")
    ap.add_argument("--split", default="dev", choices=("dev", "test", "all"))
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--effort", default=EFFORT)
    ap.add_argument("-k", type=int, default=CHECK_K, help="candidates the checker sees")
    ap.add_argument("--limit", type=int, help="prepare: only a random sample of this many questions")
    ap.add_argument("--sample", type=int, default=20, help="tokens: requests counted")
    ap.add_argument("--output-tokens", type=int, default=1500, help="tokens: output tokens assumed per request")
    ap.add_argument("--wait", action="store_true", help="collect: wait until the batch has ended")
    args = ap.parse_args()
    dict(prepare=prepare, variant=variant, tokens=tokens, submit=submit, collect=collect, report=report)[args.cmd](args)


if __name__ == "__main__":
    main()

"""Group the copies of each fatwa across editions, keep one per the project's rule, and write the
corpus: one record per fatwa, with where its other copies are and a normalized copy for search.

Input:  --records  output folder of segment.py (records.jsonl)
Output: (same folder) corpus.jsonl   the kept fatawa (status ok), each with its other copies
                      groups.jsonl   every group of copies, all members and the choice made
                      dedupe.md, dedupe.json   counts and the lists to review

Run: python -I -X utf8 scripts/dedupe.py --records data/work/records

Same fatwa: the questions match (title and question share at least half their words, or 30%
when the answers are nearly identical) and the answers are related (5-word shingles: Jaccard
0.3 or one contained 50% in the other). Copies of one fatwa in two editions measure 0.9-1.0 on
the question and 0.5-1.0 on the answer (revised or extended answers); different fatawa that reuse
a paragraph or a quoted resolution share answer text but not the question (under 0.15). An
identical question (90% of words) with a rewritten answer is the same fatwa too, and is listed.
Links are made strongest first, and two groups that each hold a different record of the same
file are never joined (that would chain neighbouring fatawa); titles that differ only in a part
number («(1)», «(2)») are parts of a series, never copies. Kept separate, and listed: the same
answer given to different questions.

Which copy is kept (decisions 2026-10-24): the newest edition, 2022-23 chapter files over
2020-21 chapter files over the 2011-2017 volumes (later volume first). A copy in a 2022-23 file
marked «تحت الإجراء» gives way to a 2020-21 copy if there is one; otherwise it is kept. Within one
file the first copy is kept (the editors marked later ones «مكرر»). A held copy (flagged Quran
quote, quoted fatwa, article) is passed over for the next copy in that order; a group with no
usable copy stays out.
"""
import argparse
import collections
import json
import pathlib
import re
import unicodedata

DIACRITICS = re.compile("[" + "".join(map(chr, [*range(0x610, 0x61B), *range(0x64B, 0x660), 0x670, *range(0x6D6, 0x6EE), 0x640])) + "]")
FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
RANK = {"2022-23 chapter": 3, "2020-21 chapter": 2, "2011-2017 volume": 1}


def search_text(s):
    """The normalized copy used for search only: no diacritics, tatweel, invisible marks, brackets
    or footnote numbers; ا/أ/إ/آ/ٱ, ى/ي, ة/ه, ؤ/و, ئ/ي unified; single spaces."""
    s = "".join(c for c in unicodedata.normalize("NFC", s) if unicodedata.category(c) != "Cf")
    s = DIACRITICS.sub("", s).translate(FOLD)
    s = re.sub(r"\(\d+\)", " ", s)
    s = re.sub(r"[()\[\]{}«»﴿﴾\"']", " ", s)
    return " ".join(s.split())


def words(s):
    """Words for matching; «ﷺ» counts as the words it stands for (some copies use one, some the other)."""
    return re.findall(r"[ء-ي]+|[A-Za-z]+|\d+", search_text(s.replace("ﷺ", " صلى الله عليه وسلم ")))


def title_words(s):
    """Title words with part numbers kept: «(2)» in a title is not a footnote."""
    return re.findall(r"[ء-ي]+|[A-Za-z]+|\d+", DIACRITICS.sub("", s).translate(FOLD))


def series_parts(t1, t2):
    """Titles of two parts of one series: the same words, different numbers."""
    w1, w2 = title_words(t1), title_words(t2)
    n1, n2 = [w for w in w1 if w.isdigit()], [w for w in w2 if w.isdigit()]
    return n1 != n2 and [w for w in w1 if not w.isdigit()] == [w for w in w2 if not w.isdigit()]


def shingles(ws, k=5):
    return {" ".join(ws[i:i + k]) for i in range(max(1, len(ws) - k + 1))}


def in_progress(r):
    return "تحت الإجراء" in r["source"]


def order_key(r):
    """Sort key: the preferred copy first."""
    m = re.match(r"(\d\d)", r["source"])
    volume = int(m.group(1)) if m and r["edition"] == "2011-2017 volume" else 0
    pos = int(r["id"].rsplit("-", 1)[1])
    return (-RANK[r["edition"]], -volume, r["source"], pos)


def choose(members):
    """The kept copy of a group, by the rule above; None if no copy is usable."""
    ok = [r for r in members if r["status"] == "ok"]
    if not ok:
        return None, "no usable copy"
    ok.sort(key=order_key)
    first = ok[0]
    if in_progress(first):
        finished = [r for r in ok if r["edition"] == "2022-23 chapter" and not in_progress(r)]
        older = [r for r in ok if r["edition"] == "2020-21 chapter"]
        if finished:
            return finished[0], "newest finished copy"
        if older:
            return older[0], "2020-21 copy over an in-progress 2022-23 copy"
        return first, "in-progress copy kept: no 2020-21 copy"
    why = "newest copy"
    if any(r["status"] != "ok" and order_key(r) < order_key(first) for r in members):
        why = "newest usable copy (a newer copy is held)"
    return first, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True, type=pathlib.Path)
    args = ap.parse_args()
    recs = [json.loads(l) for l in open(args.records / "records.jsonl", encoding="utf-8")]
    fatawa = [r for r in recs if r["kind"] == "fatwa"]
    Q = [set(words(r["title"] + " " + r["question"])) for r in fatawa]
    A = [shingles(words(r["answer"])) for r in fatawa]
    df = collections.Counter(s for sh in A for s in sh)
    index = collections.defaultdict(list)
    for i, sh in enumerate(A):
        for s in sh:
            if df[s] <= 40:         # skip the formulas every answer shares
                index[s].append(i)

    # Candidate links: answers sharing rare shingles, and questions sharing most words.
    links, same_answer = [], []
    for i, sh in enumerate(A):
        cand = collections.Counter(j for s in sh if df[s] <= 40 for j in index[s] if j > i)
        for j, c in cand.items():
            if c < 3:
                continue
            inter = len(A[i] & A[j])
            aj = inter / len(A[i] | A[j])
            ac = inter / min(len(A[i]), len(A[j]))
            qj = len(Q[i] & Q[j]) / max(1, len(Q[i] | Q[j]))
            if (qj >= 0.5 and (aj >= 0.3 or ac >= 0.5)) or (qj >= 0.3 and aj >= 0.85):
                links.append((qj + aj, i, j, "copy", aj, ac))
            elif aj >= 0.85:
                same_answer.append((fatawa[i]["id"], fatawa[j]["id"], round(qj, 2), round(aj, 2)))
    qindex = collections.defaultdict(list)
    for i, q in enumerate(Q):
        for w in sorted(q, key=lambda w: (-len(w), w))[:2]:   # two longest words as a blocking key
            qindex[w].append(i)
    seen = set()
    for members in qindex.values():
        if len(members) > 300:
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                i, j = sorted((members[x], members[y]))
                if (i, j) in seen or len(Q[i]) < 6:
                    continue
                seen.add((i, j))
                qj = len(Q[i] & Q[j]) / max(1, len(Q[i] | Q[j]))
                if qj >= 0.9:
                    inter = len(A[i] & A[j])
                    aj = inter / max(1, len(A[i] | A[j]))
                    ac = inter / max(1, min(len(A[i]), len(A[j])))
                    links.append((qj + aj, i, j, "same question", aj, ac))

    # Join strongest first; never join two groups that each hold a different record of one file,
    # nor two parts of a series.
    parent = list(range(len(fatawa)))
    files = [{r["source"]} for r in fatawa]
    titles = [[r["title"]] for r in fatawa]

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    same_question, extended, refused, pairs = [], [], 0, 0
    for score, i, j, how, aj, ac in sorted(links, reverse=True):
        a, b = find(i), find(j)
        if a == b:
            continue
        same_file_dup = fatawa[i]["source"] == fatawa[j]["source"] and score >= 1.6
        if (files[a] & files[b] and not same_file_dup) or any(series_parts(x, y) for x in titles[a] for y in titles[b]):
            refused += 1
            continue
        parent[a] = b
        files[b] |= files[a]
        titles[b] += titles[a]
        pairs += 1
        if how == "same question" and aj < 0.3:
            # one answer contained in the other: extended in a later edition; otherwise reworded
            (extended if ac >= 0.6 else same_question).append((fatawa[i]["id"], fatawa[j]["id"], round(aj, 2)))

    groups = collections.defaultdict(list)
    for i, r in enumerate(fatawa):
        groups[find(i)].append(r)
    corpus, glines, why_count = [], [], collections.Counter()
    for gi, members in enumerate(sorted(groups.values(), key=lambda g: order_key(min(g, key=order_key)))):
        kept, why = choose(members)
        why_count[why] += 1
        gid = f"G{gi + 1:05d}"
        glines.append(dict(group=gid, kept=kept["id"] if kept else None, why=why,
                           members=[dict(id=r["id"], edition=r["edition"], source=r["source"], status=r["status"]) for r in sorted(members, key=order_key)]))
        if kept:
            rec = dict(kept)
            rec["group"] = gid
            rec["copies"] = [dict(id=r["id"], edition=r["edition"], source=r["source"]) for r in sorted(members, key=order_key) if r is not kept]
            rec["search"] = dict(title_question=search_text(kept["title"] + "\n" + kept["question"]), answer=search_text(kept["answer"]))
            corpus.append(rec)
    articles = [r for r in recs if r["kind"] == "article"]
    # The standalone books (segment_books.py): their usable records join the corpus as they are.
    # They are separate works, not editions of the fatawa; how much text they share with the kept
    # fatawa is measured and reported.
    books = []
    if (args.records / "books.jsonl").exists():
        books = [json.loads(l) for l in open(args.records / "books.jsonl", encoding="utf-8")]
    # A book record whose text is 90% contained in one record already kept (a fatwa, or an earlier
    # book record: one book reprints another) is a copy and stays out; one that shares half its text
    # with the kept fatawa as a whole is kept and listed.
    owner = collections.defaultdict(list)
    for k, r in enumerate(corpus):
        for s in shingles(words(r["answer"])):
            owner[s].append(k)
    book_overlap, book_copies = [], []
    for r in books:
        if r["status"] != "ok":
            continue
        sh = shingles(words(r["answer"]))
        hits = collections.Counter(k for s in sh for k in owner.get(s, ()) if len(owner[s]) <= 40)
        best, n = hits.most_common(1)[0] if hits else (None, 0)
        if sh and n / len(sh) >= 0.9:
            book_copies.append((r["id"], r["title"], corpus[best]["id"]))
            continue
        shared = sum(1 for s in sh if s in owner)
        if sh and shared / len(sh) >= 0.5:
            book_overlap.append((r["id"], r["title"], round(shared / len(sh), 2)))
        for s in sh:
            owner[s].append(len(corpus))
        rec = dict(r)
        rec["group"], rec["copies"] = None, []
        rec["search"] = dict(title_question=search_text(r["title"] + "\n" + r["question"]), answer=search_text(r["answer"]))
        corpus.append(rec)
    with open(args.records / "corpus.jsonl", "w", encoding="utf-8") as f:
        for r in corpus:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.records / "groups.jsonl", "w", encoding="utf-8") as f:
        for g in glines:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    fatawa_kept = [r for r in corpus if "edition" in r]
    by_ed = collections.Counter(r["edition"] for r in fatawa_kept)
    sizes = collections.Counter(min(len(g["members"]), 5) for g in glines)
    summary = dict(fatawa_records=len(fatawa), groups=len(glines), kept=len(fatawa_kept), pairs_linked=pairs, links_refused=refused,
                   kept_by_edition=dict(by_ed), choice=dict(why_count), group_sizes={("5+" if k == 5 else str(k)): v for k, v in sorted(sizes.items())},
                   same_answer_different_question=len(same_answer), same_question_extended_answer=len(extended),
                   same_question_reworded_answer=len(same_question),
                   articles_held=len(articles),
                   book_records_in_corpus=len(corpus) - len(fatawa_kept),
                   book_records_held=sum(1 for r in books if r["status"] != "ok"),
                   book_records_mostly_in_fatawa=len(book_overlap),
                   book_records_copies_left_out=len(book_copies),
                   corpus_total=len(corpus))
    (args.records / "dedupe.json").write_text(json.dumps(dict(summary, same_answer=same_answer, same_question=same_question,
                                                              extended=extended), ensure_ascii=False, indent=1), encoding="utf-8")
    title = {r["id"]: r["title"] for r in recs}
    lines = ["# Dedupe report", "",
             f"- Fatawa records (all editions): {len(fatawa):,}; groups of copies: {len(glines):,}; kept: {len(glines) - why_count['no usable copy']:,}",
             f"- Book records added from the standalone books: {summary['book_records_in_corpus']:,} ({summary['book_records_held']} held); corpus total: {len(corpus):,}",
             "- Kept by edition: " + ", ".join(f"{k} {v:,}" for k, v in by_ed.most_common()),
             "- How the kept copy was chosen: " + ", ".join(f"{k} {v:,}" for k, v in why_count.most_common()),
             "- Copies per group: " + ", ".join(f"{k}: {v:,}" for k, v in summary["group_sizes"].items()),
             f"- Articles (titled texts without «الجواب»), held for review and not in the corpus: {len(articles)}",
             "", f"## Same answer, different question ({len(same_answer)}): kept as separate fatawa", ""]
    lines += [f"- {a} «{title[a][:60]}» ~ {b} «{title[b][:60]}» (question {q}, answer {x})" for a, b, q, x in same_answer]
    lines += ["", f"## Same question, answer reworded between copies ({len(same_question)}): treated as one fatwa, newest kept; check for a changed view", ""]
    lines += [f"- {a} ~ {b} «{title[a][:70]}» (answer overlap {x})" for a, b, x in same_question]
    lines += ["", f"## Same question, answer extended in a later copy ({len(extended)}): one fatwa, newest kept", ""]
    lines += [f"- {a} ~ {b} «{title[a][:70]}»" for a, b, x in extended]
    lines += ["", f"## Book records that are copies of a kept record ({len(book_copies)}): left out", ""]
    lines += [f"- {a} «{t[:70]}» = {b}" for a, t, b in book_copies]
    lines += ["", f"## Book records whose text is mostly in kept records too ({len(book_overlap)}): kept", ""]
    lines += [f"- {a} «{t[:70]}» ({x:.0%} of its 5-word sequences)" for a, t, x in book_overlap]
    (args.records / "dedupe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

"""Split the fatwa encyclopedia into records, one per fatwa: title, question, answer and the
footnotes they reference, text exactly as extract_text.py wrote it (empty paragraphs and editors'
notes left out of the text).

Input:  --extract  output folder of extract_text.py (reads json/<book>.json)
Output: --out      records.jsonl   every fatwa of every edition (dedupe.py picks one copy of each)
                   parts.jsonl     every stretch of a book that is not a fatwa, with what it is
                   report.md, report.json   counts, the coverage check, the records held for review

Run: python -I -X utf8 scripts/segment.py --extract data/work/extract --out data/work/records

How a fatwa is found (docs/segmentation.md has the measurements behind each rule). A fatwa runs:
title → the asker's question → «الجواب» on its own line → basmala and «الحمد لله والصلاة والسلام…»
→ answer → «والله تعالى أعلى وأعلم». Every «الجواب» line starts an answer; between two of them lie the
end of one answer and the head (title and question) of the next. In order:
  1. Each file gives its titles one form (a heading style, an outline level, list numbers such as
     «794.»), learnt from the paragraphs that follow the Sheikh's closing formula; the last title
     of that form before an anchor starts the next fatwa, and the answer before it ends at the last
     closing formula before the first title. A closing formula after the title is the asker's.
  2. Where titles are plain paragraphs, the split is after the last paragraph ending with his
     closing formula or its variants (askers' «والله أعلم» counts only as a last resort).
  3. Otherwise a numbered question («3- …») or a paragraph shaped like a title starts the next one;
     failing all of these, the second anchor is a follow-up question in the same fatwa.
Titled texts with no «الجواب» between two fatawa become article records. Chapter headings,
ornaments, front matter, tables of contents and editors' notes become parts. Records whose words
cannot be vouched for (a flagged Quran quote, an article, an answer not opening with his formula,
i.e. another scholar's fatwa he quotes) are held: status "held: …", never used without review.

Check: every non-empty block of every book ends up in exactly one record or one part.
"""
import argparse
import collections
import json
import pathlib
import re
import unicodedata

DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
ANCHOR = re.compile(r"(?:ال)?جواب\s*[:.]?")                       # «الجواب», «الجواب:»
TAIL = r"[\s.،:؛!)\]»\d()]*$"                                       # the formula ends the block
CLOSING = re.compile(r"(?:و?الله|وهو)\s+(?:سبحانه\s+و)?(?:تعالى\s+)?و?(?:أ?على|أجل)\s+وأ?علم" + TAIL)   # his, typos included
SENTENCE_END = re.compile(r"[.!؟?»)\]]\s*(?:\(\d+\))?\s*$")
WEAK_CLOSING = re.compile(r"والله\s+(?:تعالى\s+)?أعلم" + TAIL)       # also written by askers
NUMBER = re.compile(r"^\s*(\d+)\.\t\s*|^\s*(\d+)\.\s*$")           # «794.⇥»: a title's list number made text
NUMBERED_QUESTION = re.compile(r"^\d+\s*[-.)]\s*\S")                 # «3- هل يقع الطلاق …؟»
EDITORIAL = re.compile(r"\bمكرر+ة?\b|^إلى هنا$|^تكرار (?:الجواب|الفتوى|السؤال)")   # editors' notes: «هذه الفتوى مكررة مع سابقتها»
OPENING = re.compile(r"^(?:بسم الله الرحمن الرحيم|الحمد لله)")         # how his answers open
CHAPTERS = {"كتاب " + c for c in (
    "العقيدة", "السياسة الشرعية", "العلم", "الطهارة", "الصلاة", "الجنائز", "اللباس والزينة", "الزكاة",
    "الصيام", "المناسك", "البيوع", "الفرائض", "النكاح", "الطلاق", "العدد", "الرضاع", "الجنايات", "الحدود",
    "الحدود والجنايات", "الأطعمة", "الأيمان", "الأيمان والنذور", "القضاء", "القرآن الكريم", "الحديث الشريف")}
CHAPTERS |= {"فتاوى متنوعة", "كتاب"}
ENCYCLOPEDIA = "موسوعة فتاوى المغتربين"
# Flags that keep a record out of use until a person has looked at it: the Sheikh's words cannot be
# vouched for (another scholar's fatwa he quotes, a titled text of mixed authorship) or a Quran
# quote is in doubt (decision 2026-10-24: such fatawa are left out).
HOLD = {"flagged quote", "article", "answer does not open with his formula"}


def plain(s):
    """Text for matching only: no diacritics, tatweel or invisible marks (RLM …), single spaces."""
    s = "".join(c for c in unicodedata.normalize("NFC", s) if unicodedata.category(c) != "Cf")
    return " ".join(DIACRITICS.sub("", s).split())


def edition(name):
    """(id prefix, edition) from a source file name; (None, None) for books outside the encyclopedia."""
    m = re.match(r"(\d\d) book\.doc$", name)
    if m:
        return f"V{m.group(1)}", "2011-2017 volume"
    m = re.match(r"(\d\d)-(\d) ", name)
    if m:
        return f"C{m.group(1)}-{m.group(2)}", "2020-21 chapter"
    m = re.match(r"(\d\d) \((\d)\) ", name)
    if m:
        return f"N{m.group(1)}", "2022-23 chapter"
    m = re.match(r"(\d\d) ", name)
    if m and int(m.group(1)) <= 23:
        return f"C{m.group(1)}", "2020-21 chapter"
    return None, None


def chapter_name(name):
    """«كتاب العلم» from «03 (2) كتاب العلم.doc», «03 العلم.doc» … (the file names are not uniform)."""
    s = re.sub(r"(?:\.doc)?\.docx?$", "", name)
    s = re.sub(r"^\d\d(?:-\d)?\s*(?:\(\d\))?\s*", "", s)
    s = s.split("-")[1] if "موسوعة" in s else s
    s = " ".join(re.sub(r"تحت الإجراء|\s\d\s*$", " ", s).split())
    return s if s.startswith("كتاب") else "كتاب " + s


class Book:
    def __init__(self, path):
        d = json.loads(path.read_text(encoding="utf-8"))
        self.name = d["source"]
        self.blocks = d["blocks"]
        self.notes = {(n["kind"], n["n"]): n for n in d["notes"] if n["n"] is not None}
        self.plain = [plain(b["text"]) for b in self.blocks]
        self.anchors = [i for i in range(len(self.blocks)) if self.is_anchor(i)]
        self.forms, self.numbered_titles = self.title_forms()

    def empty(self, i):
        return not self.plain[i]

    def is_anchor(self, i):
        return self.blocks[i]["kind"] in ("p", "cell") and bool(ANCHOR.fullmatch(self.plain[i]))

    def closes(self, i):
        return bool(CLOSING.search(self.plain[i]))

    def number(self, i):
        m = NUMBER.match(self.blocks[i]["text"])
        return int(m.group(1) or m.group(2)) if m else None

    def chapter_heading(self, i):
        st = (self.blocks[i]["style"] or "").lower()
        return st == "heading 1" or "عنوان 1" in st or self.plain[i] in CHAPTERS

    def editorial(self, i):
        """An editors' note, short and about the file («مكرر مع ما سبق», «إلى هنا»), not the Sheikh's text."""
        p = self.plain[i]
        return bool(p) and len(p.split()) <= 16 and bool(EDITORIAL.search(p))

    def outside(self, i):
        """Not part of any fatwa: empty, an ornament («***»), a chapter heading, an editors' note, or
        table-of-contents material."""
        p = self.plain[i]
        return (not p or not re.search(r"\w", p) or self.chapter_heading(i) or self.editorial(i)
                or self.blocks[i]["kind"] == "toc" or p == "الفهرس")

    def title_form(self, i):
        return not self.outside(i) and (self.blocks[i]["style"], self.blocks[i]["outline"]) in self.forms

    def title_forms(self):
        """How this file shapes its titles, learnt from the first block after each of the Sheikh's
        closing formulas: the (style, outline level) pairs that a style or an outline level 1-2 makes
        deliberate and that cover a tenth of the cases, and whether titles carry list numbers."""
        seen, numbered = collections.Counter(), 0
        for a, nxt in zip(self.anchors, self.anchors[1:]):
            c = [j for j in range(a + 1, nxt) if self.closes(j)]
            h = c[-1] + 1 if c else nxt
            while h < nxt and self.outside(h):
                h += 1
            if h < nxt:
                seen[(self.blocks[h]["style"], self.blocks[h]["outline"])] += 1
                numbered += self.number(h) is not None
        total = sum(seen.values())
        forms = {f for f, n in seen.items() if n >= max(2, total / 10) and (f[0] is not None or f[1] in (1, 2))}
        self.styled = total > 0 and sum(seen[f] for f in forms) >= 0.9 * total     # titles reliably in their form
        return forms, total > 0 and numbered >= total / 2

    def titled(self, i, last_number):
        """A block shaped like this file's titles. A list number counts only where titles are numbered
        and only as the next number in sequence (lists inside answers restart at 1)."""
        if self.outside(i) or self.closes(i):      # a closing line set in a heading style is not a title
            return False
        if self.title_form(i):
            return True
        n = self.number(i)
        return self.numbered_titles and n is not None and (last_number is None or last_number < n <= last_number + 5)

    def number_only(self, i):
        return bool(NUMBER.match(self.blocks[i]["text"])) and not NUMBER.sub("", self.blocks[i]["text"]).strip()

    def back_over_number(self, t, lo):
        """Where the head of title t starts: a title can run over several paragraphs of the title's
        form («شرح قوله تعالى:», then the verse), and its list number can stand alone before it."""
        while True:
            j = t - 1
            while j > lo and (self.empty(j) or self.editorial(j)):
                j -= 1
            if j > lo and (self.title_form(j) or self.number_only(j)):
                t = j
                if self.number_only(j):
                    return t
            else:
                return t


def head_by_shape(book, a, nxt):
    """Where neither a title form nor a closing formula marks the split: the next title is a short
    paragraph (at most 20 words) ending without punctuation (or with «)» or «»», as 97% of the
    plain-paragraph titles do), right after a paragraph that ends a sentence, and followed by at
    least one question paragraph and nothing that opens an answer. Titles with an outline level
    are preferred, then the earliest candidate among the last six paragraphs."""
    blocks = [j for j in range(a + 1, nxt) if not book.outside(j)]
    found = []
    for k in range(max(1, len(blocks) - 6), len(blocks) - 1):
        t, p = blocks[k], book.plain[blocks[k]]
        if (len(p.split()) > 20 or re.search(r"[^\w)»]$", p) or "/" in p     # «/»: dates of quoted fatawa
                or p.startswith(("بسم الله", "الحمد لله"))):
            continue
        if not SENTENCE_END.search(book.plain[blocks[k - 1]]):
            continue
        if any(book.plain[j].startswith(("بسم الله الرحمن", "الحمد لله والصلاة")) for j in blocks[k + 1:]):
            continue
        found.append(t)
    with_outline = [t for t in found if book.blocks[t]["outline"] is not None]
    return (with_outline or found or [None])[0]


def title_runs(book, T, lo):
    """The starts of the titles among title blocks T: consecutive title paragraphs (with only empty
    paragraphs, editors' notes or a standalone list number between them) are one title, and a list
    number standing alone before a title belongs to it."""
    runs = []
    for t in T:
        if runs and all(book.title_form(j) or book.outside(j) or book.number_only(j) for j in range(runs[-1][1] + 1, t)):
            runs[-1][1] = t
        else:
            runs.append([t, t])
    return [book.back_over_number(s, lo) for s, _ in runs]


def fatwa_ranges(book):
    """[(head start, [anchors], answer end, how the head was found, how the answer ends, flags)].
    Anchors joined into one fatwa are follow-up questions (or a fatwa he quotes) inside one answer;
    a range without anchors is an article: a titled text with no question and no «الجواب»."""
    A = book.anchors
    if not A:
        return []
    n = len(book.blocks)
    T0 = [j for j in range(A[0]) if book.titled(j, None)]
    pre = [j for j in range(A[0]) if not book.outside(j)]
    if T0:
        head, head_how = book.back_over_number(T0[-1], -1), "title"
    elif 0 < len(pre) <= 6:     # the file opens with the first fatwa: its plain title and question
        head, head_how = pre[0], "start of file"
    else:
        s = head_by_shape(book, -1, A[0])
        head, head_how = (s, "title shape") if s is not None else (A[0], "none")
    last_number = book.number(head) if head < A[0] else None
    out, group, flags = [], [A[0]], []
    for k, a in enumerate(A):
        nxt = A[k + 1] if k + 1 < len(A) else None
        if nxt is None:
            C = [j for j in range(a + 1, n) if book.closes(j)]
            if C:
                end, end_how = C[-1], "closing"
            else:       # no closing formula: the answer stops at the table of contents, a chapter heading or an ornament
                end = next((j - 1 for j in range(a + 2, n) if not book.empty(j) and book.outside(j)), n - 1)
                end_how = "end of book"
            out.append((head, group, end, head_how, end_how, flags))
            break
        C = [j for j in range(a + 1, nxt) if book.closes(j)]
        T = [j for j in range(a + 1, nxt) if book.titled(j, last_number)]
        if T:
            # The last title before the anchor starts the next fatwa. A closing formula after it is
            # the asker's (titles inside answers are rare: 14 in the whole corpus). Titles between
            # the answer's end and that head start articles: titled texts with no «الجواب».
            runs = title_runs(book, T, a)
            first, nhead = runs[0], runs[-1]
            before = [c for c in C if c < first]
            end, end_how = (before[-1], "closing") if before else (first - 1, "title")
            nhow, nflags = "title", (["closing formula inside the question"] if any(c > nhead for c in C) else [])
            out.append((head, group, end, head_how, end_how, flags))
            for s, e in zip(runs, runs[1:]):
                out.append((s, [], e - 1, "title", "next title", ["article: titled text without «الجواب»"]))
            head, head_how, group, flags = nhead, nhow, [nxt], nflags
            num = book.number(head)
            last_number = num if num is not None else last_number
            continue
        if C:
            end, end_how = C[-1], "closing"
            nhead, nhow = C[-1] + 1, "closing"
        else:
            W = [j for j in range(a + 1, nxt) if WEAK_CLOSING.search(book.plain[j])]
            q = max((j for j in range(a + 1, nxt) if not book.outside(j)), default=None)
            s = head_by_shape(book, a, nxt)
            if W:
                end, end_how = W[-1], "weak closing"
                nhead, nhow = W[-1] + 1, "weak closing"
            elif q is not None and NUMBERED_QUESTION.match(book.plain[q]) and q > a + 1:
                end, end_how = q - 1, "numbered question"   # a list of short questions, each answered
                nhead, nhow = q, "numbered question"
            elif s is not None:
                end, end_how = s - 1, "title shape"
                nhead, nhow = s, "title shape"
            else:
                group.append(nxt)                   # a follow-up question in the same fatwa
                continue
        out.append((head, group, end, head_how, end_how, flags))
        head, head_how, group, flags = nhead, nhow, [nxt], []
        while head < nxt and book.outside(head):
            head += 1
        num = book.number(head) if head < nxt else None
        last_number = num if num is not None else last_number
    return out


def field(book, a, z, dropped=None):
    """Text and spans of blocks a..z (inclusive), one line per block, offsets into the joined text.
    Empty blocks are left out; editors' notes too, listed in `dropped` when given."""
    texts, spans, off = [], [], 0
    for i in range(a, z + 1):
        if book.empty(i):
            continue
        if dropped is not None and book.editorial(i):
            dropped.append(dict(block=i, text=book.blocks[i]["text"]))
            continue
        t = book.blocks[i]["text"]
        spans += [dict(s, start=s["start"] + off, end=s["end"] + off) for s in book.blocks[i]["spans"]]
        texts.append(t)
        off += len(t) + 1
    return "\n".join(texts), spans


def build(book, code, ed):
    """Records and parts of one book, every block assigned to exactly one of them."""
    recs, parts = [], []
    owner = [None] * len(book.blocks)
    chapter = chapter_name(book.name) if ed != "2011-2017 volume" else None

    def own(a, z, who):
        for i in range(a, z + 1):
            assert owner[i] is None, (book.name, i, owner[i], who)
            owner[i] = who

    def part(a, z, kind):
        while a <= z and book.empty(a):
            a += 1
        while z >= a and book.empty(z):
            z -= 1
        if a <= z:
            text, _ = field(book, a, z)
            parts.append(dict(source=book.name, kind=kind, blocks=[a, z], text=text))
            own(a, z, "part")

    prev_end = -1
    for head, anchors, end, head_how, end_how, range_flags in fatwa_ranges(book):
        # An article (no anchors) has a title and a body; a fatwa's head ends at its first anchor.
        stop = anchors[0] if anchors else end + 1
        # Between the previous answer and this head: chapter headings, editors' notes, front matter.
        while head < stop and book.outside(head):
            head += 1
        while end > (anchors[0] if anchors else head) and book.outside(end):
            end -= 1
        if ed == "2011-2017 volume":    # the volumes span all chapters: «كتاب العلم», or «كتاب» / «القرآن الكريم»
            heads1 = [i for i in range(prev_end + 1, head) if book.chapter_heading(i) and not book.empty(i)]
            for i in heads1:
                if book.plain[i].startswith(("كتاب", "فتاوى")):
                    nxt = next((j for j in heads1 if j > i), None) if book.plain[i] == "كتاب" else None
                    chapter = " ".join((book.blocks[i]["text"] + (" " + book.blocks[nxt]["text"] if nxt else "")).split())
        part(prev_end + 1, head - 1, "front" if prev_end < 0 else "between")
        flags, dropped = list(range_flags), []
        # Title: the head's first paragraph, or its run of title-form paragraphs; a list number
        # standing alone before it is the title's number.
        number, t0 = None, head
        if head < stop and book.number_only(head):
            number = book.number(head)
            t0 = next((j for j in range(head + 1, stop) if not book.outside(j)), stop)
        t1 = t0
        while t1 + 1 < stop and book.title_form(t0) and (book.title_form(t1 + 1) or book.outside(t1 + 1)):
            t1 += 1
        while t1 > t0 and book.outside(t1):
            t1 -= 1
        title, tspans = field(book, t0, t1, dropped) if t0 < stop else ("", [])
        m = NUMBER.match(title)
        if m:
            number, cut = int(m.group(1) or m.group(2)), m.end()
            title = title[cut:]
            tspans = [dict(s, start=s["start"] - cut, end=s["end"] - cut) for s in tspans if s["start"] >= cut]
        if anchors:
            q = (t1 + 1, anchors[0] - 1) if t1 + 1 <= anchors[0] - 1 else None
            question, qspans = field(book, *q, dropped) if q else ("", [])
            answer, aspans = field(book, anchors[0] + 1, end, dropped)
        else:       # an article: its text stands where an answer would
            question, qspans = "", []
            answer, aspans = field(book, t1 + 1, end, dropped)
        notes = []
        for s in tspans + qspans + aspans:
            if s["kind"] == "note" and s.get("n") is not None:
                nt = book.notes.get((s["note"], s["n"]))
                if nt is not None and all(nt is not x for x in notes):
                    notes.append(nt)
        bad = sorted({s["status"] for s in tspans + qspans + aspans + [x for nt in notes for x in nt["spans"]]
                      if s["kind"] == "quran" and s["status"] in ("unresolved", "ambiguous", "corrected")})
        if head_how not in ("closing", "title"):
            flags.append(f"head found by {head_how}")
        if end_how not in ("closing", "next title"):
            flags.append(f"answer ends by {end_how}")
        if dropped:
            flags.append("editors' note left out")
        if len(anchors) > 1:
            flags.append(f"{len(anchors)} answers (follow-up questions)")
        if anchors and not question.strip():
            flags.append("no question text")
        if bad:
            flags.append("flagged quote: " + ", ".join(bad))
        if anchors and not OPENING.match(plain(answer)) and head_how != "numbered question":
            flags.append("answer does not open with his formula")
        if anchors and book.styled and head_how in ("closing", "title") and t0 < stop and not (
                book.title_form(t0) or number is not None):
            flags.append("title not in the file's title form")
        held = sorted({f.split(":")[0] for f in flags} & HOLD)
        rid = f"{code}-{len(recs) + 1:04d}"
        recs.append(dict(id=rid, kind="fatwa" if anchors else "article", source=book.name, edition=ed,
                         collection=ENCYCLOPEDIA, chapter=chapter,
                         number=number, title=title.strip(), question=question, answer=answer,
                         notes=[dict(kind=x["kind"], n=x["n"], text=x["text"], spans=x["spans"]) for x in notes],
                         spans=dict(title=tspans, question=qspans, answer=aspans),
                         blocks=dict(head=head, anchors=anchors, end=end), editorial=dropped, flags=flags,
                         status="held: " + "; ".join(held) if held else "ok"))
        own(head, end, rid)
        prev_end = end
    part(prev_end + 1, len(book.blocks) - 1, "after" if recs else "front")
    loose = [i for i, o in enumerate(owner) if o is None and not book.empty(i)]
    assert not loose, (book.name, loose[:5])
    return recs, parts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--only", help="substring filter on book names")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    all_recs, all_parts, rows, coverage = [], [], [], collections.Counter()
    for path in sorted((args.extract / "json").glob("*.json")):
        if args.only and args.only not in path.name:
            continue
        book = Book(path)
        code, ed = edition(book.name)
        if not code:
            continue
        recs, parts = build(book, code, ed)
        all_recs += recs
        all_parts += parts
        in_recs = sum(r["blocks"]["end"] - r["blocks"]["head"] + 1 for r in recs)
        in_parts = sum(p["blocks"][1] - p["blocks"][0] + 1 for p in parts)
        coverage.update(blocks=len(book.blocks), in_records=in_recs, in_parts=in_parts,
                        empty_outside=len(book.blocks) - in_recs - in_parts)
        rows.append((book.name, ed, len(book.blocks), sum(r["kind"] == "fatwa" for r in recs),
                     sum(r["kind"] == "article" for r in recs), len(book.anchors),
                     sum(r["status"] != "ok" for r in recs), len(parts)))
        fl = collections.Counter(f.split(":")[0] for r in recs for f in r["flags"])
        print(f"{len(recs):5d} records {len(book.anchors):5d} anchors  {book.name}  {dict(fl) if fl else ''}", flush=True)
    with open(args.out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in all_recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.out / "parts.jsonl", "w", encoding="utf-8") as f:
        for p in all_parts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    write_report(all_recs, all_parts, rows, coverage, args.out)
    print(f"{len(all_recs)} records, {len(all_parts)} parts")


def write_report(recs, parts, rows, coverage, out):
    flags = collections.Counter(f.split(":")[0] for r in recs for f in r["flags"])
    held = collections.Counter(r["status"] for r in recs if r["status"] != "ok")
    kinds = collections.Counter((r["edition"], r["kind"]) for r in recs)
    summary = dict(records=len(recs), ok=sum(r["status"] == "ok" for r in recs), held=dict(held), flags=dict(flags),
                   by_edition={f"{e} {k}": n for (e, k), n in sorted(kinds.items())}, parts=dict(collections.Counter(p["kind"] for p in parts)),
                   coverage=dict(coverage), editorial_notes=sum(len(r["editorial"]) for r in recs))
    (out / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        "# Segmentation report", "",
        f"- Records: {len(recs):,} ({summary['ok']:,} ok, {len(recs) - summary['ok']:,} held for review)",
        *[f"  - {k}: {n:,}" for k, n in summary["by_edition"].items()],
        f"- Coverage: {coverage['blocks']:,} blocks; {coverage['in_records']:,} in records, {coverage['in_parts']:,} in parts, "
        f"{coverage['empty_outside']:,} empty blocks outside both (every non-empty block is in exactly one record or part)",
        f"- Parts: " + ", ".join(f"{k} {n:,}" for k, n in summary["parts"].items()),
        f"- Editors' notes left out of records: {summary['editorial_notes']}",
        "", "## Flags", "", "| flag | records |", "|---|---|",
        *[f"| {k} | {n:,} |" for k, n in flags.most_common()],
        "", "## Per file", "", "| file | edition | blocks | fatawa | articles | anchors | held | parts |", "|---|---|---|---|---|---|---|---|",
        *[f"| {r[0]} | {r[1]} | {r[2]:,} | {r[3]:,} | {r[4]} | {r[5]:,} | {r[6]} | {r[7]} |" for r in rows],
        "", "## Held for review", "",
    ]
    for r in recs:
        if r["status"] != "ok":
            lines.append(f"- {r['id']} ({r['source']}) {r['status'][6:]} — {r['title'][:90]}")
    lines += ["", "## Editors' notes left out", ""]
    for r in recs:
        for e in r["editorial"]:
            lines.append(f"- {r['id']} block {e['block']}: {e['text'].strip()}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

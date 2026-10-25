"""Split the standalone books into records: one per section (the passage under a heading) for his
own books and treatises, one per question and answer for the two interviews; the books the
project leaves out or holds (decisions 2026-10-24) are listed, not split.

Input:  --extract  output folder of extract_text.py (json/<book>.json, with paragraph formatting)
Output: --out      books.jsonl, books_parts.jsonl, books.md, books.json

Run: python -I -X utf8 scripts/segment_books.py --extract data/work/extract --out data/work/records

Headings. These books set their headings by direct formatting, not styles: centred, larger or
bold. Each book's body text has one size and alignment (the most common among paragraphs of 25
words or more); a heading is a short paragraph (at most 20 words) set apart from it: centred and
larger or bold, or larger and bold (two books have options for their own sub-heading form). Bold
lead-ins at body size («يقول ابن كثير رحمه الله :»), poetry lines and the basmala are not
headings. Heading levels follow size. A section runs from a heading to the next one, with the
path of headings above it; the title page and the table of contents (from «الفهرس») are parts,
and so are sections the file repeats word for word.

Others' text inside his books (forewords, debate transcripts, appended documents) is named in
the BOOKS table by the paragraph where each stretch begins and the one after it ends, and left
out as a part. Books of questions and interviews become question-answer records (numbered
questions, «*» with «الجواب:», or a dialogue's bold questions); in المسائل الأساسية an issue and
its «أفكار أولية حول الإجابة» are one record.

Check: every non-empty paragraph of a book that is split ends up in exactly one record or part.
"""
import argparse
import collections
import json
import pathlib
import re
import unicodedata

DIACRITICS = re.compile("[" + "".join(map(chr, [*range(0x610, 0x61B), *range(0x64B, 0x660), 0x670, *range(0x6D6, 0x6EE), 0x640])) + "]")

# Decisions 2026-10-24 (CLAUDE.md): what each standalone book is and how it is used.
#   his        his own book: split into sections (forewords by others left out)
#   partial    only the sections listed as his
#   interview  question-answer records; the interviewer's framing is left out
#   out        co-authored with Dr. Abdullah al-Muslih, or an excerpt of such a book: not used
#   held       no author line: held until the Sheikh's team confirms
#   duplicate  the same file as another book
BOOKS = {
    "fa`alm.doc": ("his", "فاعلم أنه لا إله إلا الله", {"exclude": [
        ("فتوى علماء جمعية الهداية", "شبهات وجوابها", "a fatwa of the scholars of the Hidaya association, reproduced")]}),
    "Sharia-Applying.doc": ("his", "قضية تطبيق الشريعة بين المبدأ ودعاوى الخصوم", {}),
    "أدب طلب العلم.docx": ("his", "أدب طلب العلم", {"align_headings": True}),
    "التعددية السياسية.doc": ("his", "التعددية السياسية في الدولة الإسلامية", {}),
    "المحاورة.doc": ("his", "المحاورة", {}),
    "المخرج من الفتنة خط جميل من دار التأصيل.doc": ("his", "المخرج من الفتنة", {}),
    "المسائل الأساسية بخط جميل من دار التأصيل.doc": ("his", "المسائل الأساسية", {"answer_heading": "أفكار أولية حول الإجابة"}),
    "تساؤلات أمريكية _ التعديل الثالث.doc": ("his", "تساؤلات أمريكية", {"questions": "numbered", "intro": True}),
    # Others' text inside his books, as (first paragraph, paragraph after it) by how they begin:
    # forewords by others, the transcript of a debate with other speakers, appended documents.
    "تهافت العلمانية.doc": ("his", "تهافت العلمانية", {"exclude": [
        ("تقديم", "هذه المناظرة", "foreword by Dr. Abd al-Ghaffar Aziz"),
        ("مناظرة", "خاتمة", "transcript of the 1992 debate: other speakers")]}),
    "جماعةالمسلمين.doc": ("his", "جماعة المسلمين: مفهومها وكيفية لزومها في واقعنا المعاصر", {}),
    "حجة الوداع.doc": ("his", "الحرمات والحقوق الإنسانية في خطبة الوداع", {}),
    "حكم الدين نهائي خط جميل.doc": ("his", "حكم الدين في من تطاول على النبيين والمرسلين", {"colon_headings": True}),
    "دعاة لا قضاة.doc": ("his", "قراءة في كتاب دعاة لا قضاة", {}),
    "مدى شرعية الانتماء.doc": ("his", "مدى شرعية الانتماء إلى الأحزاب والجماعات الإسلامية", {}),
    "موقف الإسلام نهائي خط جميل.doc": ("his", "موقف الإسلام من العلمانية", {"colon_headings": True}),
    "نظرية السيادة.doc": ("his", "نظرية السيادة وأثرها على شرعية الأنظمة الوضعية", {}),
    "نوازل فقهية على الساحة الأمريكية.doc": ("his", "نوازل فقهية على الساحة الأمريكية", {}),
    "وقفات هادئة مع فتوى إباحة القروض الربوية.doc": ("his", "وقفات هادئة مع فتوى إباحة القروض الربوية", {"exclude": [
        ("تقديم", "بسم الله الرحم الرحيم", "foreword by Dr. Ali al-Salous"),
        ("الملاحق", None, "appendices: others' fatawa and council resolutions")]}),
    # Of these two only his own text: his introduction to the abridgment of Ibn Taymiyya; his essays
    # in المواجهة, not Imara's preface, not the anthology of others' sayings, not the debaters'
    # profiles (their positions stated as headlines) and not the debate transcript.
    "الصارم.doc": ("partial", "تقريب الصارم المسلول", {"keep": ["مقدمة التقريب"]}),
    "المواجهة بين الإسلام والعالمانية خط جميل من دار التأصيل.doc": ("partial", "المواجهة بين الإسلام والعالمانية", {"keep": [
        "تمهيد", "وهكذا تنقض عرى الإسلام", "المناورة", "تحرير محل النزاع", "حديث الإفك", "قبس من الأدلة",
        "الجذور التاريخية لفكرة فصل الدولة عن الدين"]}),
    "تكلم الدعاة.doc": ("interview", "هكذا تكلم الدعاة", {"questions": "star"}),
    "نهائي تطرف.doc": ("interview", "حوار حول التطرف الديني", {"questions": "dialogue",
                       "review": "dialogue split by formatting: check question and answer"}),
    "ما لا يسع المسلم جهله.doc": ("out", "ما لا يسع المسلم جهله", {}),
    "مالا يسع التاجر جهله.doc": ("out", "ما لا يسع التاجر جهله", {}),
    "البيوع وأحكامها.doc": ("out", "البيوع وأحكامها", {}),
    "المضاربة وأحكامها.doc": ("out", "المضاربة وأحكامها", {}),
    "المعاملات الربوية والبدائل الشرعية 18-3-2007.doc": ("out", "المعاملات الربوية والبدائل الشرعية", {}),
    "أصول الإيمان.doc": ("held", "أصول الإيمان", {}),
    "نهائي الطحاوية.doc": ("held", "شرح العقيدة الطحاوية", {}),
    "وجيزالزكاة.doc": ("held", "الوجيز في أحكام الزكاة", {}),
    "من التطبيقات المعاصرة للزكاة.doc": ("held", "من التطبيقات المعاصرة للزكاة", {}),
    "قضايا معاصرة.doc": ("held", "قضايا معاصرة", {}),
    "قراءة في كتاب دعاة لا قضاة.doc": ("duplicate", "قراءة في كتاب دعاة لا قضاة", {"same_as": "دعاة لا قضاة.doc"}),
}


def plain(s):
    s = "".join(c for c in unicodedata.normalize("NFC", s) if unicodedata.category(c) != "Cf")
    return " ".join(DIACRITICS.sub("", s).split())


class Book:
    def __init__(self, path, opts=None):
        self.opts = opts or {}
        d = json.loads(path.read_text(encoding="utf-8"))
        self.name = d["source"]
        self.blocks = d["blocks"]
        self.notes = {(n["kind"], n["n"]): n for n in d["notes"] if n["n"] is not None}
        self.plain = [plain(b["text"]) for b in self.blocks]
        size, align = collections.Counter(), collections.Counter()
        for b, p in zip(self.blocks, self.plain):
            n = len(p.split())
            if b["kind"] == "p" and n >= 25 and b["fmt"]["size"]:
                size[b["fmt"]["size"]] += n
                align[b["fmt"]["align"]] += n
        self.body_size = size.most_common(1)[0][0] if size else 32
        self.body_align = align.most_common(1)[0][0] if align else None

    def empty(self, i):
        return not re.search(r"\w", self.plain[i])

    def heading(self, i):
        """A short paragraph set apart from the body text: centred and larger or bold, or larger and
        bold. Two books mark sub-headings otherwise (options): a short line not justified like the
        body (`align_headings`), or a short line ending with a colon that is not a conjunction-led
        lead-in such as «ومن هذه الأحاديث:» (`colon_headings`)."""
        b, p = self.blocks[i], self.plain[i]
        n = len(p.split())
        if b["kind"] not in ("p", "textbox") or not p or n > 20 or self.empty(i):
            return False
        if re.match(r"^بسم ا+ل?له الرحم", p) or p.startswith(("إن الحمد لله", "الحمد لله")) and n > 4:
            return False
        if self.opts.get("align_headings") and n <= 8 and b["fmt"]["align"] in (None, "right", "start") \
                and self.body_align not in (None, "right", "start") and not re.search(r"[.،:؛]$", p):
            return True
        if self.opts.get("colon_headings") and n <= 10 and p.endswith(":") and not p.startswith(("و", "ف")):
            return True
        f = b["fmt"]
        size = (f["size"] or self.body_size) - self.body_size
        bold = (f["bold"] or 0) >= 0.6
        centered = f["align"] == "center"
        stretched = "ــ" in b["text"]          # kashida-stretched lines: poetry at body size
        if centered and (size >= 4 or (bold and not stretched and n <= 12)):
            return True
        if size >= 8 and n <= 6 and not p.startswith("أما بعد"):     # a large word or two on its own line: «مقدمة»
            return True
        return bold and size >= 4 and n <= 12 and not p.endswith(":")

    def level(self, i):
        return -(self.blocks[i]["fmt"]["size"] or self.body_size)


def field(book, a, z):
    texts, spans, off = [], [], 0
    for i in range(a, z + 1):
        if book.empty(i):
            continue
        t = book.blocks[i]["text"]
        spans += [dict(s, start=s["start"] + off, end=s["end"] + off) for s in book.blocks[i]["spans"]]
        texts.append(t)
        off += len(t) + 1
    return "\n".join(texts), spans


def notes_of(book, spans):
    out = []
    for s in spans:
        if s["kind"] == "note" and s.get("n") is not None:
            nt = book.notes.get((s["note"], s["n"]))
            if nt is not None and all(nt is not x for x in out):
                out.append(nt)
    return [dict(kind=x["kind"], n=x["n"], text=x["text"], spans=x["spans"]) for x in out]


def flagged(spans):
    return sorted({s["status"] for s in spans if s["kind"] == "quran" and s["status"] in ("unresolved", "ambiguous", "corrected")})


TITLE_PAGE = re.compile(r"تأليف|إعداد|اعداد|الصاوي|المصلح|الطبعة|الحقوق|دار |نائب رئيس|الأستاذ الدكتور|دكتور")   # not «بقلم»: a foreword follows


def split_sections(book, code, title, opts):
    """Records (one per section) and parts of a book of his."""
    n = len(book.blocks)
    heads = [i for i in range(n) if book.heading(i)]
    # The title page: everything before the first body paragraph, except the run of headings right
    # above it («الباب الأول» / «مقدمة»), which stops at title-page lines (the author, «تأليف» …).
    first_body = next((i for i in range(n) if len(book.plain[i].split()) >= 25), n)
    title_lines = [i for i in range(first_body) if not book.empty(i) and len(book.plain[i].split()) <= 12
                   and (TITLE_PAGE.search(book.plain[i]) or plain(title).startswith(book.plain[i]))]
    start = next((i for i in range(title_lines[-1] + 1, n) if not book.empty(i)), n) if title_lines else 0
    # The table of contents: from a «فهرس» heading in the last fifth of the book.
    toc = next((h for h in heads if h > n * 0.8 and re.match(r"^(?:ال)?فهرس", book.plain[h])), n)
    # Stretches of others' text, from the paragraph that begins with the first marker to the one
    # before the paragraph that begins with the second; they also end any section running into them.
    excluded, pos = [], 0
    for a_mark, z_mark, why in opts.get("exclude", []):
        a = next(i for i in range(pos, n) if book.plain[i].startswith(a_mark))
        z = next((i for i in range(a + 1, n) if book.plain[i].startswith(z_mark)), n) - 1 if z_mark else min(toc, n) - 1
        excluded.append((a, z, why))
        pos = z + 1
    if excluded and excluded[0][0] < start:      # a foreword right after the title page («بقلم …» looks like a title-page line)
        start = excluded[0][0]
    heads = sorted({h for h in heads if start <= h < toc} | {a for a, _, _ in excluded} | {z + 1 for _, z, _ in excluded if z + 1 < toc})
    recs, parts = [], []
    for a, z, why in excluded:
        parts.append(dict(source=book.name, kind="not his text (left out)", blocks=[a, z], text=why + ": " + field(book, a, min(z, a + 3))[0]))
    if start > 0:
        parts.append(dict(source=book.name, kind="title page", blocks=[0, start - 1], text=field(book, 0, start - 1)[0]))
    if toc < n:
        parts.append(dict(source=book.name, kind="table of contents", blocks=[toc, n - 1], text=field(book, toc, n - 1)[0]))
    # Sections: a run of headings (only empty paragraphs between them), then the text up to the next run.
    runs, breaks = [], {a for a, _, _ in excluded} | {z + 1 for _, z, _ in excluded}
    for h in heads:
        if runs and h not in breaks and all(book.empty(j) for j in range(runs[-1][1] + 1, h)):
            runs[-1][1] = h
        else:
            runs.append([h, h])
    bounds = []
    if not runs or runs[0][0] > start:          # text before the first heading: a section without one
        bounds.append((start, start, (runs[0][0] if runs else toc) - 1))
    for k, (h0, h1) in enumerate(runs):
        bounds.append((h0, h1 + 1, (runs[k + 1][0] if k + 1 < len(runs) else toc) - 1))
    path = {}
    for h0, b0, z in bounds:
        if any(a <= h0 <= ez for a, ez, _ in excluded):
            continue                                 # already a part
        hs = [j for j in range(h0, b0) if j in heads]
        for j in hs:
            lv = book.level(j)
            path = {k: v for k, v in path.items() if k < lv}
            path[lv] = j
        head_text, hspans = field(book, h0, b0 - 1)
        body, bspans = field(book, b0, z) if b0 <= z else ("", [])
        if not body.strip() or (not head_text.strip() and len(body.split()) < 10):
            parts.append(dict(source=book.name, kind="heading without text" if not body.strip() else "short line before the first heading",
                              blocks=[h0, z], text=(head_text + "\n" + body).strip()))
            continue
        trail = [" ".join(book.blocks[path[k]]["text"].split()) for k in sorted(path)]
        flags = []
        if "keep" in opts and not any(k in plain(" / ".join(trail)) for k in opts["keep"]):
            parts.append(dict(source=book.name, kind="not his text (left out)", blocks=[h0, z], text=head_text))
            continue
        notes = notes_of(book, hspans + bspans)
        bad = flagged(hspans + bspans + [s for nt in notes for s in nt["spans"]])
        if bad:
            flags.append("flagged quote: " + ", ".join(bad))
        recs.append(dict(id=f"{code}-{len(recs) + 1:04d}", kind="section", source=book.name, collection=title,
                         chapter=" / ".join(trail[:-1]) or None, title=" ".join(head_text.split()), path=trail,
                         question="", answer=body, notes=notes,
                         spans=dict(title=hspans, question=[], answer=bspans), blocks=dict(head=h0, end=z),
                         flags=flags, status="held: flagged quote" if bad else "ok"))
    if opts.get("answer_heading"):
        recs = merge_issues(recs, opts["answer_heading"], code)
    # Sections the file repeats word for word (دعاة لا قضاة has whole chapters twice): the first stays.
    seen, kept = {}, []
    for r in recs:
        key = plain(r["answer"])
        if key in seen:
            parts.append(dict(source=book.name, kind="repeated in the file", blocks=[r["blocks"]["head"], r["blocks"]["end"]],
                              text=f"same text as {seen[key]}: {r['title']}"))
        else:
            seen[key] = r["id"]
            kept.append(r)
    for k, r in enumerate(kept):
        r["id"] = f"{code}-{k + 1:04d}"
    return kept, parts


def merge_issues(recs, answer_heading, code):
    """A book of issues (المسائل الأساسية): an issue's title and statement, then a section headed
    «أفكار أولية حول الإجابة» with his answer. The statement becomes the question and the
    answer sections (one or more) the answer of one record."""
    out = []
    for r in recs:
        if plain(r["title"]).startswith(answer_heading) and out and out[-1]["kind"] in ("section", "fatwa"):
            prev = out[-1]
            if prev["kind"] == "section":           # first answer section: the previous section is the issue
                prev.update(kind="fatwa", question=prev["answer"], answer="",
                            spans=dict(title=prev["spans"]["title"], question=prev["spans"]["answer"], answer=[]))
            off = len(prev["answer"]) + 1 if prev["answer"] else 0
            prev["answer"] = (prev["answer"] + "\n" if prev["answer"] else "") + r["answer"]
            prev["spans"]["answer"] += [dict(s, start=s["start"] + off, end=s["end"] + off) for s in r["spans"]["answer"]]
            prev["notes"] += [nt for nt in r["notes"] if nt not in prev["notes"]]
            prev["flags"] = sorted(set(prev["flags"]) | set(r["flags"]))
            prev["status"] = r["status"] if r["status"] != "ok" else prev["status"]
            prev["blocks"]["end"] = r["blocks"]["end"]
        else:
            out.append(r)
    for k, r in enumerate(out):
        r["id"] = f"{code}-{k + 1:04d}"
    return out


QUESTION_NUMBERED = re.compile(r"^\d+\s*[-–]\s*\S")
ANSWER_LABEL = re.compile(r"^\s*الجواب\s*:\s*")


def is_question(book, i, mode):
    """Question paragraphs, by book: numbered «47 - ما هو الجهاد؟» (تساؤلات أمريكية); «* …»
    (تكلم الدعاة); bold, or ending with «؟» right before a reply starting with «-» (نهائي تطرف)."""
    p, b = book.plain[i], book.blocks[i]
    if not p or book.empty(i) or re.search(r"\t\s*\d+\s*$", b["text"]):    # a contents line: «… ؟⇥22»
        return False
    if mode == "numbered":
        return bool(QUESTION_NUMBERED.match(p)) and ("؟" in p or "?" in p) and len(p.split()) <= 80
    if mode == "star":           # a «*» line is a question only if a reply follows it («الجواب:» or «-»);
        if not p.startswith("*"):   # otherwise it is one of his bullet points
            return False
        nxt = [j for j in range(i + 1, min(i + 4, len(book.blocks))) if not book.empty(j)]
        return any(ANSWER_LABEL.match(book.plain[j]) or book.plain[j].startswith("-") for j in nxt[:2])
    if mode == "dialogue":
        raw = b["text"]
        if len(p.split()) > 100 or "\t" in raw or raw.startswith("   ") or "ــ" in raw:
            return False                            # verse lines (indented, tabbed or kashida-stretched)
        if (b["fmt"]["bold"] or 0) >= 0.9:
            return True
        nxt = next((j for j in range(i + 1, len(book.blocks)) if not book.empty(j)), None)
        return not p.startswith("-") and p.rstrip(" .").endswith(("؟", "?")) and nxt is not None and book.plain[nxt].startswith("-")
    return False


def split_qa(book, code, title, opts):
    """Question-answer records of a book of questions or an interview. The asker's or interviewer's
    words are the question; his reply is the answer, up to the next question or section heading.
    Everything else (framing, introductions about him, tables of contents) becomes parts."""
    n = len(book.blocks)
    mode = opts["questions"]
    heads = {i for i in range(n) if book.heading(i)}
    toc = next((i for i in range(int(n * 0.75), n) if re.match(r"^(?:ال)?فهرس", book.plain[i])), n)
    qs = [i for i in range(toc) if is_question(book, i, mode)]
    if mode == "numbered" and qs:    # statements put as questions («8 - … غريب جدًّا بالنسبة لنا»), in the questions' style
        qstyle = collections.Counter(book.blocks[i]["style"] for i in qs).most_common(1)[0][0]
        qs = sorted(set(qs) | {i for i in range(toc) if book.blocks[i]["style"] == qstyle and qstyle
                               and QUESTION_NUMBERED.match(book.plain[i]) and len(book.plain[i].split()) <= 80
                               and not re.search(r"\t\s*\d+\s*$", book.blocks[i]["text"])})
    if mode == "star":      # the interview starts at its first «الجواب:»; «*» bullets before it are the magazine's own text
        first = next((i for i in range(n) if ANSWER_LABEL.match(book.plain[i])), n)
        qs = [q for q in qs if q >= max((x for x in qs if x < first), default=first)]
    recs, parts, covered = [], [], set()
    k = 0
    while k < len(qs):
        q0 = qs[k]
        q1 = q0                                     # a question may run over several paragraphs
        while k + 1 < len(qs) and all(book.empty(j) or j in qs for j in range(q1 + 1, qs[k + 1] + 1)):
            k += 1
            q1 = qs[k]
        a0 = q1 + 1
        if mode == "star":                          # the reply starts at «الجواب:» or «-»; a line between is the editor's subheading
            a0 = next((j for j in range(q1 + 1, n) if ANSWER_LABEL.match(book.plain[j]) or book.plain[j].startswith("-") or j in qs), n)
            if a0 == n or a0 in qs:
                k += 1
                continue
            end = next((j for j in range(a0, toc) if j in qs), toc) - 1     # his replies run across the editor's subheadings
            while end > a0 and (book.empty(end) or end in heads):
                end -= 1
        else:
            end = next((j for j in range(a0, toc) if j in qs or j in heads), toc) - 1
        qtext, qspans = field(book, q0, a0 - 1)
        atext, aspans = field(book, a0, end) if a0 <= end else ("", [])
        m = ANSWER_LABEL.match(atext)
        if m:                                       # the label is not his words
            cut = m.end()
            atext = atext[cut:]
            aspans = [dict(s, start=s["start"] - cut, end=s["end"] - cut) for s in aspans if s["start"] >= cut]
        k += 1
        if len(atext.split()) < 3:
            continue
        notes = notes_of(book, qspans + aspans)
        bad = flagged(qspans + aspans + [s for nt in notes for s in nt["spans"]])
        flags = ["flagged quote: " + ", ".join(bad)] if bad else []
        if opts.get("review"):
            flags.append(opts["review"])
        held = [f.split(":")[0] for f in flags if f.startswith("flagged quote")] + ([opts["review"]] if opts.get("review") else [])
        first = qtext.split("\n")[0]
        recs.append(dict(id=f"{code}-{len(recs) + 1:04d}", kind="fatwa", source=book.name, collection=title, chapter=None,
                         number=None, title=" ".join(first.split()), question=qtext, answer=atext,
                         notes=notes, spans=dict(title=[], question=qspans, answer=aspans),
                         blocks=dict(head=q0, end=end), flags=flags, status="held: " + "; ".join(held) if held else "ok"))
        covered.update(range(q0, end + 1))
    # Everything outside the records: framing, introductions, headings, tables of contents. In his
    # own books of questions the introduction before the first question is his, and is a section.
    i = 0
    while i < n:
        if i in covered or book.empty(i):
            i += 1
            continue
        j = i
        while j + 1 < n and j + 1 not in covered:
            j += 1
        text, spans = field(book, i, j)
        if opts.get("intro") and qs and j < qs[0] and len(text.split()) >= 50:
            body_from = next((x for x in range(i, j + 1) if len(book.plain[x].split()) >= 8), i)
            head, _ = field(book, i, body_from - 1) if body_from > i else ("", [])
            body, bspans = field(book, body_from, j)
            recs.insert(0, dict(id=f"{code}-0000", kind="section", source=book.name, collection=title, chapter=None,
                                title=" ".join(head.split()) or "مقدمة", path=[" ".join(head.split()) or "مقدمة"], question="",
                                answer=body, notes=notes_of(book, bspans), spans=dict(title=[], question=[], answer=bspans),
                                blocks=dict(head=i, end=j), flags=[], status="ok"))
        else:
            parts.append(dict(source=book.name, kind="not a question and answer", blocks=[i, j], text=text))
        i = j + 1
    return recs, parts


def check(book, recs, parts):
    owner = [None] * len(book.blocks)
    for who, (a, z) in [(r["id"], (r["blocks"]["head"], r["blocks"]["end"])) for r in recs] + [("part", tuple(p["blocks"])) for p in parts]:
        for i in range(a, z + 1):
            assert owner[i] is None, (book.name, i, owner[i], who)
            owner[i] = who
    loose = [i for i, o in enumerate(owner) if o is None and not book.empty(i)]
    assert not loose, (book.name, loose[:5])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--only")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    all_recs, all_parts, rows = [], [], []
    for k, path in enumerate(sorted((args.extract / "json").glob("*.json"))):
        name = path.name[:-len(".json")]
        if name not in BOOKS or (args.only and args.only not in name):
            continue
        use, title, opts = BOOKS[name]
        code = f"B{sorted(BOOKS).index(name) + 1:02d}"
        if use in ("his", "partial") or use == "interview":
            book = Book(path, opts)
            recs, parts = split_qa(book, code, title, opts) if "questions" in opts else split_sections(book, code, title, opts)
            check(book, recs, parts)
        else:
            recs, parts = [], []
        all_recs += recs
        all_parts += parts
        rows.append((name, use, title, len(recs), len(parts)))
        print(f"{use:9} {len(recs):4} records  {name}", flush=True)
    with open(args.out / "books.jsonl", "w", encoding="utf-8") as f:
        for r in all_recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(args.out / "books_parts.jsonl", "w", encoding="utf-8") as f:
        for p in all_parts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    write_report(all_recs, all_parts, rows, args.out)
    print(f"{len(all_recs)} records, {len(all_parts)} parts")


def write_report(recs, parts, rows, out):
    by_book = collections.defaultdict(list)
    for r in recs:
        by_book[r["source"]].append(r)
    summary = dict(records=len(recs), ok=sum(r["status"] == "ok" for r in recs),
                   kinds=dict(collections.Counter(r["kind"] for r in recs)),
                   held=dict(collections.Counter(r["status"] for r in recs if r["status"] != "ok")),
                   parts=dict(collections.Counter(p["kind"] for p in parts)),
                   books={name: dict(use=use, records=n, words=sum(len(r["answer"].split()) for r in by_book[name])) for name, use, _, n, _ in rows})
    (out / "books.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Standalone books", "",
             f"- Records: {len(recs):,} ({summary['ok']:,} ok): " + ", ".join(f"{k} {v:,}" for k, v in summary["kinds"].items()),
             "- Held: " + (", ".join(f"{k[6:]} {v}" for k, v in summary["held"].items()) or "none"),
             "- Parts: " + ", ".join(f"{k} {v}" for k, v in summary["parts"].items()),
             "", "| book | use | records | words |", "|---|---|---|---|"]
    lines += [f"| {name} | {use} | {n} | {summary['books'][name]['words']:,} |" for name, use, _, n, _ in rows]
    lines += ["", "## Left out of books that are used", ""]
    for p in parts:
        if p["kind"] in ("foreword by another author", "not his text (left out)", "not a question and answer"):
            lines.append(f"- {p['source']} blocks {p['blocks'][0]}–{p['blocks'][1]} ({p['kind']}): {p['text'][:100].replace(chr(10), ' / ')}")
    (out / "books.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

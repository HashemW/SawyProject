"""Acceptance test for extract_text.py: is every word of every source in the extraction, in order,
with nothing added?

The reference is Word's own plain text of each document (word_export.ps1 text/ and notes/),
read independently of extract_text.py's XML parser. Word cannot show glyph-font text (Quran
quotes, honorifics): it gives "(" or a private-use character for them, so the comparison takes
out what extract_text.py wrote in their place (the spans it records) and checks the rest:

  1. Main text: the sequence of words (Arabic, digits, Latin) in paragraphs, table cells and
     tables of contents must be identical, word for word, to Word's main text.
  2. Footnotes: same, note by note, against Word's footnote texts (Word's copy starts at the
     footnote mark, so anything before the mark is not compared). Text boxes: the same words as
     Word's text-frame story (in any order: Word lists the boxes in its own order).
  3. Glyphs: every glyph-font character the extraction read is in a recorded span, and each
     Quran quote was identified (statuses are counted; anything not exact is listed).

Run: python -I -X utf8 scripts/check_extract.py --word data/work/word --extract data/work/extract
Writes check.md and check.json next to the extraction.
"""
import argparse
import collections
import difflib
import json
import pathlib
import re
import unicodedata

TOKEN = re.compile(r"[\u0621-\u063a\u0640-\u0652\u0670-\u06d3\u06fa-\u06ff\u064b-\u065f]+|[0-9\u0660-\u0669\u06f0-\u06f9]+|[A-Za-z\u00c0-\u024f]+")
WORD_CHARS = dict.fromkeys(range(0x00, 0x20), " ")


def tokens(text):
    text = unicodedata.normalize("NFC", text)
    text = "".join(" " if 0xE000 <= ord(c) <= 0xF8FF else c for c in text).translate(WORD_CHARS)
    return TOKEN.findall(text)


def without_spans(text, spans):
    """The block's text as Word's plain text shows it: what extract_text.py wrote for glyphs is
    replaced by the source characters behind them (span "src"), note numbers are blanked out."""
    out, pos = [], 0
    for s in sorted(spans, key=lambda s: (s["start"], s["end"])):
        if s["start"] < pos:
            continue
        before = text[pos:s["start"]]
        if s.get("pad_before") and before.endswith(" "):   # a space extract_text.py added
            before = before[:-1]
        out.append(before)
        out.append(("" if s.get("pad_before") else " ") + s.get("src", "") + ("" if s.get("pad_after") else " "))
        pos = s["end"] + (1 if s.get("pad_after") and text[s["end"]:s["end"] + 1] == " " else 0)
    out.append(text[pos:])
    return "".join(out)


def compare(ours, word, label, samples):
    if ours == word:
        return 0, 0
    missing = extra = 0
    sm = difflib.SequenceMatcher(None, word, ours, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        missing += i2 - i1
        extra += j2 - j1
        if len(samples) < 40:
            samples.append({"where": label, "word": " ".join(word[max(0, i1 - 3): i2 + 3]), "ours": " ".join(ours[max(0, j1 - 3): j2 + 3])})
    return missing, extra


def check(doc, word_dir, name):
    out = {"file": name}
    samples = []
    # 1. main text
    ours = []
    for b in doc["blocks"]:
        if b["kind"] in ("p", "cell", "toc"):
            ours += tokens(without_spans(b["text"], b["spans"]))
    wt = (word_dir / "text" / (name + ".txt")).read_text(encoding="utf-8")
    word = tokens(wt)
    out["main_words"] = len(word)
    out["main_missing"], out["main_extra"] = compare(ours, word, "main", samples)
    # 2. footnotes
    wn = []
    notes_path = word_dir / "notes" / (name + ".txt")
    # One note per "\n"-terminated line; a note may itself hold other line separators (\v, \f).
    for line in (notes_path.read_text(encoding="utf-8").split("\n") if notes_path.exists() else []):
        if not line:
            continue
        n, _, t = line.partition("\t")
        wn.append(tokens(t.split("\x02", 1)[1] if "\x02" in t else t))
    on = []

    def note_tokens(text, spans, cut):
        return tokens(without_spans(text[cut:], [dict(s, start=s["start"] - cut, end=s["end"] - cut) for s in spans if s["start"] >= cut]))

    for x in doc["notes"]:
        if x["n"] is None:
            continue
        text, spans = x["text"], x["spans"]
        mark = next((s for s in spans if s["kind"] == "notemark"), None)
        if mark:   # Word's copy of a note starts after its mark
            on.append(note_tokens(text, spans, mark["end"]))
            continue
        # A note typed without a mark (its number written by hand): Word's copy drops its first
        # character, or, when the number is a separate «(1)», the whole number.
        k = len(on)
        first = note_tokens(text, spans, 1)
        number = note_tokens(text, spans, len(re.match(r"\s*\(\d+\)", text).group()) if re.match(r"\s*\(\d+\)", text) else 1)
        on.append(number if k < len(wn) and number == wn[k] else first)
    out["notes"] = len(on)
    out["notes_in_word"] = len(wn)
    out["notes_missing"] = out["notes_extra"] = 0
    for k in range(max(len(on), len(wn))):
        a, b = (on[k] if k < len(on) else []), (wn[k] if k < len(wn) else [])
        m, e = compare(a, b, f"note {k + 1}", samples)
        out["notes_missing"] += m
        out["notes_extra"] += e
    out["note_words"] = sum(len(x) for x in wn)
    # Text boxes, against Word's text-frame story (written only when a file has any).
    frames_path = word_dir / "frames" / (name + ".txt")
    ours_tb = [t for b in doc["blocks"] if b["kind"] == "textbox" for t in tokens(without_spans(b["text"], b["spans"]))]
    word_tb = tokens(frames_path.read_text(encoding="utf-8")) if frames_path.exists() else []
    out["textbox_words"] = len(word_tb)
    out["textbox_missing"], out["textbox_extra"] = compare(sorted(ours_tb), sorted(word_tb), "text boxes", samples) if ours_tb != word_tb else (0, 0)
    # 3. glyphs and quotes
    q = collections.Counter()
    review = []
    for where, items in (("text", doc["blocks"]), ("note", doc["notes"])):
        for i, b in enumerate(items):
            for s in b["spans"]:
                if s["kind"] == "quran":
                    q[s["status"]] += 1
                    if s["status"] not in ("exact", "phrase", "empty"):
                        review.append({"where": f"{where} {i}", "status": s["status"], "found": s.get("found"),
                                       "text": b["text"][max(0, s["start"] - 20): s["end"] + 30]})
    out["quotes"] = dict(q)
    out["glyphs_read"] = doc["counts"].get("glyphs_read", 0)
    out["glyphs_used"] = doc["counts"].get("glyphs_used", 0)
    out["review"] = review
    out["samples"] = samples
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word", required=True, type=pathlib.Path)
    ap.add_argument("--extract", required=True, type=pathlib.Path)
    args = ap.parse_args()
    rows = []
    for path in sorted((args.extract / "json").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        rows.append(check(doc, args.word, path.stem))
        r = rows[-1]
        print(f"{r['file']}: main -{r['main_missing']} +{r['main_extra']} notes -{r['notes_missing']} +{r['notes_extra']} quotes {r['quotes']}", flush=True)
    t = collections.Counter()
    q = collections.Counter()
    for r in rows:
        for k in ("main_words", "main_missing", "main_extra", "notes", "notes_in_word", "note_words", "notes_missing", "notes_extra",
                  "textbox_words", "textbox_missing", "textbox_extra", "glyphs_read", "glyphs_used"):
            t[k] += r[k]
        q.update(r["quotes"])
    bad = [r for r in rows if r["main_missing"] or r["main_extra"] or r["notes_missing"] or r["notes_extra"] or r["notes"] != r["notes_in_word"]
           or r["textbox_missing"] or r["textbox_extra"] or r["glyphs_read"] != r["glyphs_used"]]
    lines = [
        "# Extraction check", "",
        f"- Files: {len(rows)}; files with any difference: {len(bad)}",
        f"- Main text: {t['main_words']:,} words in Word's text; missing from the extraction: {t['main_missing']:,}; extra: {t['main_extra']:,}",
        f"- Footnotes: {t['notes']:,} extracted, {t['notes_in_word']:,} in Word; {t['note_words']:,} words; missing: {t['notes_missing']:,}; extra: {t['notes_extra']:,}",
        f"- Text boxes: {t['textbox_words']:,} words in Word's text-frame story; missing: {t['textbox_missing']:,}; extra: {t['textbox_extra']:,}",
        f"- Glyph characters read: {t['glyphs_read']:,}; accounted for: {t['glyphs_used']:,}",
        f"- Quran quotes: " + ", ".join(f"{k} {v:,}" for k, v in q.most_common()),
        "", "## Files with differences", "",
    ]
    for r in bad:
        lines.append(f"### {r['file']}")
        lines.append(f"main -{r['main_missing']} +{r['main_extra']}; notes {r['notes']} vs {r['notes_in_word']}, -{r['notes_missing']} +{r['notes_extra']}; glyphs {r['glyphs_read']} vs {r['glyphs_used']}")
        for s in r["samples"][:10]:
            lines.append(f"- {s['where']}: Word «{s['word']}» / extraction «{s['ours']}»")
        lines.append("")
    lines += ["## Quotes for review", ""]
    for r in rows:
        for x in r["review"]:
            lines.append(f"- {r['file']} ({x['where']}): {x['status']}, {x['found']} — {x['text']}")
    (args.extract / "check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.extract / "check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()

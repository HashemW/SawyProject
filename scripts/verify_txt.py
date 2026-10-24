"""Check the clean_txt conversions against Word's own reading of the source documents.

Inputs:
  --sources  folder with the original .doc/.docx files (Drive folder sawi_material)
  --word     output folder of scripts/word_export.ps1 (text/, notes/, xml/, word_inventory.json)
  --clean    folder with the clean_txt .txt files
  --out      folder for report.json (everything), report.md (summary) and quran/ (glyph quotes)

Run: python -I -X utf8 scripts/verify_txt.py --sources ... --word ... --clean ... --out ...

The reference is the document's visible main text, rebuilt from Word's own XML so that
text typed in glyph fonts is known exactly. Two encodings occur in the sources: <w:sym>
characters (HQPB1-5 Quran fonts, AGA Arabesque brackets/honorifics; Word's plain text
shows these as "(") and private-use characters inside ordinary text (Othmani1-5 Quran
fonts). Each glyph passage becomes one QURAN token (Quran font, or followed by a
[سورة: آية] reference) or one SYMBOL token; everything else is compared line -> word ->
character and every difference is classified. Quran passages are then paired with the
clean_txt's ﴿...﴾ passages to check how much of each verse was kept. Table cells and
footnotes are looked up in the clean_txt directly.
"""
import argparse
import collections
import difflib
import gzip
import json
import pathlib
import re
import unicodedata
import xml.etree.ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PKG = "{http://schemas.microsoft.com/office/2006/xmlPackage}"
NOTE_SEPARATORS = ("separator", "continuationSeparator", "continuationNotice")

GLYPH = "\ue000"           # one glyph-font character in the rebuilt reference text
QURAN = "\u27e6Q\u27e7"   # one whole Quran glyph passage, after collapsing
SYMBOL = "\u27e6S\u27e7"  # any other glyph run (honorifics, ornaments)
NOTE_REF = "\u0002"
OPEN, CLOSE = "\ufd3f", "\ufd3e"   # ornate parentheses that open and close a Quran quote
GLYPH_RUN = re.compile(GLYPH + r"(?:[\s" + GLYPH + r"]*" + GLYPH + r")?")
CLEAN_QUOTE = re.compile(OPEN + "[^" + CLOSE + "]*" + CLOSE)
QURAN_FONT = re.compile(r"HQPB|Othmani|QCF|Quran|Mushaf|KFGQPC|Uthman", re.I)
VERSE_REF = re.compile(r"\s*[\[(]\s*[\u0621-\u064a][^\])\n]{0,40}?[\d\u0660-\u0669]")

BIDI_CONTROLS = dict.fromkeys(map(ord, "\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))
# Word's Range.Text special characters (word_export.ps1 text/): U+0002 note reference,
# U+0007 end of cell, U+000E column break, U+001E non-breaking hyphen, U+001F optional
# hyphen, U+0001/U+0005/U+0008 object/comment/drawing anchors.
WORD_CHARS = {0x02: None, 0x01: None, 0x05: None, 0x08: None, 0x1F: None, 0x1E: "-", 0x07: "\n", 0x0E: "\n"}
LINE_SPLIT = re.compile(r"\r\n|[\r\n\v\f\u2028\u2029]")
DIGITS = set("0123456789\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9")
# UTF-8 Arabic bytes read as cp1252/latin-1, and cp1256 Arabic read as latin-1.
MOJIBAKE = re.compile(r"[\u00d8\u00d9\u00da\u00db][\u0080-\u00bf\u2018-\u203a\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u20ac\u2122]|[\u00c0-\u00ff]{3,}")
QMARK_IN_WORD = re.compile(r"[\u0621-\u064a]\?+[\u0621-\u064a]")
LATIN_BETWEEN_ARABIC = re.compile(r"(?<=[\u0600-\u06ff])\s?[A-Za-z]{1,3}\s?(?=[\u0600-\u06ff])")
EMPTY_PARENS = re.compile(r"\(\s*\)")
SAMPLES = 25


def is_arabic_letter(c):
    return "\u0600" <= c <= "\u08ff" and unicodedata.category(c) == "Lo"


def is_latin_letter(c):
    return c.isalpha() and (c.isascii() or "\u00c0" <= c <= "\u024f")


def is_pua(c):
    o = ord(c)
    return 0xE000 <= o <= 0xF8FF or o >= 0xF0000


def stem_key(name):
    name = unicodedata.normalize("NFC", name)
    for ext in (".docx", ".doc", ".txt"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    return name.strip()


def read_text(path):
    raw = path.read_bytes()
    info = {"bytes": len(raw), "bom": raw.startswith(b"\xef\xbb\xbf")}
    try:
        text = raw.decode("utf-8-sig")
        info["utf8"] = True
    except UnicodeDecodeError as e:
        info["utf8"] = False
        info["utf8_error"] = str(e)
        text = raw.decode("utf-8-sig", errors="replace")
    return text, info


def snippet(text, pos, width=40):
    return text[max(0, pos - width): pos + width].replace("\r", " ").replace("\n", " / ")


def integrity(text):
    """Character-level red flags in one text file."""
    r = collections.Counter()
    samples = collections.defaultdict(list)
    for i, c in enumerate(text):
        cat = unicodedata.category(c)
        if is_arabic_letter(c):
            r["arabic_letters"] += 1
        elif is_latin_letter(c):
            r["latin_letters"] += 1
        if c == "\ufffd":
            r["replacement_chars"] += 1
            if len(samples["replacement_chars"]) < SAMPLES:
                samples["replacement_chars"].append(snippet(text, i))
        elif is_pua(c) and c != GLYPH:
            r["private_use_chars"] += 1
            if len(samples["private_use_chars"]) < SAMPLES:
                samples["private_use_chars"].append(f"U+{ord(c):04X} " + snippet(text, i))
        elif cat == "Cc" and c not in "\r\n\t" and c != NOTE_REF:
            r["control_chars"] += 1
            if len(samples["control_chars"]) < SAMPLES:
                samples["control_chars"].append(f"U+{ord(c):04X} " + snippet(text, i))
        elif ord(c) in BIDI_CONTROLS:
            r["bidi_marks"] += 1
        elif cat == "Cf":
            r["other_format_chars"] += 1
    for key, rx in (("mojibake", MOJIBAKE), ("qmark_inside_word", QMARK_IN_WORD),
                    ("latin_between_arabic", LATIN_BETWEEN_ARABIC), ("empty_parens", EMPTY_PARENS)):
        for m in rx.finditer(text):
            r[key] += 1
            if len(samples[key]) < SAMPLES:
                samples[key].append(snippet(text, m.start()))
    lines = [l.strip() for l in LINE_SPLIT.split(text)]
    r["lines"] = sum(1 for l in lines if l)
    r["answer_markers"] = sum(1 for l in lines if l == "الجواب")
    r["closing_formulas"] = text.count("أعلى وأعلم")
    r["quran_brackets"] = text.count(OPEN)
    r["chars"] = len(text)
    out = dict(r)
    out["samples"] = dict(samples)
    return out


# ---------------------------------------------------------------- reference text from Word XML

def vanish_on(rpr):
    v = rpr.find(W + "vanish") if rpr is not None else None
    return v is not None and v.get(W + "val", "true") not in ("0", "false", "off")


class Document:
    """One pass over Word's flat-OPC XML: the visible main text plus an audit of the rest."""

    def __init__(self):
        self.text = []                              # visible main-story text pieces
        self.frames = []                            # text-box text, kept out of the main text
        self.cells = []                             # text of each table-cell paragraph
        self.notes = []                             # text of each footnote/endnote
        self.toc = []                               # table-of-contents text (TOC field results), kept out of the main text
        self._fields = []                           # open complex fields: their type, e.g. "TOC", "PAGEREF"
        self._para = []                             # visible text of the paragraph being read
        self.syms = []                              # (font, code) for every GLYPH, in order
        self.counts = collections.Counter()
        self.latin_fonts = collections.Counter()    # font -> Latin letters (symbol-font leaks show up here)
        self.arabic_fonts = collections.Counter()   # complex-script font -> Arabic letters
        self.sym_fonts = collections.Counter()      # font -> glyph characters
        self.fields = collections.Counter()
        self.samples = collections.defaultdict(list)

    def run(self, el, stack):
        a = self.counts
        rpr = el.find(W + "rPr")
        if any(t in stack for t in (W + "del", W + "moveFrom")) or el.find(W + "delText") is not None:
            a["deleted_chars"] += sum(len(t.text or "") for t in el.iter(W + "delText")) + sum(len(t.text or "") for t in el.iter(W + "t"))
            return
        rf = rpr.find(W + "rFonts") if rpr is not None else None
        font = lambda *keys: next((rf.get(W + k) for k in keys if rf is not None and rf.get(W + k)), "(style default)")
        pieces = []
        for child in el:
            tag = child.tag
            if tag == W + "t":
                t = child.text or ""
                if any(is_pua(c) for c in t):
                    # Symbol-font text stored as private-use characters (e.g. Othmani Quran fonts).
                    f = font("ascii", "hAnsi", "cs")
                    out = []
                    for c in t:
                        if is_pua(c):
                            out.append(GLYPH)
                            self.syms.append((f, f"{ord(c):04X}"))
                            self.sym_fonts[f] += 1
                        else:
                            out.append(c)
                    t = "".join(out)
                pieces.append(t)
            elif tag == W + "tab":
                pieces.append("\t")
            elif tag in (W + "br", W + "cr"):
                pieces.append("\n")
            elif tag == W + "noBreakHyphen":
                pieces.append("-")
            elif tag == W + "sym":
                pieces.append(GLYPH)
                key = (child.get(W + "font"), child.get(W + "char"))
                self.syms.append(key)
                self.sym_fonts[key[0]] += 1
            elif tag in (W + "footnoteReference", W + "endnoteReference"):
                pieces.append(NOTE_REF)
                a[tag[len(W):]] += 1
            elif tag == W + "fldChar":
                kind = child.get(W + "fldCharType")
                if kind == "begin":
                    self._fields.append(None)
                elif kind == "end" and self._fields:
                    self._fields.pop()
            elif tag == W + "instrText" and self._fields and self._fields[-1] is None and (child.text or "").split():
                self._fields[-1] = child.text.split()[0].upper()
        text = "".join(pieces)
        if "TOC" in self._fields:
            self.toc.append(text)
            a["toc_chars"] += len(text)
            if GLYPH in text:
                del self.syms[len(self.syms) - text.count(GLYPH):]
            return
        if vanish_on(rpr):
            a["hidden_chars"] += len(text)
            if text.strip() and len(self.samples["hidden"]) < SAMPLES:
                self.samples["hidden"].append(text[:200])
            if GLYPH in text:   # keep self.syms aligned with the visible text
                del self.syms[len(self.syms) - text.count(GLYPH):]
            return
        if W + "txbxContent" in stack:
            self.frames.append(text)
            a["textbox_chars"] += len(text)
            if GLYPH in text:
                del self.syms[len(self.syms) - text.count(GLYPH):]
            return
        self.text.append(text)
        self._para.append(text)
        a["visible_chars"] += len(text)
        if W + "ins" in stack or W + "moveTo" in stack:
            a["inserted_chars"] += len(text)
        if W + "tbl" in stack:
            a["table_chars"] += len(text)
        latin = sum(1 for c in text if is_latin_letter(c))
        if latin:
            self.latin_fonts[font("ascii", "hAnsi")] += latin
            if len(self.samples["latin"]) < 60:
                self.samples["latin"].append([font("ascii", "hAnsi"), text[:80]])
        arabic = sum(1 for c in text if is_arabic_letter(c))
        if arabic:
            self.arabic_fonts[font("cs")] += arabic
    def element(self, tag, el, stack):
        a = self.counts
        if tag == W + "r":
            self.run(el, stack)
            el.clear()
        elif tag == W + "p":
            if W + "txbxContent" in stack:
                self.frames.append("\n")
            else:
                self.text.append("\n")
                if "TOC" in self._fields:
                    self.toc.append("\n")
                if W + "tbl" in stack:
                    self.cells.append("".join(self._para))
                self._para = []
                a["paragraphs"] += 1
                ppr = el.find(W + "pPr")
                if ppr is not None and ppr.find(W + "numPr") is not None:
                    a["numbered_paragraphs"] += 1
            el.clear()
        elif tag == W + "tbl":
            a["tables"] += 1
        elif tag == W + "txbxContent":
            a["text_boxes"] += 1
        elif tag in (W + "drawing", W + "pict", W + "object"):
            a["images_or_objects"] += 1
        elif tag == W + "instrText" and el.text and el.text.split():
            self.fields[el.text.split()[0].upper()] += 1
        elif tag == W + "fldSimple" and el.get(W + "instr", "").split():
            self.fields[el.get(W + "instr").split()[0].upper()] += 1


def read_word_xml(path):
    """Parse the gzipped flat-OPC package written by word_export.ps1."""
    doc = Document()
    a = doc.counts
    part = None
    stack = []
    with gzip.open(path, "rb") as f:
        for event, el in ET.iterparse(f, events=("start", "end")):
            if event == "start":
                if el.tag == PKG + "part":
                    part = el.get(PKG + "name")
                stack.append(el.tag)
                continue
            stack.pop()
            tag = el.tag
            if tag == PKG + "part":
                part = None
                el.clear()
            elif part in ("/word/footnotes.xml", "/word/endnotes.xml"):
                if tag in (W + "footnote", W + "endnote"):
                    if el.get(W + "type") not in NOTE_SEPARATORS:
                        kind = "footnote" if tag == W + "footnote" else "endnote"
                        note = "".join(t.text or "" for t in el.iter(W + "t"))
                        doc.notes.append(note)
                        a[kind + "s"] += 1
                        a[kind + "_chars"] += len(note)
                    el.clear()
            elif part == "/word/comments.xml":
                if tag == W + "comment":
                    a["comments"] += 1
                    el.clear()
            elif part == "/word/document.xml":
                if MC + "Fallback" in stack:   # duplicate of the mc:Choice content
                    if tag in (W + "r", W + "p"):
                        el.clear()
                else:
                    doc.element(tag, el, stack)
    return doc


def glyph_passages(text, syms):
    """Collapse each glyph run into a QURAN or SYMBOL token; describe every run in order.

    A run is Quran when any of its glyphs uses a Quran font or it is followed by a
    verse reference like [البقرة: 61].
    """
    passages = []
    out = []
    outlen = 0
    pos = 0
    used = 0
    for m in GLYPH_RUN.finditer(text):
        run = m.group()
        n = run.count(GLYPH)
        mine = syms[used: used + n]
        groups = [g for g in run.split() if g]
        after = text[m.end(): m.end() + 40].split("\n")[0]
        fonts = sorted({f for f, _ in mine})
        quran = any(QURAN_FONT.search(f or "") for f in fonts) or bool(VERSE_REF.match(after))
        bounds = [0]
        for g in groups:
            bounds.append(bounds[-1] + len(g))
        before = text[pos: m.start()]
        token = " " + (QURAN if quran else SYMBOL) + " "
        passages.append({
            "kind": "quran" if quran else "symbol",
            "pos": outlen + len(before),
            "glyphs": n,
            "glyph_words": len(groups),
            "fonts": fonts,
            "codes": [" ".join(c for _, c in mine[bounds[k]: bounds[k + 1]]) for k in range(len(groups))],
            "before": text[max(0, m.start() - 40): m.start()].split("\n")[-1],
            "after": after.strip(),
        })
        used += n
        out += [before, token]
        outlen += len(before) + len(token)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), passages


# ---------------------------------------------------------------- comparison

def units(text):
    """Lines normalized for comparison: NFC, no bidi marks or note refs, single spaces, no empty lines."""
    text = unicodedata.normalize("NFC", text).translate(BIDI_CONTROLS).replace(NOTE_REF, "")
    return [" ".join(l.split()) for l in LINE_SPLIT.split(text) if l.split()]


def char_class(s):
    s = "".join(s.split())
    if not s:
        return "whitespace"
    if QURAN in s or OPEN in s or CLOSE in s:
        return "quran"
    if SYMBOL in s:
        return "symbol"
    if any(is_arabic_letter(c) for c in s):
        return "arabic"
    if any(is_latin_letter(c) for c in s):
        return "latin"
    if all(c in DIGITS for c in s):
        return "digits"
    if all(c == "\u0640" for c in s):   # tatweel
        return "tatweel"
    if all(unicodedata.category(c) == "Mn" for c in s):
        return "diacritics"
    if all(unicodedata.category(c)[0] in "PS" for c in s):
        return "punctuation"
    if all(unicodedata.category(c) in ("Cf", "Cc") for c in s):
        return "format"
    return "mixed"


def nonspace(s):
    return sum(1 for c in s if not c.isspace())


class Diff:
    def __init__(self):
        self.matched = 0
        self.missing = collections.Counter()   # class -> chars in the source, absent from clean_txt
        self.extra = collections.Counter()     # class -> chars in clean_txt, absent from the source
        self.samples = collections.defaultdict(list)

    def edit(self, gone, added, where):
        key = char_class(gone + added)
        if gone:
            self.missing[key if key == "quran" else char_class(gone)] += nonspace(gone)
        if added:
            self.extra[key if key == "quran" else char_class(added)] += nonspace(added)
        if key not in ("whitespace", "quran") and len(self.samples[key]) < SAMPLES:
            self.samples[key].append({"line": where, "source": gone[:300], "clean": added[:300]})

    def chars(self, a, b, where):
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                self.matched += nonspace(a[i1:i2])
            else:
                self.edit(a[i1:i2], b[j1:j2], where)

    def words(self, a, b, where):
        wa, wb = a.split(" "), b.split(" ")
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
            da, db = " ".join(wa[i1:i2]), " ".join(wb[j1:j2])
            if tag == "equal":
                self.matched += nonspace(da)
            elif QURAN in da or OPEN in db or len(da) + len(db) > 600:
                self.edit(da, db, where)
            else:
                self.chars(da, db, where)

    def lines(self, ref, cand):
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ref, cand).get_opcodes():
            if tag == "equal":
                self.matched += sum(nonspace(l) for l in ref[i1:i2])
            elif tag == "delete":
                self.edit(" ".join(ref[i1:i2]), "", i1 + 1)
            elif tag == "insert":
                self.edit("", " ".join(cand[j1:j2]), i1 + 1)
            else:
                self.words(" ".join(ref[i1:i2]), " ".join(cand[j1:j2]), i1 + 1)


def arabic_words(lines):
    return collections.Counter(w for l in lines for w in l.split(" ") if any(is_arabic_letter(c) for c in w))


def compare(ref_text, clean_text):
    ref, cand = units(ref_text), units(clean_text)
    d = Diff()
    d.lines(ref, cand)
    # Order-independent check, with Quran (glyph or ﴿…﴾) and symbol passages removed from both sides.
    rw = arabic_words(units(CLEAN_QUOTE.sub(" ", ref_text.replace(QURAN, " ").replace(SYMBOL, " "))))
    cw = arabic_words(units(CLEAN_QUOTE.sub(" ", clean_text)))
    missing_words, extra_words = rw - cw, cw - rw
    ref_chars = sum(nonspace(l) for l in ref)
    return {
        "source_lines": len(ref),
        "clean_lines": len(cand),
        "source_chars": ref_chars,
        "clean_chars": sum(nonspace(l) for l in cand),
        "matched_chars": d.matched,
        "missing": dict(d.missing),
        "extra": dict(d.extra),
        "arabic_words_source": sum(rw.values()),
        "arabic_words_missing": sum(missing_words.values()),
        "arabic_words_extra": sum(extra_words.values()),
        "top_missing_words": missing_words.most_common(15),
        "top_extra_words": extra_words.most_common(15),
        "samples": dict(d.samples),
    }


def compare_quran(passages, ref_text, clean_text):
    """Pair the source's Quran passages (glyph or Unicode ﴿...﴾) with clean_txt ﴿...﴾ passages
    by the verse reference that follows each one."""
    quran = [dict(p, words=max(p["glyph_words"] - 2, 1)) for p in passages if p["kind"] == "quran"]
    for m in CLEAN_QUOTE.finditer(ref_text):
        words = [w for w in m.group().split() if any(is_arabic_letter(c) for c in w)]
        quran.append({"pos": m.start(), "words": len(words), "after": ref_text[m.end(): m.end() + 40].split("\n")[0].strip()})
    quran.sort(key=lambda p: p["pos"])
    clean = []
    for m in CLEAN_QUOTE.finditer(clean_text):
        words = [w for w in m.group().split() if any(is_arabic_letter(c) for c in w)]
        after = clean_text[m.end(): m.end() + 40].strip().split("\n")[0]
        clean.append({"words": len(words), "after": after, "text": m.group()})
    ref_key = lambda s: re.sub(r"\s+", "", s.split("]")[0]) if s.startswith("[") else ""
    a = [ref_key(p["after"]) for p in quran]
    b = [ref_key(c["after"]) for c in clean]
    pairs = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            pairs += list(zip(range(i1, i2), range(j1, j2)))
    rows = []
    for i, j in pairs:
        p, c = quran[i], clean[j]
        # For glyph passages p["words"] is an upper bound: brackets, pause marks and verse
        # numbers can be separate glyph groups. "expanded" is therefore a lower bound.
        rows.append({"source_words": p["words"], "clean_words": c["words"], "reference": p["after"][:30],
                     "expanded": c["words"] > p["words"] + 2, "shortened": c["words"] < p["words"] - 2,
                     "clean_text": c["text"][:200]})
    back_to_back = re.compile(CLOSE + r"\s*" + OPEN)
    return {
        "source_passages": len(quran),
        "source_glyph_passages": sum(1 for p in quran if "glyphs" in p),
        "clean_passages": len(clean),
        "paired": len(rows),
        "expanded": sum(r["expanded"] for r in rows),
        "shortened": sum(r["shortened"] for r in rows),
        "back_to_back_source": len(back_to_back.findall(ref_text)),
        "back_to_back_clean": len(back_to_back.findall(clean_text)),
        "source_words": sum(r["source_words"] for r in rows),
        "clean_words": sum(r["clean_words"] for r in rows),
        "examples": [r for r in rows if r["expanded"] or r["shortened"]][:10],
    }


def lookup_norm(s):
    s = unicodedata.normalize("NFC", s).translate(BIDI_CONTROLS)
    s = "".join(c for c in s if not is_pua(c) and c != NOTE_REF)
    return " ".join(s.split())


def lookups(doc, clean_text):
    """Are the source's table cells and footnotes anywhere in the clean_txt file?"""
    clean = lookup_norm(clean_text)
    out = {}
    for key, items, probe_len in (("table_cells", doc.cells, None), ("notes", doc.notes, 40)):
        items = [lookup_norm(t) for t in items]
        items = [t for t in items if sum(1 for w in t.split() if any(is_arabic_letter(c) for c in w)) >= 3]
        missing = [t for t in items if (t[:probe_len] if probe_len else t) not in clean]
        out[key] = {"total": len(items), "found": len(items) - len(missing), "missing_samples": [t[:200] for t in missing[:8]]}
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", required=True, type=pathlib.Path)
    ap.add_argument("--word", required=True, type=pathlib.Path)
    ap.add_argument("--clean", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--only", help="substring filter on source file names (for quick runs)")
    args = ap.parse_args()
    (args.out / "quran").mkdir(parents=True, exist_ok=True)

    inventory = {}
    inv_path = args.word / "word_inventory.json"
    if inv_path.exists():
        rows = json.loads(inv_path.read_text(encoding="utf-8-sig"))
        for row in rows if isinstance(rows, list) else [rows]:
            inventory[unicodedata.normalize("NFC", row["file"])] = row

    sources = sorted(p for p in args.sources.iterdir() if p.suffix.lower() in (".doc", ".docx"))
    txts = {stem_key(p.name): p for p in args.clean.iterdir() if p.suffix.lower() == ".txt"}
    used = set()
    results = []
    for src in sources:
        name = unicodedata.normalize("NFC", src.name)
        if args.only and args.only not in name:
            continue
        key = stem_key(name)
        row = {"source": name, "clean_txt": None, "word_export": inventory.get(name)}
        clean = txts.get(key)
        if clean:
            used.add(key)
            row["clean_txt"] = clean.name
        xml = args.word / "xml" / (src.name + ".xml.gz")
        if xml.exists():
            doc = read_word_xml(xml)
            ref_raw = "".join(doc.text)
            ref, passages = glyph_passages(ref_raw, doc.syms)
            audit = dict(doc.counts)
            audit["glyph_passages"] = dict(collections.Counter(p["kind"] for p in passages))
            audit["glyph_fonts"] = dict(doc.sym_fonts.most_common(20))
            audit["symbol_codes"] = dict(collections.Counter(
                f"{p['fonts'][0] if p['fonts'] else '?'}:{' '.join(p['codes'])}" for p in passages if p["kind"] == "symbol").most_common(15))
            audit["latin_letters_by_font"] = dict(doc.latin_fonts.most_common(20))
            audit["arabic_letters_by_font"] = dict(doc.arabic_fonts.most_common(20))
            audit["fields"] = dict(doc.fields.most_common(20))
            audit["samples"] = dict(doc.samples)
            row["xml_audit"] = audit
            row["source_integrity"] = integrity(ref)
            word_txt = args.word / "text" / (src.name + ".txt")
            if word_txt.exists():
                # Self-check: the XML-rebuilt reference should hold the same Arabic words as
                # Word's own plain text (Word's adds list numbers; neither has glyph passages).
                wt, _ = read_text(word_txt)
                xw = arabic_words(units(ref.replace(QURAN, " ").replace(SYMBOL, " ") + "\n" + "".join(doc.toc).replace(GLYPH, " ")))
                ww = arabic_words(units(wt.translate(WORD_CHARS)))
                row["reference_check"] = {"words": sum(xw.values()), "not_in_word_text": sum((xw - ww).values()),
                                          "only_in_word_text": sum((ww - xw).values()),
                                          "examples": [w for w, _ in ((xw - ww) + (ww - xw)).most_common(10)]}
            if passages:
                (args.out / "quran" / (src.name + ".json")).write_text(json.dumps(passages, ensure_ascii=False, indent=0), encoding="utf-8")
            if clean:
                ctext, cinfo = read_text(clean)
                row["clean_file"] = cinfo
                row["clean_integrity"] = integrity(ctext)
                row["comparison"] = compare(ref, ctext)
                row["quran"] = compare_quran(passages, ref, ctext)
                row["lookups"] = lookups(doc, ctext)
        results.append(row)
        c = row.get("comparison") or {}
        print(f"{name}: missing_ar_words={c.get('arabic_words_missing')} extra_ar_words={c.get('arabic_words_extra')}", flush=True)

    orphans = [] if args.only else sorted(p.name for k, p in txts.items() if k not in used)
    report = {"pairs": results, "clean_txt_without_source": orphans}
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(report, args.out / "report.md")


def write_markdown(report, path):
    pairs = report["pairs"]
    t = collections.Counter()
    rows = []
    for r in pairs:
        c, q, lk = r.get("comparison"), r.get("quran") or {}, r.get("lookups") or {}
        w = r.get("word_export") or {}
        rc = r.get("reference_check") or {}
        t["ref_words"] += rc.get("words", 0)
        t["ref_not_in_word"] += rc.get("not_in_word_text", 0)
        t["ref_only_in_word"] += rc.get("only_in_word_text", 0)
        if w.get("status") == "error":
            t["word_errors"] += 1
            rows.append(f"| {r['source']} | Word cannot open it: {w.get('error', '')[:60]} | | | | | | |")
            continue
        if not c:
            t["no_clean_txt"] += 1
            rows.append(f"| {r['source']} | NO clean_txt | | | | | | |")
            continue
        cells, notes = lk.get("table_cells", {}), lk.get("notes", {})
        for k in ("arabic_words_source", "arabic_words_missing", "arabic_words_extra"):
            t[k] += c[k]
        t["cells"] += cells.get("total", 0)
        t["cells_found"] += cells.get("found", 0)
        t["notes"] += notes.get("total", 0)
        t["notes_found"] += notes.get("found", 0)
        for k in ("source_passages", "source_glyph_passages", "clean_passages", "paired", "expanded", "shortened",
                  "back_to_back_source", "back_to_back_clean"):
            t["quran_" + k] += q.get(k, 0)
        found = 1 - c["arabic_words_missing"] / c["arabic_words_source"] if c["arabic_words_source"] else 1
        rows.append("| {src} | {found:.2%} | {ws} | {mw} | {ew} | {cells} | {notes} | {q} |".format(
            src=r["source"], found=found, ws=c["arabic_words_source"], mw=c["arabic_words_missing"], ew=c["arabic_words_extra"],
            cells=f"{cells['found']}/{cells['total']}" if cells.get("total") else "",
            notes=f"{notes['found']}/{notes['total']}" if notes.get("total") else "",
            q=f"{q['source_passages']} / {q['clean_passages']} / {q['expanded']} / {q['back_to_back_clean'] - q['back_to_back_source']}"
            if q.get("source_passages") or q.get("clean_passages") else ""))
    pct = lambda a, b: f"{a / b:.2%}" if b else "n/a"
    lines = [
        "# clean_txt vs the Word source",
        "",
        "## Totals",
        "",
        f"- Source files: {len(pairs)}; Word could not open: {t['word_errors']}; no clean_txt file: {t['no_clean_txt']}",
        f"- Reference self-check (XML-rebuilt text vs Word's own plain text): {t['ref_words']:,} Arabic words; "
        f"{t['ref_not_in_word']:,} only in the rebuilt text, {t['ref_only_in_word']:,} only in Word's text (list numbers)",
        f"- Arabic words outside Quran passages: {t['arabic_words_source']:,}; missing from clean_txt: "
        f"{t['arabic_words_missing']:,} ({pct(t['arabic_words_missing'], t['arabic_words_source'])}); extra in clean_txt: {t['arabic_words_extra']:,}",
        f"- Table cells found in clean_txt: {t['cells_found']:,} of {t['cells']:,}",
        f"- Footnotes found in clean_txt: {t['notes_found']:,} of {t['notes']:,}",
        f"- Quran passages in sources: {t['quran_source_passages']:,} ({t['quran_source_glyph_passages']:,} in glyph fonts, the rest Unicode ﴿…﴾); "
        f"﴿…﴾ passages in clean_txt: {t['quran_clean_passages']:,}; paired by verse reference: {t['quran_paired']:,}; "
        f"of those, longer than the source quote: {t['quran_expanded']:,} (lower bound), shorter: {t['quran_shortened']:,}; "
        f"back-to-back ﴾﴿ duplicates added: {t['quran_back_to_back_clean'] - t['quran_back_to_back_source']:,}",
        "- clean_txt files with no source: " + (", ".join(report["clean_txt_without_source"]) or "none"),
        "",
        "## Per file",
        "",
        "Words found = share of the source's Arabic words (glyph passages excluded) present in clean_txt.",
        "Quran = passages in source / \ufd3f\u2026\ufd3e passages in clean_txt / paired passages longer than the source quote / back-to-back duplicates added.",
        "",
        "| source | words found | source words | missing | extra | table cells found | footnotes found | Quran |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

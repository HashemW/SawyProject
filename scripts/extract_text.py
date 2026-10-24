"""Extract the Sheikh's books from Word's XML into text: every paragraph, table cell and footnote,
with Quran quotes and honorifics typed in glyph fonts turned into real text.

Inputs:
  --word   output folder of scripts/word_export.ps1. Reads final/<name>.xml.gz (Word's XML after
           list numbers were converted to text); falls back to xml/ when final/ is missing.
  --quran  Tanzil's Uthmani text, "sura|aya|text" lines (data/raw/quran/quran-uthmani.txt)
  --out    output folder:
             json/<name>.json        blocks (paragraphs, table cells, text boxes, table-of-contents
                                     lines) and footnotes, with the position of every Quran quote,
                                     honorific and footnote reference in their text
             text/<name>.txt         main text, one paragraph, table cell or text-box paragraph per
                                     line; tables of contents are left out (they are in the JSON)
             text/<name>.notes.txt   footnotes, "<n><TAB><text>" one per line
             report.json, report.md  per-file counts and every quote that needs a human look

Run: python -I -X utf8 scripts/extract_text.py --word data/work/word --quran data/raw/quran/quran-uthmani.txt --out data/work/extract

Quran quotes (see quran_glyphs.py) are replaced by Tanzil's text of exactly the quoted words,
between the source's own brackets. The first pass identifies every quote in every file; words
whose glyphs are spelled the same in several places of the Quran are then settled by how the
same glyphs read in quotes that were identified without doubt. The second pass writes the output.
"""
import argparse
import collections
import gzip
import io
import itertools
import json
import pathlib
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # python -I leaves the script folder out
import quran_glyphs as Q  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PKG = "{http://schemas.microsoft.com/office/2006/xmlPackage}"
NOTE_SEPARATORS = ("separator", "continuationSeparator", "continuationNotice")

# Glyphs of other symbol fonts: bullets and marks with a plain-text equivalent; anything else is
# an ornament and is dropped from the text (and counted in the report).
OTHER_GLYPHS = {"Symbol:B7": "•", "Lotus Linotype:B7": "•", "Wingdings 2:97": "•", "ACS  Symbols:4D": "•",
                "Wingdings:A7": "•", "Wingdings:76": "•", "Symbol:D6": "√", "Symbol:2D": "-", "AGA Arabesque:2D": "-",
                **{f"AGA Arabesque:{0x30 + d:02X}": str(d) for d in range(10)}}   # list numbers set in AGA Arabesque
JUNK = set(".،:؛…/")     # characters found standing in for a glyph inside a quote ("." = 0x2E, "/" = 0x2F)


def is_pua(c):
    return 0xE000 <= ord(c) <= 0xF8FF


def on(el, name):
    """A boolean run/paragraph property that is present and not switched off."""
    x = el.find(W + name) if el is not None else None
    return x is not None and x.get(W + "val", "true") not in ("0", "false", "off")


# ---------------------------------------------------------------- reading Word's XML

class Styles:
    """Style names, outline levels and fonts; which fonts are symbol fonts (charset 02)."""

    def __init__(self, raw):
        self.symbol = set(re.findall(r'<w:font w:name="([^"]+)">(?:(?!</w:font>).)*?<w:charset w:val="02"', raw, re.S))
        self.name, self.outline, self.based, self.fonts, self.caps = {}, {}, {}, {}, {}
        part = re.search(r'<pkg:part pkg:name="/word/styles.xml".*?</pkg:part>', raw, re.S)
        for m in re.finditer(r"<w:style [^>]*w:styleId=\"([^\"]+)\"[^>]*>(.*?)</w:style>", part.group(0) if part else "", re.S):
            sid, body = m.groups()
            n = re.search(r'<w:name w:val="([^"]+)"', body)
            self.name[sid] = n.group(1) if n else sid
            o = re.search(r'<w:outlineLvl w:val="(\d+)"', body)
            if o:
                self.outline[sid] = int(o.group(1))
            b = re.search(r'<w:basedOn w:val="([^"]+)"', body)
            if b:
                self.based[sid] = b.group(1)
            f = re.search(r"<w:rFonts ([^>]*)/>", body)
            if f:
                self.fonts[sid] = dict(re.findall(r'w:(ascii|hAnsi|cs)="([^"]+)"', f.group(1)))
            c = re.search(r'<w:rPr>(?:(?!</w:rPr>).)*?<w:caps(?: w:val="([^"]+)")?/>', body, re.S)
            if c:
                self.caps[sid] = c.group(1) not in ("0", "false", "off")
        d = re.search(r"<w:rPrDefault>.*?<w:rFonts ([^>]*)/>", raw, re.S)
        self.default_fonts = dict(re.findall(r'w:(ascii|hAnsi|cs)="([^"]+)"', d.group(1))) if d else {}

    def chain(self, sid):
        seen = []
        while sid and sid not in seen:
            seen.append(sid)
            sid = self.based.get(sid)
        return seen

    def outline_of(self, sid):
        return next((self.outline[s] for s in self.chain(sid) if s in self.outline), None)

    def font_of(self, sid, slot):
        for s in self.chain(sid):
            if slot in self.fonts.get(s, {}):
                return self.fonts[s][slot]
        return None

    def caps_of(self, sid):
        return next((self.caps[s] for s in self.chain(sid) if s in self.caps), None)


class Block:
    def __init__(self, kind, style=None, outline=None, table=None):
        self.kind, self.style, self.outline, self.table = kind, style, outline, table
        self.pieces = []          # ("t", text, toc) | ("g", key, font, code) | ("ref", n) | ("mark",)
        self.toc_chars = 0
        self.chars = 0

    def text(self, s, toc):
        if s:
            self.pieces.append(("t", s, toc))
            self.chars += len(s)
            self.toc_chars += len(s) if toc else 0


class Reader:
    """One pass over a flat-OPC package: blocks of the main story and of the footnotes/endnotes."""

    def __init__(self, raw):
        self.styles = Styles(raw)
        self.blocks = []
        self.notes = {"footnote": {}, "endnote": {}}     # xml id -> [Block]
        self.refs = {"footnote": [], "endnote": []}       # xml ids in order of reference
        self.counts = collections.Counter()
        self._stack = []          # open blocks (paragraphs can nest inside text boxes)
        self._tables = []         # [table no, row, col] for each open table
        self._ntables = 0
        self._fields = []         # open complex fields: [type, in_result]
        self._note = None
        self._parse(raw)

    def _parse(self, raw):
        part, stack = None, []
        for event, el in ET.iterparse(io.BytesIO(raw.encode("utf-8")), events=("start", "end")):
            tag = el.tag
            if event == "start":
                if tag == PKG + "part":
                    part = el.get(PKG + "name")
                stack.append(tag)
                if part in ("/word/document.xml", "/word/footnotes.xml", "/word/endnotes.xml") and MC + "Fallback" not in stack:
                    self._start(tag, el, stack, part)
                continue
            stack.pop()
            if tag == PKG + "part":
                part = None
                el.clear()
            elif part in ("/word/document.xml", "/word/footnotes.xml", "/word/endnotes.xml"):
                if MC + "Fallback" in stack or tag == MC + "Fallback":
                    if tag in (W + "p", W + "r"):
                        el.clear()
                    continue
                self._end(tag, el, stack, part)

    def _start(self, tag, el, stack, part):
        if tag == W + "tbl":
            self._ntables += 1
            self._tables.append([self._ntables, -1, -1])
        elif tag == W + "tr" and self._tables:
            self._tables[-1][1] += 1
            self._tables[-1][2] = -1
        elif tag == W + "tc" and self._tables:
            self._tables[-1][2] += 1
        elif tag in (W + "footnote", W + "endnote"):
            kind = tag[len(W):]
            self._note = None if el.get(W + "type") in NOTE_SEPARATORS else (kind, el.get(W + "id"))
            if self._note:
                self.notes[kind][self._note[1]] = []
        elif tag == W + "p":
            if part != "/word/document.xml":
                kind = "note"
            elif W + "txbxContent" in stack:
                kind = "textbox"
            else:
                kind = "cell" if self._tables else "p"
            table = tuple(self._tables[-1]) if self._tables and kind == "cell" else None
            self._stack.append(Block(kind, table=table))

    def _end(self, tag, el, stack, part):
        if tag == W + "r":
            if self._stack:
                self._run(el)
            el.clear()
        elif tag == W + "pPr" and self._stack and stack and stack[-1] == W + "p":
            ps = el.find(W + "pStyle")
            self._stack[-1].sid = ps.get(W + "val") if ps is not None else None
            o = el.find(W + "outlineLvl")
            self._stack[-1].outline = int(o.get(W + "val")) if o is not None else None
        elif tag == W + "p":
            b = self._stack.pop() if self._stack else None
            if b is not None:
                sid = getattr(b, "sid", None)
                b.style = self.styles.name.get(sid, sid)
                if b.outline is None:
                    b.outline = self.styles.outline_of(sid)
                visible = [p for p in b.pieces if p[0] != "t" or p[1].strip()]
                if b.kind == "p" and visible and all(p[0] == "t" and p[2] for p in visible):
                    b.kind = "toc"
                if b.kind == "note":
                    if self._note:
                        self.notes[self._note[0]][self._note[1]].append(b)
                else:
                    self.blocks.append(b)
                self.counts["paragraphs_" + b.kind] += 1
            el.clear()
        elif tag == W + "tbl":
            self._tables.pop()
        elif tag in (W + "footnote", W + "endnote"):
            self._note = None
            el.clear()
        elif tag in (W + "drawing", W + "pict", W + "object"):
            self.counts["objects"] += 1

    def _run(self, el):
        b = self._stack[-1]
        rpr = el.find(W + "rPr")
        if el.find(W + "delText") is not None:
            self.counts["deleted_runs"] += 1
            return
        if on(rpr, "vanish"):
            self.counts["hidden_chars"] += sum(len(t.text or "") for t in el.iter(W + "t"))
            return
        rf = rpr.find(W + "rFonts") if rpr is not None else None
        rstyle = rpr.find(W + "rStyle").get(W + "val") if rpr is not None and rpr.find(W + "rStyle") is not None else None

        def font(slot):
            if rf is not None and rf.get(W + slot):
                return rf.get(W + slot)
            for sid in (rstyle, getattr(b, "sid", None)):
                f = self.styles.font_of(sid, slot) if sid else None
                if f:
                    return f
            return self.styles.default_fonts.get(slot)

        complex_script = on(rpr, "rtl") or on(rpr, "cs")
        # "All caps" formatting (on the run, its character style or the paragraph's style, e.g.
        # TOC 1) is shown, and read by Word, in capitals.
        if rpr is not None and rpr.find(W + "caps") is not None:
            caps = on(rpr, "caps")
        else:
            caps = next((c for c in (self.styles.caps_of(rstyle), self.styles.caps_of(getattr(b, "sid", None))) if c is not None), False)
        toc = any(f[0] == "TOC" for f in self._fields)
        for child in el:
            tag = child.tag
            if tag == W + "t":
                self._chars(b, (child.text or "").upper() if caps else child.text or "", font, complex_script, toc)
            elif tag == W + "sym":
                f, c = child.get(W + "font"), child.get(W + "char")
                b.pieces.append(("g", Q.glyph_key(f, c), f, c.upper(), "("))   # Word's text shows a symbol as "("
                b.chars += 1
                self.counts["glyphs_read"] += 1
            elif tag in (W + "tab", W + "ptab"):
                b.text("\t", toc)
            elif tag in (W + "br", W + "cr"):
                b.text("\n", toc)
            elif tag == W + "noBreakHyphen":
                b.text("-", toc)
            elif tag in (W + "footnoteReference", W + "endnoteReference"):
                kind = tag[len(W):-len("Reference")]
                self.refs[kind].append(child.get(W + "id"))
                b.pieces.append(("ref", kind, child.get(W + "id"), child.get(W + "customMarkFollows") in ("1", "true", "on")))
            elif tag in (W + "footnoteRef", W + "endnoteRef"):
                b.pieces.append(("mark",))
            elif tag == W + "fldChar":
                kind = child.get(W + "fldCharType")
                if kind == "begin":
                    self._fields.append([None, False])
                elif kind == "separate" and self._fields:
                    self._fields[-1][1] = True
                elif kind == "end" and self._fields:
                    self._fields.pop()
            elif tag == W + "instrText" and self._fields and self._fields[-1][0] is None and (child.text or "").split():
                self._fields[-1][0] = child.text.split()[0].upper()

    def _chars(self, b, text, font, complex_script, toc):
        """Plain text, except characters Word draws from a glyph font: private-use characters;
        ASCII/Latin-1 characters set in a symbol font, in runs not marked right-to-left; and any
        character set in a font that draws honorifics on ordinary characters (Q.LETTER_FONTS)."""
        buf = []
        for c in text:
            o = ord(c)
            sym = None
            if is_pua(c):
                f = font("ascii") or font("hAnsi") or font("cs")
                sym = (Q.glyph_key(f, f"{o:04X}"), f)
            elif not c.isspace():
                arabic = "\u0600" <= c <= "\u06ff" or "\ufb50" <= c <= "\ufeff"
                f = font("cs" if complex_script or arabic else "ascii" if o < 0x80 else "hAnsi")
                if f in Q.LETTER_FONTS:
                    sym = ("L:" + c, f)
                elif o < 0x100 and not complex_script and f in self.styles.symbol:
                    sym = (Q.glyph_key(f, f"{o:04X}"), f)
                    c = chr(0xF000 + o)     # how Word's own text shows a symbol-font character
            if sym:
                if buf:
                    b.text("".join(buf), toc)
                    buf = []
                b.pieces.append(("g", sym[0], sym[1], f"{o:04X}", c))
                b.chars += 1
                self.counts["glyphs_read"] += 1
                self.counts["glyphs_in_text_runs" if is_pua(c) else "glyphs_from_letters"] += 1
            else:
                buf.append(c)
        if buf:
            b.text("".join(buf), toc)


def read_package(path):
    raw = gzip.open(path, "rb").read().decode("utf-8")
    return Reader(raw)


# ---------------------------------------------------------------- glyph passages

def classify(piece):
    """'q' Quran-font glyph, 'open'/'close' AGA bracket, 'g' any other glyph, 't' text, 'r' reference."""
    if piece[0] != "g":
        return "t" if piece[0] == "t" else "r"
    key = piece[1]
    if Q.is_quran_font(piece[2]):
        return "q"
    if key.startswith("A:") and key[2:] in Q.AGA_BRACKETS:
        return "open" if Q.AGA_BRACKETS[key[2:]] == Q.OPEN else "close"
    return "g"


def is_glue(s):
    """Text that can sit inside a glyph quote: spaces, and stray punctuation standing for a glyph."""
    return all(c.isspace() or c in JUNK or unicodedata.category(c) == "Cf" for c in s)


def passages(pieces):
    """(start, end) piece-index windows holding one glyph quote each: Quran-font glyphs, with the
    brackets around them and any spaces or stray punctuation in between. A window must contain
    a letter, a phrase, a verse-end ornament or a bracket; lone spaces and marks are not quotes.

    Brackets do not end a quote: in several books the opening bracket is stored after the
    quote's first word and the closing one before its last word. Only a closing bracket followed
    (through spaces or stray punctuation) by an opening one separates two quotes."""
    kinds = [classify(p) for p in pieces]

    def bracket(x):
        if kinds[x] in ("open", "close"):
            return kinds[x]
        if kinds[x] == "q":
            return "open" if pieces[x][1] in Q.QURAN_OPEN else "close" if pieces[x][1] in Q.QURAN_CLOSE else None
        return None

    out = []
    i, n = 0, len(pieces)
    while i < n:
        if kinds[i] != "q":
            i += 1
            continue
        start = i
        j = i - 1          # an AGA opening bracket just before the first glyph belongs to the quote
        while j >= 0 and (kinds[j] == "open" or (kinds[j] == "t" and not pieces[j][1].strip())):
            if kinds[j] == "open":
                start = j
                break
            j -= 1
        end, k = i, i + 1
        closed = bracket(i) == "close"          # the last bracket seen was a closing one
        while k < n:
            br = bracket(k)
            if br == "open" and closed:
                break                           # «﴾ ﴿»: the next quote
            if kinds[k] in ("q", "open", "close"):
                end = k
                if br:
                    closed = br == "close"
                elif kinds[k] == "q":
                    closed = False
            elif kinds[k] != "t" or not is_glue(pieces[k][1]):
                break
            k += 1
        if any(pieces[x][0] == "g" and (Q.is_letter(pieces[x][1]) or pieces[x][1] in Q.PHRASE_GLYPHS or pieces[x][1] in Q.AYAH_PARTS
                                        or pieces[x][1] in Q.QURAN_OPEN or pieces[x][1] in Q.QURAN_CLOSE)
               for x in range(start, end + 1)):
            out.append((start, end))
        i = end + 1
    return out


def glyph_groups(pieces):
    """Stored glyph groups for quran_glyphs.tokens(): split at spaces; stray punctuation inside
    the quote becomes a wildcard glyph, '...' an ellipsis."""
    groups, cur = [], []
    for p in pieces:
        if p[0] == "g":
            if p[1] in Q.SPACE_GLYPHS:
                if cur:
                    groups.append(cur)
                    cur = []
            else:
                cur.append(p[1])
            continue
        s = p[1]
        for m in re.finditer(r"\.{2,}|…|\s+|.", s):
            t = m.group()
            if t.isspace() or unicodedata.category(t[0]) == "Cf":
                if cur:
                    groups.append(cur)
                    cur = []
            elif t.startswith("..") or t == "…":
                if cur:
                    groups.append(cur)
                    cur = []
                groups.append(["..."])
            else:
                cur.append(Q.WILDCARD)
    if cur:
        groups.append(cur)
    return groups


def wildcard_readings(groups, limit=81):
    """Other ways to group a quote's glyphs: a stray character inside a stored group often replaced
    a space as well as a glyph, so it may start or end a word. Yields regroupings, fewest splits first."""
    options = []
    for g in groups:
        inner = [i for i, k in enumerate(g) if k == Q.WILDCARD and 0 < i < len(g) - 1]
        opts = []
        for choice in itertools.product((None, "before", "after"), repeat=len(inner)):
            parts, cur = [], []
            for i, k in enumerate(g):
                c = choice[inner.index(i)] if i in inner else None
                if c == "before" and cur:
                    parts.append(cur)
                    cur = []
                cur.append(k)
                if c == "after":
                    parts.append(cur)
                    cur = []
            if cur:
                parts.append(cur)
            opts.append((sum(x is not None for x in choice), parts))
        options.append(opts)
    combos = []
    for combo in itertools.islice(itertools.product(*options), limit):
        combos.append((sum(n for n, _ in combo), [p for _, parts in combo for p in parts]))
    for n, regrouped in sorted(combos, key=lambda c: c[0]):
        if n:
            yield regrouped


def following_text(pieces, end, limit=80):
    s = []
    for p in pieces[end + 1:]:
        if p[0] == "t":
            s.append(p[1])
        elif p[0] == "g":
            s.append(" ")
        if sum(len(x) for x in s) > limit:
            break
    return "".join(s)


# ---------------------------------------------------------------- rendering

class Renderer:
    def __init__(self, quran, results, note_numbers):
        self.quran = quran
        self.results = results            # per quote, in order: (toks, ident) from the first pass
        self.next = 0
        self.note_numbers = note_numbers  # (kind, xml id) -> displayed number
        self.counts = collections.Counter()
        self.unknown = collections.Counter()

    def block(self, b, note_n=None):
        """Text of a block with spans: quran quotes, honorifics, other symbols, note references."""
        pieces = b.pieces
        windows = {s: e for s, e in passages(pieces)}
        out, spans = [], []
        pos = 0

        def emit(s, kind=None, **info):
            nonlocal pos
            # An honorific glued to a word in the source gets a space, as it is read as words
            # (recorded as "pad_before"/"pad_after", so the check knows the space is ours).
            if kind == "honorific" and s and out and out[-1] and out[-1][-1].isalnum():
                s = " " + s
                info["pad_before"] = True
            elif kind is None and s and s[0].isalnum() and spans and spans[-1]["kind"] == "honorific" and spans[-1]["end"] == pos:
                s = " " + s
                spans[-1]["pad_after"] = True
            if kind:
                spans.append(dict(kind=kind, start=pos + (len(s) - len(s.lstrip(" "))), end=pos + len(s), **info))
            out.append(s)
            pos += len(s)

        i = 0
        while i < len(pieces):
            if i in windows:
                e = windows[i]
                toks, ident = self.results[self.next]
                self.next += 1
                self.counts["quran_" + ident.status] += 1
                text = Q.render(self.quran, toks, ident)
                info = {"status": ident.status, "found": ident.note}
                if ident.cited:
                    info["cited"] = list(ident.cited)
                if ident.spans:
                    info["verses"] = [[list(self.quran.words[f][:3]), list(self.quran.words[l][:3])] for f, l, _ in ident.spans]
                if ident.status in ("unresolved", "ambiguous", "corrected", "wildcard"):
                    info["source_letters"] = " ".join(t[1] for t in toks if t[0] == "word")
                    info["glyphs"] = " / ".join(" ".join(g) for g in glyph_groups(pieces[i:e + 1]))
                if ident.vowel_note:
                    info["vowels"] = ident.vowel_note
                info["src"] = "".join(p[4] if p[0] == "g" else p[1] for p in pieces[i:e + 1] if p[0] in ("g", "t"))
                emit(text, "quran", **info)
                self.counts["glyphs_used"] += sum(1 for p in pieces[i:e + 1] if p[0] == "g")
                i = e + 1
                continue
            p = pieces[i]
            if p[0] == "g":
                self.counts["glyphs_used"] += 1
            if p[0] == "t":
                emit(p[1])
            elif p[0] == "ref":
                kind, xid, custom = p[1], p[2], p[3]
                n = self.note_numbers.get((kind, xid))
                emit("" if custom or n is None else str(n), "note", note=kind, n=n)
            elif p[0] == "mark":
                emit(str(note_n) if note_n is not None else "", "notemark")
            else:
                key, font, src = p[1], p[2], p[4]
                letters = Q.LETTER_FONTS.get(font, {})
                if key.startswith("A:") and key[2:] in Q.AGA:
                    emit(Q.AGA[key[2:]], "honorific", glyph=key, src=src)
                    self.counts["honorifics"] += 1
                elif key.startswith("L:") and key[2:] in letters:
                    emit(letters[key[2:]], "honorific", glyph=f"{font}:{key[2:]}", src=src)
                    self.counts["honorifics"] += 1
                elif key.startswith("A:") and key[2:] in Q.AGA_BRACKETS:
                    emit(Q.AGA_BRACKETS[key[2:]], "bracket", glyph=key, src=src)
                elif f"{font}:{key.split(':')[-1]}" in OTHER_GLYPHS:
                    emit(OTHER_GLYPHS[f"{font}:{key.split(':')[-1]}"], "symbol", glyph=f"{font}:{p[3]}", src=src)
                    self.counts["symbols"] += 1
                elif key in Q.SPACE_GLYPHS or key.endswith(":20"):
                    emit(" ")
                else:
                    self.unknown[f"{font}:{key[2:] if key.startswith('L:') else p[3]}"] += 1
                    spans.append(dict(kind="ornament", start=pos, end=pos, glyph=f"{font}:{p[3]}", src=src))
            i += 1
        return "".join(out), spans


# ---------------------------------------------------------------- per document

def quote_inputs(blocks):
    """Every glyph quote of a document, in output order: (stored groups, cited reference text)."""
    for b in blocks:
        for s, e in passages(b.pieces):
            yield glyph_groups(b.pieces[s:e + 1]), following_text(b.pieces, e)


def ordered_blocks(reader):
    """Main-story blocks, then footnotes in reference order (and any never referenced)."""
    numbers = {}
    notes = []
    for kind in ("footnote", "endnote"):
        n = 0
        for xid in reader.refs[kind]:
            if (kind, xid) in numbers or xid not in reader.notes[kind]:
                continue
            n += 1
            numbers[(kind, xid)] = n
            notes.append((kind, xid, n))
        for xid in reader.notes[kind]:
            if (kind, xid) not in numbers:
                notes.append((kind, xid, None))
    return numbers, notes


def all_blocks(reader, notes):
    yield from reader.blocks
    for kind, xid, n in notes:
        yield from reader.notes[kind][xid]


def first_pass(paths, quran):
    """Identify every quote; returns {file: [(toks, ident)]}."""
    results = {}
    for path in paths:
        reader = read_package(path)
        numbers, notes = ordered_blocks(reader)
        res = []
        for groups, after in quote_inputs(list(all_blocks(reader, notes))):
            ref = quran.parse_reference(after)
            toks = Q.tokens(groups)
            ident = Q.identify(quran, toks, ref)
            if ident.status in ("unresolved", "corrected") and any(Q.WILDCARD in g for g in groups):
                for regrouped in wildcard_readings(groups):
                    t2 = Q.tokens(regrouped)
                    i2 = Q.identify(quran, t2, ref)
                    if i2.status not in ("unresolved", "corrected"):
                        toks, ident = t2, i2
                        ident.note += ", a stray character also stood for a space"
                        break
            res.append((toks, ident))
        results[path.name] = res
        print(f"identified {len(res):5d} quotes  {path.name}", flush=True)
    return results


def settle(quran, results):
    """Choose among spans with the same letters but different vowels by how the same glyph words
    read in quotes identified without doubt; flag words whose glyphs read differently elsewhere."""
    def words(toks, chain):
        idx = [(i, s if i == f else 0) for f, l, s in chain for i in range(f, l + 1)]
        keys = [t[2] for t in toks if t[0] == "word"]
        return [(k, Q.trim_prefix(quran.words[i][3], s) if s else quran.words[i][3]) for k, (i, s) in zip(keys, idx)]

    def texts(ident):
        return {" ".join(w for f, l, s in chain for w in quran.text(f, l, s)) for chain in ident.candidates}

    book = collections.defaultdict(collections.Counter)
    for res in results.values():
        for toks, ident in res:
            if ident.candidates and len(texts(ident)) == 1 and ident.status in ("exact", "prefix") and ident.mode == "words":
                for k, w in words(toks, ident.spans):
                    book[k][w] += 1
    stats = collections.Counter()
    for res in results.values():
        for toks, ident in res:
            if not ident.candidates or ident.mode != "words":   # words not one to one with the span
                continue
            if len(texts(ident)) > 1:
                good = {}
                for chain in ident.candidates:
                    ws = words(toks, chain)
                    known = [(k, w) for k, w in ws if k in book]
                    if known and all(w in book[k] for k, w in known):
                        good.setdefault(" ".join(w for _, w in ws), chain)
                if len(good) == 1:
                    ident.spans = next(iter(good.values()))
                    ident.note += ", vowels from other quotes"
                    stats["settled_by_vowels"] += 1
                else:
                    ident.status = "ambiguous"
                    ident.note += f", {len(texts(ident))} readings, glyph vowels do not decide"
                    stats["ambiguous"] += 1
            # Vowel check: does a word's glyph spelling usually read as a different word elsewhere?
            odd = []
            for k, w in words(toks, ident.spans):
                c = book.get(k)
                if c and sum(c.values()) >= 3:
                    usual, n = c.most_common(1)[0]
                    if w != usual and c[w] < n:
                        odd.append(f"{w} (these glyphs read {usual} in {n} of {sum(c.values())} quotes)")
            if odd:
                ident.vowel_note = "; ".join(odd)
                stats["vowel_differences"] += 1
    return stats


def write_document(path, quran, res, out):
    reader = read_package(path)
    numbers, notes = ordered_blocks(reader)
    r = Renderer(quran, res, numbers)
    blocks = []
    for b in reader.blocks:
        text, spans = r.block(b)
        blocks.append({"kind": b.kind, "style": b.style, "outline": b.outline, "table": b.table, "text": text, "spans": spans})
    note_out = []
    for kind, xid, n in notes:
        paras = []
        spans_all = []
        for b in reader.notes[kind][xid]:
            text, spans = r.block(b, note_n=n)
            off = sum(len(p) + 1 for p in paras)
            spans_all += [dict(s, start=s["start"] + off, end=s["end"] + off) for s in spans]
            paras.append(text)
        note_out.append({"kind": kind, "n": n, "text": "\n".join(paras), "spans": spans_all})
    assert r.next == len(res), (path.name, r.next, len(res))
    name = path.name[: -len(".xml.gz")]
    doc = {"source": name, "quran_text": Q.TANZIL_NOTICE, "blocks": blocks, "notes": note_out,
           "counts": dict(reader.counts, **r.counts), "unknown_glyphs": dict(r.unknown)}
    (out / "json" / (name + ".json")).write_text(json.dumps(doc, ensure_ascii=False, indent=0), encoding="utf-8")
    main = [b["text"] for b in blocks if b["kind"] in ("p", "cell", "textbox")]
    (out / "text" / (name + ".txt")).write_text("\n".join(main) + "\n", encoding="utf-8")
    (out / "text" / (name + ".notes.txt")).write_text(
        "".join(f"{x['n'] if x['n'] is not None else '?'}\t{x['text'].replace(chr(10), ' ')}\n" for x in note_out), encoding="utf-8")
    return doc


# ---------------------------------------------------------------- report

REVIEW = {
    "unresolved": "Not identified (shown as " + Q.UNREADABLE + ")",
    "ambiguous": "Same letters in several places with different vowels; the glyphs do not decide",
    "corrected": "Corrected: the source's quote itself differs from the Quran; the cited verses' text is shown",
    "wildcard": "Repaired: stray characters stood in for glyphs; the words were identified around them",
    "vowels": "Glyph vowels differ from Tanzil's at the identified place",
    "reference": "The source's reference names other verses than the quoted ones",
}


def review_items(doc):
    for where, items in (("text", doc["blocks"]), ("note", doc["notes"])):
        for i, blk in enumerate(items):
            for s in blk["spans"]:
                if s["kind"] != "quran":
                    continue
                kinds = [k for k in ("unresolved", "ambiguous", "corrected", "wildcard") if s["status"] == k]
                if s.get("vowels"):
                    kinds.append("vowels")
                if s.get("cited") and s.get("found") == "anywhere":
                    kinds.append("reference")
                for k in kinds:
                    yield {"kind": k, "file": doc["source"], "where": where, "block": i, "status": s["status"],
                           "found": s.get("found"), "cited": s.get("cited"), "verses": s.get("verses"),
                           "vowels": s.get("vowels"), "glyphs": s.get("glyphs"), "source_letters": s.get("source_letters"),
                           "text": blk["text"][max(0, s["start"] - 30): s["end"] + 40]}


def write_report(docs, settle_stats, out):
    totals = collections.Counter()
    rows, review = [], []
    for d in docs:
        c = collections.Counter(d["counts"])
        totals.update(c)
        totals["unknown_glyphs"] += sum(d["unknown_glyphs"].values())
        review += list(review_items(d))
        q = {k[6:]: v for k, v in c.items() if k.startswith("quran_")}
        rows.append(f"| {d['source']} | {c['paragraphs_p']} | {c['paragraphs_cell']} | {c['paragraphs_note']} | "
                    f"{sum(q.values())} | {', '.join(f'{k} {v}' for k, v in sorted(q.items()) if k != 'exact')} | "
                    f"{c['honorifics']} | {sum(d['unknown_glyphs'].values()) or ''} |")
    (out / "report.json").write_text(json.dumps({"totals": totals, "settle": settle_stats, "review": review}, ensure_ascii=False, indent=1), encoding="utf-8")
    qtot = {k[6:]: v for k, v in totals.items() if k.startswith("quran_")}
    lines = [
        "# Extraction report", "",
        f"- Files: {len(docs)}",
        f"- Paragraphs: {totals['paragraphs_p']:,}; table-cell paragraphs: {totals['paragraphs_cell']:,}; "
        f"footnote paragraphs: {totals['paragraphs_note']:,}; text-box paragraphs: {totals['paragraphs_textbox']:,}; "
        f"table-of-contents lines: {totals['paragraphs_toc']:,}",
        f"- Quran quotes: {sum(qtot.values()):,} — " + ", ".join(f"{k}: {v:,}" for k, v in sorted(qtot.items(), key=lambda kv: -kv[1])),
        f"- Settled by glyph vowels: {settle_stats.get('settled_by_vowels', 0)}; still ambiguous: {settle_stats.get('ambiguous', 0)}; "
        f"quotes whose glyph vowels differ from Tanzil's at the identified place: {settle_stats.get('vowel_differences', 0)}",
        f"- Honorifics written out: {totals['honorifics']:,}; bullets/marks: {totals['symbols']:,}; ornaments dropped: {totals['unknown_glyphs']:,}",
        "", "## Per file", "",
        "| source | paragraphs | cells | note paragraphs | quotes | quotes not exact | honorifics | ornaments |",
        "|---|---|---|---|---|---|---|---|", *rows,
    ]
    for kind, title in REVIEW.items():
        items = [x for x in review if x["kind"] == kind]
        lines += ["", f"## {title} ({len(items)})", ""]
        for x in items:
            verses = "; ".join(f"{a[0]}:{a[1]}:{a[2]}-{b[0]}:{b[1]}:{b[2]}" for a, b in x["verses"] or [])
            extra = f" cited {x['cited'][0]}:{x['cited'][1]}-{x['cited'][2]}" if x["cited"] else ""
            extra += f" → {verses}" if verses else ""
            extra += f"; {x['vowels']}" if kind == "vowels" else ""
            extra += f"; {x['found']}; the source's letters: {x['source_letters']}" if kind in ("corrected", "unresolved") else ""
            lines.append(f"- {x['file']} ({x['where']} {x['block']}){extra} — {x['text']}")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word", required=True, type=pathlib.Path)
    ap.add_argument("--quran", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--only", help="substring filter on file names (quick runs; vowels are then settled from those files only)")
    args = ap.parse_args()
    for d in ("json", "text"):
        (args.out / d).mkdir(parents=True, exist_ok=True)
    quran = Q.Quran(args.quran)
    src = args.word / "final" if (args.word / "final").exists() else args.word / "xml"
    paths = sorted(p for p in src.glob("*.xml.gz") if not args.only or args.only in p.name)
    results = first_pass(paths, quran)
    settle_stats = settle(quran, results)
    print("settled:", dict(settle_stats), flush=True)
    docs = []
    for path in paths:
        docs.append(write_document(path, quran, results[path.name], args.out))
        print(f"written  {path.name}", flush=True)
    write_report(docs, settle_stats, args.out)


if __name__ == "__main__":
    main()

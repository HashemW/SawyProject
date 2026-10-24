"""Repair a copy of `التعددية السياسية.doc`, the one source Word will not open, so it can go
through word_export.ps1 like every other book. The original is never modified.

What is wrong: Word refuses the file ("Office has detected a problem with this file") and Google
Docs opens it as an empty page. Its container (CFB) and its text are intact. One entry of the
character-formatting bin table (PlcfBteChpx, in the 1Table stream) points at page 0, which is the
file header, instead of a formatting page (FKP). Every other entry, and every paragraph-formatting
entry, is valid. Drive keeps no older version of the file.

What the entry covered: 41 characters (byte offsets 370896-370978 of the WordDocument stream).
They are the start of a Quran quote typed in the Othmani glyph fonts, in a passage quoted from
al-Qurtubi: «لقوله تعالى: ﴿لَّا تَجِدُ قَوْمًا يُؤْمِنُونَ بِٱللَّهِ وَٱلْيَوْمِ ٱلْـَٔاخِرِ …﴾» (58:22).
The characters are a space, the opening bracket, the glyphs of the first five words and the first
glyph of the sixth, and the spaces between them. Lost with the entry is which font each character
is drawn in: for the glyphs, which of Othmani1-5 (the same code draws different shapes in
different fonts); for the bracket, the AGA Arabesque symbol behind Word's "(" placeholder.

How it is rebuilt: the glyph program that typed these quotes writes the same codes in the same
fonts for the same words. The same paragraph quotes the verse once before, a few lines up, and
that copy is intact: its glyphs have exactly the fonts written back here (GLYPH_FONTS; the script
checks this). The same words in 11 other books have the same fonts too, every one of them
(scripts/find_glyph_fonts.py lists them), and the rest of this quote, outside the damaged range,
matches them glyph for glyph. The
bracket is AGA Arabesque F029, as in the intact copy; it is the opening bracket this book uses
for its other glyph quotes too (counted when the script runs). The formatting itself (size, colour, bold, language) is copied
byte for byte from runs of the same paragraph: the body text before the quote, its closing
bracket, a space inside the quote and its glyphs in each Othmani font. Revision-save ids are
left out so the new page fits in 512 bytes; they do not change how text looks or reads.

The new formatting page is written into a page of the WordDocument stream that nothing uses (no
text piece, formatting page or section record lies in it), and the broken entry is pointed at it.
Nothing else changes: the script checks that the repaired copy has the same text, that every bin
table entry is valid, and that the rebuilt run reads back with the intended fonts.

Run: python -I -X utf8 scripts/repair_doc.py --src "data/raw/sawi_material/التعددية السياسية.doc" --out "data/work/repaired/التعددية السياسية.doc"
"""
import argparse
import hashlib
import pathlib
import struct

SOURCE_SHA256 = "3239f8ecf5cb9356ee8d393b06c95cbfed1a97ca86cdde294de48ee1ff4e8796"
BROKEN = (370896, 370978)              # WordDocument byte range of the bin table entry pointing at page 0

# Font (Othmani1-5) of each glyph of 58:22 «لَّا تَجِدُ قَوْمًا يُؤْمِنُونَ بِٱللَّهِ وَ…», as typed in the
# intact copy earlier in the same paragraph and in every other book with these words: 7 occurrences
# of the first five words in 6 books, 29 of the fifth and sixth (بِٱللَّهِ وَٱلْيَوْمِ) in 11, each with
# these fonts. Words separated by "|"; "code:font".
GLYPH_FONTS = ("9E:5 77:2 | DF:4 89:1 C5:4 67:1 72:5 42:1 | 24:1 59:4 42:2 F6:4 71:2 73:5 25:2 | "
               "9A:5 63:2 71:2 E3:4 5A:2 CF:4 42:2 F7:4 73:2 E3:4 83:2 | AB:5 21:1 24:5 24:1 CE:4 2F:1 | CF:4")
EARLIER_COPY = 370144                  # the verse's first glyph in the intact copy earlier in the paragraph

# Runs of the same paragraph whose formatting is copied (WordDocument byte offsets).
TEXT_RUN = 370582                      # the body text just before the quote
CLOSE_RUN = 371104                     # the quote's closing bracket, AGA Arabesque F028
SPACE_RUN = 371000                     # a space between two glyph words of the quote
QUOTE_RUNS = (370978, 371104)          # the quote's glyphs after the damaged range

SPRM_FTC0, SPRM_FTC2, SPRM_FTC_BI, SPRM_SYMBOL = 0x4A4F, 0x4A51, 0x4A5E, 0x6A09
RSID_SPRMS = {0x6815, 0x6816, 0x6817}  # sprmCRsidProp, sprmCRsidText, sprmCRsidRMDel
CLX, BTE_CHPX, BTE_PAPX, PLCF_SED, STTBF_FFN = 33, 12, 13, 6, 15   # FibRgFcLcb97 indexes


class Cfb:
    """Compound file (version 3, 512-byte sectors): streams by name, and where each stream byte
    sits in the file, so a copy can be patched in place."""

    def __init__(self, data):
        assert data[:8] == bytes.fromhex("D0CF11E0A1B11AE1"), "not a compound file"
        assert struct.unpack_from("<H", data, 30)[0] == 9, "expected 512-byte sectors"
        self.data = data
        n_fat, dir_start, _, self.cutoff, minifat_start = struct.unpack_from("<IIIII", data, 44)
        assert struct.unpack_from("<I", data, 72)[0] == 0, "DIFAT sectors are not supported"
        self.fat = []
        for s in [x for x in struct.unpack_from("<109I", data, 76) if x < 0xFFFFFFFA][:n_fat]:
            self.fat += struct.unpack_from("<128I", self.sector(s))
        directory = b"".join(self.sector(s) for s in self.chain(dir_start))
        self.entries = {}
        for i in range(len(directory) // 128):
            e = directory[i * 128:(i + 1) * 128]
            if e[66]:
                n = struct.unpack_from("<H", e, 64)[0]
                self.entries[e[:max(n - 2, 0)].decode("utf-16-le")] = struct.unpack_from("<IQ", e, 116)

    def sector(self, s):
        return self.data[512 + s * 512:512 + (s + 1) * 512]

    def chain(self, s):
        out = []
        while s < 0xFFFFFFFA:
            assert s not in out and s < len(self.fat), "broken sector chain"
            out.append(s)
            s = self.fat[s]
        return out

    def stream(self, name):
        start, size = self.entries[name]
        assert size >= self.cutoff, "small (mini-stream) streams are not needed here"
        return b"".join(self.sector(s) for s in self.chain(start))[:size]

    def file_offset(self, name, pos):
        return 512 + self.chain(self.entries[name][0])[pos // 512] * 512 + pos % 512


class Doc:
    """The parts of a Word 97-2003 document this repair needs: text pieces, the character and
    paragraph bin tables and their formatting pages, section records and the font table."""

    def __init__(self, data):
        self.cfb = Cfb(data)
        wd = self.wd = self.cfb.stream("WordDocument")
        assert struct.unpack_from("<H", wd, 0)[0] == 0xA5EC, "not a Word document"
        flags = struct.unpack_from("<H", wd, 10)[0]
        assert not flags & 0x0004 and not flags & 0x0100, "fast-saved or encrypted files are not supported"
        self.table_name = "1Table" if flags & 0x0200 else "0Table"
        self.table = self.cfb.stream(self.table_name)
        csw = struct.unpack_from("<H", wd, 32)[0]
        pos = 34 + csw * 2
        cslw = struct.unpack_from("<H", wd, pos)[0]
        self.ccp_text = struct.unpack_from("<i", wd, pos + 2 + 3 * 4)[0]
        pos += 2 + cslw * 4
        n = struct.unpack_from("<H", wd, pos)[0]
        self.fclcb = struct.unpack_from(f"<{n * 2}I", wd, pos + 2)
        self.fc_min = struct.unpack_from("<I", wd, 24)[0]

    def blob(self, k):
        fc, lcb = self.fclcb[2 * k], self.fclcb[2 * k + 1]
        return fc, self.table[fc:fc + lcb]

    def plc(self, k, cb_data):
        fc, b = self.blob(k)
        n = (len(b) - 4) // (4 + cb_data)
        assert (len(b) - 4) % (4 + cb_data) == 0, f"PLC {k} has an odd size"
        cps = list(struct.unpack_from(f"<{n + 1}I", b))
        data = [b[(n + 1) * 4 + j * cb_data:(n + 1) * 4 + (j + 1) * cb_data] for j in range(n)]
        return fc, cps, data, fc + (n + 1) * 4

    def pieces(self):
        """(cp start, cp end, byte offset, bytes per character) of every text piece."""
        _, clx = self.blob(CLX)
        i = 0
        while clx[i] == 1:
            i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
        assert clx[i] == 2
        lcb = struct.unpack_from("<I", clx, i + 1)[0]
        plc = clx[i + 5:i + 5 + lcb]
        n = (lcb - 4) // 12
        cps = struct.unpack_from(f"<{n + 1}I", plc)
        out = []
        for k in range(n):
            fc = struct.unpack_from("<I", plc, (n + 1) * 4 + k * 8 + 2)[0]
            if fc & 0x40000000:
                out.append((cps[k], cps[k + 1], (fc & 0x3FFFFFFF) // 2, 1))
            else:
                out.append((cps[k], cps[k + 1], fc, 2))
        return out

    def text(self):
        return "".join(self.wd[fc:fc + (b - a) * w].decode("cp1252" if w == 1 else "utf-16-le") for a, b, fc, w in self.pieces())

    def bins(self, k):
        """(fc start, fc end, page number) of every entry of a bin table, and where the page
        numbers are in the table stream."""
        _, fcs, pns, pn_pos = self.plc(k, 4)
        return [(fcs[j], fcs[j + 1], struct.unpack_from("<I", pns[j])[0] & 0x3FFFFF) for j in range(len(pns))], pn_pos

    def fkp_runs(self, pn, chpx=True):
        page = self.wd[pn * 512:(pn + 1) * 512]
        crun = page[511]
        rgfc = struct.unpack_from(f"<{crun + 1}I", page)
        runs = []
        for r in range(crun):
            off = page[(crun + 1) * 4 + r * (1 if chpx else 13)] * 2
            g = page[off + 1:off + 1 + page[off]] if off and chpx else b""
            runs.append((rgfc[r], rgfc[r + 1], g))
        return runs

    def bad_bins(self, k):
        """Bin table entries whose page is not a formatting page for exactly their range."""
        bad = []
        for fc0, fc1, pn in self.bins(k)[0]:
            page = self.wd[pn * 512:(pn + 1) * 512]
            if pn * 512 < self.fc_min or len(page) < 512:
                bad.append((fc0, fc1, pn))
                continue
            crun = page[511]
            rgfc = struct.unpack_from(f"<{crun + 1}I", page) if crun else ()
            if not crun or rgfc[0] != fc0 or rgfc[-1] != fc1 or list(rgfc) != sorted(rgfc):
                bad.append((fc0, fc1, pn))
        return bad

    def run_at(self, fc):
        for fc0, fc1, pn in self.bins(BTE_CHPX)[0]:
            if fc0 <= fc < fc1 and pn:
                return next(g for a, b, g in self.fkp_runs(pn) if a <= fc < b)
        raise KeyError(fc)

    def fonts(self):
        _, b = self.blob(STTBF_FFN)
        out, i = [], 4
        for _ in range(struct.unpack_from("<H", b)[0]):
            out.append(b[i + 1:i + 1 + b[i]][39:].decode("utf-16-le").split("\x00")[0])
            i += 1 + b[i]
        return out

    def used_pages(self):
        """WordDocument pages holding anything: header, text pieces, formatting pages, sections."""
        used = set(range((self.fc_min + 511) // 512))
        for a, b, fc, w in self.pieces():
            used.update(range(fc // 512, (fc + (b - a) * w - 1) // 512 + 1))
        for k in (BTE_CHPX, BTE_PAPX):
            used.update(pn for _, _, pn in self.bins(k)[0])
        _, _, seds, _ = self.plc(PLCF_SED, 12)
        for sed in seds:
            fc = struct.unpack_from("<i", sed, 2)[0]
            if fc >= 0:
                size = 2 + struct.unpack_from("<H", self.wd, fc)[0]
                used.update(range(fc // 512, (fc + size - 1) // 512 + 1))
        return used


def sprms(g):
    """(sprm, operand) pairs of a character grpprl (no table sprms with long operands occur here)."""
    out, i = [], 0
    while i + 2 <= len(g):
        sprm = struct.unpack_from("<H", g, i)[0]
        i += 2
        n = {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}.get(sprm >> 13) or g[i] + 1
        out.append((sprm, g[i:i + n]))
        i += n
    assert i == len(g), "grpprl does not parse"
    return out


def pack(pairs):
    return b"".join(struct.pack("<H", s) + op for s, op in pairs)


def font_of(g, fonts, sprm=SPRM_FTC0):
    return next((fonts[struct.unpack_from("<H", op)[0]] for s, op in sprms(g) if s == sprm), None)


def symbol_of(g, fonts):
    return next(((fonts[struct.unpack_from("<H", op)[0]], struct.unpack_from("<H", op, 2)[0]) for s, op in sprms(g) if s == SPRM_SYMBOL), None)


def build_fkp(runs):
    """A character formatting page: run boundaries, then one formatting record per distinct
    grpprl, packed from the end of the page."""
    page = bytearray(512)
    crun = len(runs)
    struct.pack_into(f"<{crun + 1}I", page, 0, *[a for a, _, _ in runs], runs[-1][1])
    top, offsets = 511, {}
    for g in dict.fromkeys(g for _, _, g in runs):
        top -= 1 + len(g)
        top -= top % 2
        page[top] = len(g)
        page[top + 1:top + 1 + len(g)] = g
        offsets[g] = top // 2
    assert top >= (crun + 1) * 4 + crun, f"formatting does not fit in one page ({crun} runs)"
    for r, (_, _, g) in enumerate(runs):
        page[(crun + 1) * 4 + r] = offsets[g]
    page[511] = crun
    return bytes(page)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()
    data = args.src.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SOURCE_SHA256, "not the file this repair was worked out for"
    doc = Doc(data)
    fonts = doc.fonts()

    bad = doc.bad_bins(BTE_CHPX)
    assert bad == [(*BROKEN, 0)], bad
    assert not doc.bad_bins(BTE_PAPX)
    damaged = doc.wd[BROKEN[0]:BROKEN[1]].decode("utf-16-le")
    words = [[(int(c, 16), int(f)) for c, f in (x.split(":") for x in w.split())] for w in GLYPH_FONTS.split("|")]
    expected = " ( " + " ".join("".join(chr(0xF000 + c) for c, _ in w) for w in words)
    assert damaged == expected, "the damaged range does not hold the expected characters"
    glyphs = expected[3:]
    assert doc.wd[EARLIER_COPY:EARLIER_COPY + 2 * len(glyphs)].decode("utf-16-le") == glyphs
    earlier = [font_of(doc.run_at(EARLIER_COPY + 2 * k), fonts) for k, ch in enumerate(glyphs) if ch != " "]
    assert earlier == [f"Othmani{f}" for w in words for _, f in w], "the intact copy has other fonts"
    assert symbol_of(doc.run_at(EARLIER_COPY - 4), fonts) == ("AGA Arabesque", 0xF029), "the intact copy has another bracket"

    # Formatting to copy, each checked to be what it is taken for.
    def bare(g):
        return pack([(s, op) for s, op in sprms(g) if s not in RSID_SPRMS])
    text_g, close_g, space_g = (bare(doc.run_at(fc)) for fc in (TEXT_RUN, CLOSE_RUN, SPACE_RUN))
    assert font_of(text_g, fonts, SPRM_FTC_BI) == "AF_Najed" and not symbol_of(text_g, fonts)
    assert symbol_of(close_g, fonts) == ("AGA Arabesque", 0xF028)
    assert font_of(space_g, fonts, SPRM_FTC_BI) == "Traditional Arabic" and font_of(space_g, fonts) is None
    open_g = pack([(s, struct.pack("<HH", struct.unpack_from("<H", op)[0], 0xF029) if s == SPRM_SYMBOL else op) for s, op in sprms(close_g)])
    othmani = {}
    for fc0, fc1, pn in doc.bins(BTE_CHPX)[0]:
        for a, b, g in (doc.fkp_runs(pn) if pn else []):
            f = font_of(g, fonts)
            if QUOTE_RUNS[0] <= a < QUOTE_RUNS[1] and f and f.startswith("Othmani"):
                othmani.setdefault(int(f[-1]), bare(g))
    assert sorted(othmani) == [1, 2, 3, 4, 5], sorted(othmani)

    # The book's own opening brackets for glyph quotes.
    symbols = {}
    for fc0, fc1, pn in doc.bins(BTE_CHPX)[0]:
        for a, b, g in (doc.fkp_runs(pn) if pn else []):
            s = symbol_of(g, fonts)
            if s and s[0] == "AGA Arabesque":
                symbols[s[1]] = symbols.get(s[1], 0) + 1
    print("AGA Arabesque symbols in the book:", {f"{k:04X}": v for k, v in sorted(symbols.items())})

    # One run per character, then merged.
    glyph_fonts = iter(f for w in words for _, f in w)
    chars = [text_g, open_g] + [space_g if ch == " " else othmani[next(glyph_fonts)] for ch in damaged[2:]]
    runs = []
    for i, g in enumerate(chars):
        fc = BROKEN[0] + 2 * i
        if runs and runs[-1][2] == g:
            runs[-1] = (runs[-1][0], fc + 2, g)
        else:
            runs.append((fc, fc + 2, g))
    page = build_fkp(runs)

    # The last unused page lies among the formatting pages (an orphan of an earlier save); the
    # other one sits between the header and the first text piece, so it is not taken.
    free = [p for p in range(len(doc.wd) // 512) if p not in doc.used_pages()]
    pn = free[-1]
    _, pn_pos = doc.bins(BTE_CHPX)
    entry = next(j for j, (a, _, _) in enumerate(doc.bins(BTE_CHPX)[0]) if a == BROKEN[0])
    out = bytearray(data)
    for k in range(512):
        out[doc.cfb.file_offset("WordDocument", pn * 512 + k)] = page[k]
    pos = pn_pos + entry * 4
    old = struct.unpack_from("<I", doc.table, pos)[0]
    new = struct.pack("<I", (old & ~0x3FFFFF) | pn)
    for k in range(4):
        out[doc.cfb.file_offset(doc.table_name, pos + k)] = new[k]

    fixed = Doc(bytes(out))
    assert not fixed.bad_bins(BTE_CHPX) and not fixed.bad_bins(BTE_PAPX)
    assert fixed.text() == doc.text(), "text changed"
    reread = [(a, b, font_of(g, fonts) or "", symbol_of(g, fonts)) for a, b, g in fixed.fkp_runs(pn)]
    glyphs = [f[-1] for a, b, f, _ in reread for _ in range((b - a) // 2) if f.startswith("Othmani")]
    assert glyphs == [str(f) for w in words for _, f in w]
    assert reread[1][3] == ("AGA Arabesque", 0xF029)
    changed = sum(1 for a, b in zip(data, out) if a != b)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bytes(out))
    print(f"bin table entry {entry} ({BROKEN[0]}-{BROKEN[1]}): page 0 -> page {pn} (unused; {len(free)} unused pages)")
    print(f"new formatting page: {len(runs)} runs; {changed} bytes of the file changed; text identical ({len(doc.text()):,} characters)")
    print(f"written {args.out} (sha256 {hashlib.sha256(out).hexdigest()})")


if __name__ == "__main__":
    main()

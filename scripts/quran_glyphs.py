"""Decode text typed in the sources' glyph fonts and identify Quran quotes in the Tanzil text.

Quran fonts. HQPB1-5 and Othmani1-5 (same codes) draw the Madinah mushaf piece by piece:
letter shapes in fonts 1-3, vowels and other marks in 4-5, and in font 2 also brackets,
verse-end ornaments and their digits. Each code is one 8-bit symbol character (Word stores it
as <w:sym> or as a private-use character U+F0xx). A word's glyphs are stored in visual
left-to-right order, i.e. reversed; words are stored in reading order, separated by spaces.

Quotes are not decoded into text glyph by glyph. Each word's letters are read from LETTERS
(below), the letter sequence is looked up in the Tanzil text, and the output is Tanzil's own
words for that span. LETTERS was read off the rendered fonts and then checked by aligning
11,552 referenced quotes with Tanzil: 11,500 decode to exactly the cited letters, and every
label agrees with at least 97% of its aligned occurrences. Labels are skeleton letters, the
same normalization as skeleton(): no marks, alef forms -> ا, ؤ -> و, ئ/ى -> ي, ة -> ه, ء dropped.

Honorifics. AGA Arabesque (honorifics and ornate brackets) and CTraditional Arabic (honorifics
drawn on ordinary characters) are not installed on any of our machines. Each symbol's meaning
was taken from sentences that occur twice in the sources, once with the symbol and once with
the words typed out (e.g. 2,955 times «رضي الله عنه» for `t`); see docs/extraction.md.
"""
import collections
import difflib
import re
import unicodedata

OPEN, CLOSE = chr(0xFD3F), chr(0xFD3E)   # ﴿ ﴾ as they open and close a quote in Arabic text
END_OF_AYAH = chr(0x06DD)                 # followed by the verse number in Arabic-Indic digits
ARABIC_DIGITS = str.maketrans("0123456789", "".join(chr(0x0660 + d) for d in range(10)))
TANZIL_NOTICE = ("Quran text: Tanzil Quran Text (Uthmani, version 1.1), Copyright (C) 2007-2026 Tanzil Project, "
                 "Creative Commons Attribution 3.0; verbatim copies only; https://tanzil.net")
BASMALA = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"

# ---------------------------------------------------------------- glyph tables

# "<font> <code or range> <label>", label "-" = draws no letter of its own (e.g. hamza on a kashida).
_LETTERS = """
1 21 لله|1 23-2E ا|1 2F-3E ب|1 3F-4E ت|1 4F-5E ث|1 5F-6C ج|1 6D-79 ح|1 7A-88 خ|1 89-8A د|1 8B-8C ذ
1 8D-92 ر|1 93-98 ز|1 99-A8 س|1 A9-B8 ش|1 B9-C9 ص|1 CA-DA ض|1 DB-DE ط|1 DF-E2 ظ|1 E3-ED ع|1 EE-F8 غ
1 F9-FF ف|2 21-24 ف|2 25-2D ق|2 2E-38 ك|2 39-41 ل|2 42-51 م|2 52-63 ن|2 64-70 ه|2 71-76 و|2 77-82 لا
2 83-AA ي|2 AB -|2 AC-B9 ي|2 C6 ن|2 D3 ي|2 D4 خ|2 D5 ح|2 D6 ج|2 D7-D8 ي|2 D9-DA ج|2 DB ح|2 DC خ
2 DD-DE ص|2 DF-E0 ض|2 E4 -|2 E6-E7 ي|2 E8 ن|2 E9 ث|2 EA ت|2 EB ب|2 EC-EF ي|2 F0 ن|2 F1 ث|2 F2 ت
2 F3 ب|2 F4-F5 ي|2 F6 ن|2 F7 ث|2 F8 ت|2 F9 ب|2 FA-FB ن|2 FC ي|2 FF م|3 21 ل|3 23 ل|3 24 د|3 25 ذ
3 26-27 ه|3 28 ب|3 29 ت|3 2A ث|3 2B ن|3 2C-2E ي|3 2F م|3 30 ه|3 31-3E ي|3 3F-40 د|3 41 ر|3 47 -
3 4A س|3 4B ش|3 4C ص|3 4D ض|3 4E س|3 4F ش|3 50 ي|3 51 ل|3 52 م|3 53 ه|3 54 لله|3 55 ب|3 56 ت
3 57 ث|3 58-59 ق|3 5A-5B س|3 5C-5D ش|3 5E ل|3 5F-60 ي|3 62 ي|3 6C ك|3 6E ت|3 6F ث|3 70 ن|3 71-73 ي
3 76 ب|3 77 ت|3 78 ث|3 79 ن|3 7A-7C ي|3 81-82 ك|3 83 ع|3 85 ه|3 86-88 ي|3 89 ه|3 8A س|3 8B ش
3 8C ص|3 8D ض|3 8E س|3 8F ش|3 90 ص|3 91 ض|3 92 ف|3 93 ر|3 94 ع
"""
LETTERS = {}
for _item in _LETTERS.replace("\n", "|").split("|"):
    if _item.strip():
        _font, _rng, _lab = _item.split()
        _a, _, _b = _rng.partition("-")
        for _c in range(int(_a, 16), int(_b or _a, 16) + 1):
            LETTERS[f"{_font}:{_c:02X}"] = "" if _lab == "-" else _lab

QURAN_OPEN = {"2:E2", "A:5D", "A:7D", "A:29"}
QURAN_CLOSE = {"2:E1", "A:5B", "A:7B", "A:28"}
AYAH_LEFT, AYAH_RIGHT = "2:C7", "2:C8"     # the verse-end ornament's two halves, digits in between
AYAH_PARTS = {f"2:{c:02X}" for c in range(0xC7, 0xD3)}
DIGIT = {f"2:{0xC9 + d:02X}": str(d) for d in range(10)}
# Whole-phrase glyphs in font 3, keyed by their stored (visual) order.
PHRASES = {("3:64",): "قال تعالى:", ("3:68", "3:67"): "صدق الله العظيم", ("3:69", "3:6A", "3:6B"): BASMALA}
PHRASE_GLYPHS = {g for k in PHRASES for g in k}
SPACE_GLYPHS = {f"{f}:20" for f in "12345A"}
WILDCARD = "?"                             # a stray character standing where a glyph should be

AGA = {
    "55": "عز وجل", "59": "جل جلاله", "49": "سبحانه وتعالى",
    "72": "صلى الله عليه وسلم", "65": "صلى الله عليه وسلم",
    "74": "رضي الله عنه", "79": "رضي الله عنهم", "75": "عليه السلام",
}
AGA_BRACKETS = {"5D": OPEN, "7D": OPEN, "29": OPEN, "5B": CLOSE, "7B": CLOSE, "28": CLOSE}

# Ordinary (non-symbol) fonts that draw an honorific in place of a character. CTraditional Arabic
# is used for nothing else in the sources. ب ل : were confirmed by sentences that occur twice
# (400, 223 and 754 times); ت by all 16 contexts (Companions, and «… ت وأرضاه»); ن and س
# from their only contexts (1 and 2). Its ﻷ (6 times, always after «الله») is not known.
LETTER_FONTS = {
    "CTraditional Arabic": {"ب": "رضي الله عنهما", "ل": "رضي الله عنها", ":": "رحمه الله",
                            "ت": "رضي الله عنه", "س": "رضي الله عنه", "ن": "رضي الله عنهم"},
}


def glyph_key(font, code):
    """'HQPB2'/'Othmani2', 'F0E1' -> '2:E1'; AGA Arabesque -> 'A:xx'; other fonts keep their name."""
    m = re.match(r"(?:HQPB|Othmani)(\d)$", font or "")
    tail = f"{int(code, 16) & 0xFF:02X}"
    if m:
        return f"{m.group(1)}:{tail}"
    if font == "AGA Arabesque":
        return f"A:{tail}"
    return f"{font}:{tail}"


def is_quran_font(font):
    return bool(re.match(r"(?:HQPB|Othmani)\d$", font or ""))


def is_letter(key):
    return key in LETTERS or (key[:2] in ("1:", "2:", "3:") and key not in AYAH_PARTS and key not in QURAN_OPEN
                              and key not in QURAN_CLOSE and key not in PHRASE_GLYPHS and key not in SPACE_GLYPHS
                              and not ("2:BA" <= key <= "2:C5") and key not in ("1:22", "2:E3", "2:E5", "3:22"))


# ---------------------------------------------------------------- Tanzil

SKELETON = str.maketrans({"ٱ": "ا", "أ": "ا", "إ": "ا", "آ": "ا", "ؤ": "و", "ئ": "ي", "ى": "ي", "ة": "ه", "ء": None,
                          chr(0x0640): None, chr(0x06E5): None, chr(0x06E6): None})


def skeleton(word):
    """Letters only, normalized; Tanzil words and decoded glyph words meet here."""
    return "".join(c for c in word if unicodedata.category(c) not in ("Mn", "Me", "So", "Cf")).translate(SKELETON)


SURAS = """الفاتحة البقرة آل_عمران النساء المائدة الأنعام الأعراف الأنفال التوبة يونس هود يوسف الرعد إبراهيم
الحجر النحل الإسراء الكهف مريم طه الأنبياء الحج المؤمنون النور الفرقان الشعراء النمل القصص العنكبوت الروم
لقمان السجدة الأحزاب سبأ فاطر يس الصافات ص الزمر غافر فصلت الشورى الزخرف الدخان الجاثية الأحقاف محمد الفتح
الحجرات ق الذاريات الطور النجم القمر الرحمن الواقعة الحديد المجادلة الحشر الممتحنة الصف الجمعة المنافقون
التغابن الطلاق التحريم الملك القلم الحاقة المعارج نوح الجن المزمل المدثر القيامة الإنسان المرسلات النبأ
النازعات عبس التكوير الانفطار المطففين الانشقاق البروج الطارق الأعلى الغاشية الفجر البلد الشمس الليل الضحى
الشرح التين العلق القدر البينة الزلزلة العاديات القارعة التكاثر العصر الهمزة الفيل قريش الماعون الكوثر
الكافرون النصر المسد الإخلاص الفلق الناس""".split()
SURA_ALIASES = {"براءة": 9, "بني_إسرائيل": 17, "المؤمن": 40, "حم_السجدة": 41, "القتال": 47, "الدهر": 76,
                "الانشراح": 94, "اللهب": 111, "تبت": 111, "الزلزال": 99, "النبإ": 78, "عم": 78}


def _name_key(s):
    s = re.sub("[^ء-ي_ ]", "", s).replace(" ", "").replace("_", "")
    return s.translate(str.maketrans("أإآٱىة", "اااايه"))


def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


SURA_NUMBER = {}
for _i, _n in enumerate(SURAS, 1):
    SURA_NUMBER[_name_key(_n)] = _i
for _n, _i in SURA_ALIASES.items():
    SURA_NUMBER[_name_key(_n)] = _i
for _k, _i in list(SURA_NUMBER.items()):
    if _k.startswith("ال") and len(_k) > 3:
        SURA_NUMBER.setdefault(_k[2:], _i)


def sura_number(name):
    k = re.sub("^سوره", "", _name_key(name))
    if k in SURA_NUMBER:
        return SURA_NUMBER[k]
    if k[:1] in ("ب", "ل") and k[1:] in SURA_NUMBER:      # "بالنحل"
        return SURA_NUMBER[k[1:]]
    close = {SURA_NUMBER[n] for n in SURA_NUMBER if len(n) >= 4 and _lev(k, n) <= 1}
    return close.pop() if len(close) == 1 else None


_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NUM = r"([\d٠-٩۰-۹]+)"
REFERENCE = re.compile(r"^[\s.،:\-]*(?:الآية|الآيات|الاية|الايات)?\s*[\[(]\s*(?:سورة\s*)?([^\]):\d٠-٩]{1,25}?)\s*[:،,/]?\s*"
                       r"(?:الآية|آية|الآيات|آيات)?\s*" + _NUM + r"\s*(?:[-–—،,و]\s*" + _NUM + ")?")


class Quran:
    """Tanzil's Uthmani text indexed by word skeleton."""

    def __init__(self, path):
        verses = {}
        for line in open(path, encoding="utf-8"):
            p = line.rstrip("\n").split("|")
            if len(p) == 3 and p[0].isdigit():
                verses[(int(p[0]), int(p[1]))] = p[2]
        for (s, a), t in list(verses.items()):        # Tanzil prefixes verse 1 of each sura with the basmala
            if a == 1 and s not in (1, 9) and t.startswith(BASMALA + " "):
                verses[(s, a)] = t[len(BASMALA) + 1:]
        self.verse_count = collections.Counter(s for s, a in verses)
        self.words = []          # (sura, ayah, n, text): every token with letters
        self.after = []          # non-word tokens (pause marks, ۩) right after each word
        self.before = {}         # word index -> non-word tokens before it (۞ at the start of a verse)
        self.verse_words = {}    # (sura, ayah) -> (first, last) word index
        for (s, a) in sorted(verses):
            first = len(self.words)
            pending = []
            for tok in verses[(s, a)].split(" "):
                if skeleton(tok):
                    if pending:
                        self.before[len(self.words)] = pending
                        pending = []
                    self.words.append((s, a, len(self.words) - first + 1, tok))
                    self.after.append([])
                elif len(self.words) > first:
                    self.after[-1].append(tok)
                else:
                    pending.append(tok)
            self.verse_words[(s, a)] = (first, len(self.words) - 1)
        skel = [skeleton(w[3]) for w in self.words]
        self.stream = "|" + "|".join(skel) + "|"
        self.sep = []                                  # offset of the "|" before each word
        pos = 0
        for k in skel:
            self.sep.append(pos)
            pos += len(k) + 1
        self.sep_index = {p: i for i, p in enumerate(self.sep)}

    def verses(self, sura, a, b):
        a, b = max(1, a), min(self.verse_count[sura], b)
        return self.verse_words[(sura, a)][0], self.verse_words[(sura, b)][1]

    def parse_reference(self, text):
        """[البقرة: 61], ( آل عمران :187 ), الآية [التوبة: 6], [البقرة: 159-160] -> (sura, first, last)."""
        m = REFERENCE.match(text.replace("\xa0", " "))
        if not m:
            return None
        s = sura_number(m.group(1))
        if not s:
            return None
        a = int(m.group(2).translate(_DIGITS))
        b = int(m.group(3).translate(_DIGITS)) if m.group(3) else a
        if not 1 <= a <= self.verse_count[s]:
            return None
        return (s, a, min(max(a, b), self.verse_count[s]))

    # -------------------------------------------------- search

    def find(self, part, lo=0, hi=None, skip_prefix=False, flexible=False):
        """Word spans (first, last, skipped_letters) whose letters match `part`: a list of words,
        each a list of per-glyph regex pieces. flexible: the quote's word boundaries need not be
        Tanzil's (the glyph program joins words such as بعدما that Tanzil writes apart)."""
        hi = len(self.words) - 1 if hi is None else hi
        start, end = self.sep[lo], (self.sep[hi + 1] if hi + 1 < len(self.sep) else len(self.stream) - 1) + 1
        if flexible:
            body = r"\|?".join(p for w in part for p in w)
        else:
            body = r"\|".join("".join(w) for w in part)
        pat = r"\|" + ("([^|]{1,2})" if skip_prefix else "()") + body + r"\|"
        out = []
        for m in re.finditer("(?=(" + pat + "))", self.stream[start:end]):
            p = start + m.start()
            first = self.sep_index.get(p)
            if first is None:
                continue
            last_sep = p + len(m.group(1)) - 1
            last = self.sep_index.get(last_sep)
            last = (last - 1) if last is not None else len(self.words) - 1
            if first <= last:
                out.append((first, last, len(m.group(2))))
        return out

    def text(self, first, last, skip=0):
        return [self.words[i][3] if (i > first or not skip) else trim_prefix(self.words[i][3], skip)
                for i in range(first, last + 1)]


def trim_prefix(word, letters):
    """Drop the first `letters` skeleton letters of a Tanzil word with their marks: أَوَلَمْ, 1 -> وَلَمْ."""
    n = 0
    for i, c in enumerate(word):
        if skeleton(c):
            if n == letters:
                return word[i:]
            n += 1
    return ""


# ---------------------------------------------------------------- passages

# Two glyphs have a second use, seen in quotes that otherwise match exactly: 1:21 (normally the
# لله ligature) also draws a single lam, and 3:39 (normally a final ىٰ) also a bare connecting stroke.
ALTERNATIVES = {"1:21": "(?:لله|ل)", "3:39": "(?:ي)?"}


def _glyph_pattern(key):
    """Regex for the letters one glyph stands for; unread and unlabelled glyphs match 0-3 letters."""
    if key in ALTERNATIVES:
        return ALTERNATIVES[key]
    if key == WILDCARD or key not in LETTERS:
        return "[^|]{0,3}"
    return re.escape(LETTERS[key])


def tokens(groups):
    """Stored glyph groups (lists of keys, split at spaces) -> tokens in reading order.

    ('open'|'close',) ('word', skeleton, keys, letter patterns) ('mark', keys) ('ayah', number|None)
    ('phrase', text) ('ellipsis',)
    """
    out = []
    for grp in groups:
        if grp == ["..."]:
            out.append(("ellipsis",))
            continue
        # Split the stored group at brackets, phrases and verse-end ornaments, then reverse:
        # within one group the stored order is visual (left to right).
        subs, cur, i = [], [], 0
        while i < len(grp):
            g = grp[i]
            if g in AYAH_PARTS:
                # One ornament: AYAH_LEFT, the digits in their natural order, AYAH_RIGHT.
                if cur:
                    subs.append(("glyphs", cur))
                    cur = []
                j = i
                while j < len(grp) and grp[j] in AYAH_PARTS:
                    j += 1
                    if grp[j - 1] == AYAH_RIGHT:
                        break
                digits = "".join(DIGIT.get(x, "") for x in grp[i:j])
                subs.append(("ayah", int(digits) if digits else None))
                i = j
                continue
            if g in QURAN_OPEN or g in QURAN_CLOSE:
                if cur:
                    subs.append(("glyphs", cur))
                    cur = []
                subs.append(("open",) if g in QURAN_OPEN else ("close",))
            else:
                cur.append(g)
            i += 1
        if cur:
            subs.append(("glyphs", cur))
        for sub in reversed(subs):
            if sub[0] != "glyphs":
                out.append(sub)
                continue
            keys = tuple(sub[1])
            if keys in PHRASES:
                out.append(("phrase", PHRASES[keys]))
            elif any(is_letter(k) or k == WILDCARD for k in keys):
                letters = [k for k in reversed(keys) if k == WILDCARD or is_letter(k)]
                word = "".join(WILDCARD if k == WILDCARD else LETTERS.get(k, WILDCARD) for k in letters)
                out.append(("word", word, keys, [p for p in map(_glyph_pattern, letters) if p]))
            elif any(k in PHRASE_GLYPHS for k in keys):
                out.append(("phrase", None, keys))
            else:
                out.append(("mark", keys))
    return out


class Identification:
    """Where a glyph quote sits in the Quran and the words it shows."""

    def __init__(self, status, spans=(), note=""):
        self.status = status          # exact | prefix | wildcard | corrected | ambiguous | unresolved | phrase | empty
        self.spans = list(spans)      # [(first, last, skip)] one per part (parts are separated by "...")
        self.note = note              # where it was found (cited | near | anywhere) and how
        self.mode = "words"           # "words": the quote's words map one to one onto the span's
        self.candidates = []          # all placements with the same letters
        self.cited = None             # the reference written after the quote, if any
        self.vowel_note = None


def identify(quran, toks, ref):
    """Find the passage's words in Tanzil: the cited verses first, then the whole Quran."""
    ident = _identify(quran, toks, ref)
    ident.cited = ref
    return ident


def _identify(quran, toks, ref):
    parts, cur = [], []
    for t in toks:
        if t[0] == "word":
            cur.append(t)
        elif t[0] == "ellipsis" and cur:
            parts.append(cur)
            cur = []
    if cur:
        parts.append(cur)
    if not parts:
        return Identification("phrase" if any(t[0] == "phrase" for t in toks) else "empty")
    markers = _markers(toks)
    wild = any(WILDCARD in t[1] for p in parts for t in p)
    nwords = sum(len(p) for p in parts)
    pats = [[t[3] for t in p] for p in parts]
    # Search order: the cited verses, then 3 verses either side, then the whole Quran; at each
    # step whole words first, then allowing the first word to drop a 1-2 letter prefix (و, ف, أ...).
    # A quote with unreadable glyphs is only placed near its reference, or anywhere if it is long.
    regions = []
    if ref:
        regions += [(quran.verses(ref[0], ref[1], ref[2]), "cited"), (quran.verses(ref[0], ref[1] - 3, ref[2] + 3), "near")]
    if not wild or nwords >= 4:
        regions.append(((0, len(quran.words) - 1), "anywhere"))

    def search(parts_pats, flexible=False, regions=regions):
        for (lo, hi), where in regions:
            for skip_prefix in (False, True):
                found = _find_parts(quran, parts_pats, lo, hi, skip_prefix, flexible)
                if not flexible:
                    found = [f for f in found if _markers_fit(quran, f, markers)]
                if (wild or flexible) and where == "anywhere" and len({_text(quran, f) for f in found}) > 1:
                    found = []
                if found:
                    return found, where
        return None

    def result(found, where, mode):
        status = "wildcard" if wild else ("prefix" if any(s for _, _, s in found[0]) else "exact")
        ident = Identification(status, found[0], note=where if mode == "words" else f"{where}, {mode}")
        ident.candidates = found
        ident.mode = mode
        return ident

    r = search(pats)
    if r:
        return result(*r, "words")
    # The same letters, read with the glyph program's word boundaries ignored.
    r = search(pats, flexible=True)
    if r:
        return result(*r, "word boundaries differ from Tanzil's")
    # Words stored in visual order (a quote in a left-to-right paragraph).
    r = search([[w for w in reversed(p)] for p in reversed(pats)], flexible=True)
    if r:
        return result(*r, "words stored in reverse order")
    # Two words typed without a space: one stored group holds both, so after reversal they come
    # out swapped. Try every rotation of each long word, near the reference (or anywhere if none).
    near = regions[:2] if ref else regions
    for pi, part in enumerate(pats):
        for wi, word in enumerate(part):
            if len(word) < 4:
                continue
            for k in range(1, len(word)):
                trial = [list(p) for p in pats]
                trial[pi][wi] = word[k:] + word[:k]
                r = search(trial, flexible=True, regions=near)
                if r:
                    return result(*r, "words written without a space")
    # Neighbouring words stored in swapped pairs (short runs reordered by the bidi algorithm).
    flat = [w for p in pats for w in p]
    if len(pats) == 1 and 3 <= len(flat) <= 8:
        for swaps in _pair_swaps(len(flat)):
            trial = list(flat)
            for i in swaps:
                trial[i], trial[i + 1] = trial[i + 1], trial[i]
            r = search([trial], flexible=True)
            if r:
                return result(*r, "neighbouring words stored swapped")
    # The source's quote itself differs from the Quran (missing or extra letters or words):
    # placed only within the cited verses, output as Tanzil's text, and flagged.
    approx = _approximate(quran, parts, ref)
    if approx:
        ident = Identification("corrected", [approx[0]], note="cited, " + approx[1])
        ident.candidates = [[approx[0]]]
        ident.mode = "corrected"
        return ident
    return Identification("unresolved", note="no span of the Quran has these letters")


def _pair_swaps(n):
    """Every non-empty set of non-overlapping neighbour swaps (i, i+1) among n words, fewest first."""
    out = [[]]
    for i in range(n - 1):
        out += [s + [i] for s in out if not s or s[-1] < i - 1]
    return sorted((s for s in out if s), key=len)


def _text(quran, chain):
    return " ".join(w for f, l, s in chain for w in quran.text(f, l, s))


def _find_parts(quran, parts, lo, hi, skip_prefix, flexible=False):
    """All placements of the parts in order (each later part after the previous, within 10 verses)."""
    out = []
    for first in quran.find(parts[0], lo, hi, skip_prefix, flexible):
        chain = [first]
        for part in parts[1:]:
            prev_end = chain[-1][1]
            if prev_end + 1 >= len(quran.words):
                break
            s, a = quran.words[prev_end][:2]
            nxt = quran.find(part, prev_end + 1, quran.verses(s, a, a + 10)[1], skip_prefix, flexible)
            if not nxt:
                break
            chain.append(nxt[0])
        if len(chain) == len(parts):
            out.append(chain)
    return out


def _approximate(quran, parts, ref):
    """Best span of the cited verses for a quote whose own letters differ from the Quran:
    at least 3 and 60% of its words must match, in order. Returns ((first, last, 0), difference)."""
    src = [t[1] for p in parts for t in p]
    if not ref or len(src) < 3:
        return None
    lo, hi = quran.verses(ref[0], ref[1] - 1, ref[2] + 1)
    region = [skeleton(quran.words[i][3]) for i in range(lo, hi + 1)]
    sm = difflib.SequenceMatcher(None, src, region, autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    matched = sum(b.size for b in blocks)
    if not blocks or matched < max(3, 0.6 * len(src)):
        return None
    first = max(0, blocks[0].b - blocks[0].a)
    last = min(len(region) - 1, blocks[-1].b + blocks[-1].size - 1 + (len(src) - blocks[-1].a - blocks[-1].size))
    if last - first + 1 > len(src) + 5:
        return None
    diff = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, src, region[first:last + 1], autojunk=False).get_opcodes():
        if tag != "equal":
            diff.append(f"source «{' '.join(src[i1:i2])}» / Quran «{' '.join(quran.words[lo + first + j][3] for j in range(j1, j2))}»")
    return (lo + first, lo + last, 0), "the quote differs from the Quran: " + "; ".join(diff)


def _markers(toks):
    """Verse-end ornaments as (words before it, number, trailing?)."""
    out, n = [], 0
    words_total = sum(1 for t in toks if t[0] == "word")
    for t in toks:
        if t[0] == "word":
            n += 1
        elif t[0] == "ayah":
            out.append((n, t[1], n == words_total))
    return out


def _markers_fit(quran, chain, markers):
    """Inner ornaments must sit at the end of their verse; a trailing one only names the last word's verse."""
    if not markers:
        return True
    idx = [i for f, l, _ in chain for i in range(f, l + 1)]
    for n, num, trailing in markers:
        if n == 0 or n > len(idx):
            continue
        w = quran.words[idx[n - 1]]
        if num is not None and w[1] != num:
            return False
        if not trailing and quran.verse_words[(w[0], w[1])][1] != idx[n - 1]:
            return False
    return True


UNREADABLE = chr(0x27E6) + "?" + chr(0x27E7)   # stands for quoted words that could not be identified


def render(quran, toks, ident):
    """The passage as text: the source's brackets, phrases and verse-end ornaments around Tanzil's
    words for the identified span; pause marks where the source shows them."""
    if ident.mode != "words" and ident.spans:
        return _render_span(quran, toks, ident)
    idx = [(i, skip if i == f else 0) for f, l, skip in ident.spans for i in range(f, l + 1)]
    out = []
    n = 0
    marked = set()            # word boundaries whose pause marks are already written
    for t in toks:
        kind = t[0]
        if kind in ("open", "close"):
            continue          # brackets go around the whole quote (see _brackets)
        elif kind == "ellipsis":
            out.append("...")
        elif kind == "phrase" and t[1]:
            out.append(t[1])
        elif kind == "word":
            if idx:
                i, skip = idx[n]
                if n == 0 and quran.before.get(i) and _has_mark_before(toks):
                    out.extend(quran.before[i])
                out.append(trim_prefix(quran.words[i][3], skip) if skip else quran.words[i][3])
            elif not out or out[-1] != UNREADABLE:
                out.append(UNREADABLE)
            n += 1
        elif kind == "mark" and idx and 0 < n <= len(idx) and n not in marked:
            marked.add(n)
            out.extend(quran.after[idx[n - 1][0]])
        elif kind == "ayah":
            num = t[1] if t[1] is not None else (quran.words[idx[n - 1][0]][1] if idx and n else None)
            out.append(END_OF_AYAH + str(num).translate(ARABIC_DIGITS) if num else END_OF_AYAH)
    return _brackets(toks, " ".join(x for x in out if x))


def _brackets(toks, body):
    """The source's brackets around the quote. They are put at its edges: some books store the
    opening bracket after the first word and the closing one before the last."""
    kinds = {t[0] for t in toks}
    return (OPEN if "open" in kinds else "") + body + (CLOSE if "close" in kinds else "")


def _render_span(quran, toks, ident):
    """For quotes whose words do not map one to one onto Tanzil's: the span's words with Tanzil's
    pause marks, verse-end ornaments at verse ends if the source shows any, and the source's brackets."""
    kinds = [t[0] for t in toks]
    words_at = [i for i, k in enumerate(kinds) if k == "word"]
    ornaments = "ayah" in kinds                       # the source marks verse ends
    trailing = "ayah" in kinds[words_at[-1]:]         # ... and closes the quote with one
    out = []
    for pi, (f, l, skip) in enumerate(ident.spans):
        if pi:
            out.append("...")
        last_part = pi == len(ident.spans) - 1
        for i in range(f, l + 1):
            out.append(trim_prefix(quran.words[i][3], skip) if i == f and skip else quran.words[i][3])
            if i < l:
                out.extend(quran.after[i])
            verse_end = quran.verse_words[quran.words[i][:2]][1] == i
            if ornaments and ((verse_end and i < l) or (i == l and trailing and last_part)):
                out.append(END_OF_AYAH + str(quran.words[i][1]).translate(ARABIC_DIGITS))
    return _brackets(toks, " ".join(x for x in out if x))


def _has_mark_before(toks):
    for t in toks:
        if t[0] == "word":
            return False
        if t[0] == "mark":
            return True
    return False

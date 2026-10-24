"""List every place a run of glyph words occurs in the books, with the font of each glyph there.

The glyph program that typed the Quran quotes writes the same codes in the same fonts for the same
words, so where a source lost the fonts of some glyphs (see repair_doc.py), the other occurrences
show which fonts they were. Words are given as glyph codes, the code's last two hex digits, comma
separated, words separated by "_" (codes in Othmani fonts are private-use characters U+F0xx).

Run: python -I -X utf8 scripts/find_glyph_fonts.py --word data/work/word --skip التعددية "AB,21,24,24,CE,2F_CF,51,F6,71,75,8B,F8,39,24,23,75,72"
Prints each occurrence ("code/font" per glyph, font as its last character: 1-5 for Othmani1-5)
and how many distinct font assignments were seen.
"""
import argparse
import collections
import gzip
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # python -I leaves the script folder out
import extract_text as X  # noqa: E402


def glyph_words(block):
    """The block as words: each a list of (code, font) for glyphs, or [("T", None)] for text."""
    words, cur = [], []
    for p in block.pieces:
        chars = [(p[3][-2:].upper(), p[2])] if p[0] == "g" else [(" ", None) if c.isspace() else ("T", None) for c in p[1]] if p[0] == "t" else []
        for code, font in chars:
            if code == " " or code == "T":
                if cur:
                    words.append(cur)
                    cur = []
                if code == "T":
                    words.append([("T", None)])
            else:
                cur.append((code, font))
    if cur:
        words.append(cur)
    return words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--word", required=True, type=pathlib.Path, help="output folder of word_export.ps1")
    ap.add_argument("--skip", help="leave out books whose name contains this (e.g. the book being repaired)")
    ap.add_argument("words", help='glyph codes, e.g. "9E,77_DF,89,C5,67,72,42"')
    args = ap.parse_args()
    target = [[c.upper() for c in w.split(",")] for w in args.words.split("_") if w]
    plain = re.compile(r"\s+".join("".join(re.escape(chr(0xF000 + int(c, 16))) for c in w) for w in target))
    seen = collections.Counter()
    books = set()
    for path in sorted((args.word / "final").glob("*.xml.gz")):
        if args.skip and args.skip in path.name:
            continue
        raw = gzip.open(path, "rb").read().decode("utf-8")
        if not plain.search(re.sub(r"<[^>]+>", "", raw)):
            continue
        reader = X.Reader(raw)
        notes = [b for d in reader.notes.values() for blocks in d.values() for b in blocks]
        for n, block in enumerate(reader.blocks + notes):
            words = glyph_words(block)
            for i in range(len(words) - len(target) + 1):
                if all([c for c, _ in words[i + k]] == target[k] for k in range(len(target))):
                    fonts = " | ".join(" ".join(f"{c}/{(f or '?')[-1]}" for c, f in words[i + k]) for k in range(len(target)))
                    seen[fonts] += 1
                    books.add(path.name)
                    print(f"{path.name[:-len('.xml.gz')]} (block {n}): {fonts}")
    print(f"\n{sum(seen.values())} occurrences in {len(books)} books; {len(seen)} distinct font assignment(s)")


if __name__ == "__main__":
    main()

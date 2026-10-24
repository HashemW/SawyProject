"""How much text do the source files share? (Input: word_export.ps1 text/ folder.)

Counts paragraphs of 20+ words by normalized hash and reports, per file, how many of its
paragraphs also occur in another file, plus the file pairs that share the most.

Run: python -I -X utf8 scripts/overlap.py data/work/word/text
"""
import collections
import hashlib
import pathlib
import re
import sys
import unicodedata

DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed\u0640]")
SPLIT = re.compile(r"[\r\n\v\f\x07]")


def key(paragraph):
    p = unicodedata.normalize("NFC", paragraph)
    p = DIACRITICS.sub("", p)
    p = re.sub(r"[^\w\s]", " ", p)
    words = p.split()
    return hashlib.sha1(" ".join(words).encode()).hexdigest() if len(words) >= 20 else None


def main(folder):
    files = sorted(pathlib.Path(folder).glob("*.txt"))
    where = collections.defaultdict(set)
    per_file = {}
    for f in files:
        keys = [k for k in (key(p) for p in SPLIT.split(f.read_text(encoding="utf-8"))) if k]
        per_file[f.name] = keys
        for k in keys:
            where[k].add(f.name)
    total = sum(len(v) for v in per_file.values())
    unique = len(where)
    print(f"paragraphs (20+ words): {total:,} in {len(files)} files; distinct: {unique:,} ({unique / total:.1%})")
    pairs = collections.Counter()
    for k, names in where.items():
        names = sorted(names)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs[(names[i], names[j])] += 1
    print("\nfile pairs sharing the most paragraphs:")
    for (a, b), n in pairs.most_common(25):
        print(f"{n:6,}  {a[:-8]}  <->  {b[:-8]}")
    print("\nshare of each file's paragraphs that also appear in another file:")
    for name, keys in sorted(per_file.items()):
        if keys:
            shared = sum(1 for k in keys if len(where[k]) > 1)
            print(f"{shared / len(keys):6.1%}  of {len(keys):5}  {name[:-8]}")


if __name__ == "__main__":
    main(sys.argv[1])

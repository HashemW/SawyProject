# Text extraction from the Word sources

Done 2026-10-24 by Claude for Hashem. This replaces `clean_txt`, which turned out not to be usable as is (see [data-verification.md](data-verification.md)).

**Result:** all 115 Word files that open are extracted. Compared with Word's own plain text of the same documents, every word is there, in order, and nothing is added: 7,527,899 words of main text and 1,103,822 words in 34,055 footnotes, 0 missing, 0 extra. All 1,708,156 characters typed in glyph fonts are accounted for. The 15,681 Quran quotes typed in glyph fonts are now real text: 15,553 (99.2%) match the Quran letter for letter as quoted, 109 more once stray characters standing in for glyphs are allowed for, and 19 need a human decision (below). 15,264 honorifics typed as glyphs are written out in words.

The output is local (`data/work/extract/`, gitignored because it holds the books). Reproduce with:

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_export.ps1 -InputDir data\raw\sawi_material -OutDir data\work\word
python -I -X utf8 scripts\extract_text.py --word data\work\word --quran data\raw\quran\quran-uthmani.txt --out data\work\extract
python -I -X utf8 scripts\check_extract.py --word data\work\word --extract data\work\extract
```

## What you get

- `json/<book>.json`: the book as blocks in reading order. Each block has a `kind` (`p` paragraph, `cell` table-cell paragraph with its table/row/column, `textbox`, `toc` table-of-contents line), its Word `style` (fatwa titles carry heading styles, e.g. `heading 3` in the 2020–23 chapter files), its outline level, its `text`, and `spans` marking what in the text came from somewhere special: `quran` (with the verses, how the quote was identified, and the reference the Sheikh cited), `honorific` (with the glyph it was drawn with), `note` (footnote reference), `symbol` (bullets). `notes` holds the footnotes in Word's numbering, with the same structure. Every file carries the Tanzil attribution.
- `text/<book>.txt`: the same text, one paragraph, cell or text-box paragraph per line (tables of contents left out; they only repeat headings). `text/<book>.notes.txt`: footnotes, `<n><TAB><text>`.
- `report.md`: counts per book and every quote listed for review. `check.md`: the acceptance test.

## How the text is read

`word_export.ps1` has Word open each file read-only with macros off, accept tracked changes (there are none) and turn list numbers into text, all in memory, then save Word's XML of that state (`final/`) and Word's own plain text of it (`text/`, `notes/`, `frames/`). Nothing is ever saved back.

`extract_text.py` reads that XML. It keeps what a reader sees: hidden text and field codes are left out and field results kept, as Word's own text does; footnotes get the numbers Word shows; tables are read cell by cell; text boxes (cover titles, and section headings in one treatise) are kept where they are anchored.

Three kinds of text are not ordinary characters in these files.

### Quran quotes in glyph fonts

15,681 quotes are typed in the HQPB1–5 or Othmani1–5 fonts (the same glyph set), plus 33 phrase glyphs (the basmala, «قال تعالى:», «صدق الله العظيم»). These fonts draw the Madinah mushaf piece by piece: one character per letter shape, vowel mark, verse-end ornament or digit. Read as text, a quote is nonsense.

1. **Letters.** Every glyph of fonts 1–3 was labelled with the letter it draws. The labels were read off the fonts (installed on Hashem's PC) and then checked by aligning 11,552 referenced quotes with the Tanzil text: 11,500 then read exactly as the cited verses, and every label agrees with at least 97% of its aligned occurrences (`scripts/quran_glyphs.py`). Vowels and other marks are not decoded: they come from Tanzil.
2. **Placement.** The letters of each quote are looked up in Tanzil's Uthmani text: first in the verses the Sheikh cites after the quote (12,985 found there), then 3 verses either side (199), then anywhere (2,355: no reference, or one that names other verses). The match must be letter for letter; verse-end ornaments inside a quote must sit at the end of the verse they number. The quote is then written as Tanzil's words for exactly that span (a partial quote stays partial), between the source's brackets, with the verse-end ornaments the source shows (`۝` and the number) and Tanzil's pause marks where the source has them.
3. **What the glyph program and the typists did to some quotes**, each still matched letter for letter: quotes starting inside a word (﴿وَلَمْ تُؤْمِن﴾ from أَوَلَمْ, 14), words the glyph program joins where Tanzil does not (بعدما, 6), words typed without a space, which come out swapped (29), neighbouring words stored in swapped pairs (4) or a whole quote in visual order (1), and brackets stored inside the quote (after its first word and before its last, in several Othmani-font books). 109 quotes have stray characters (`.` `/` `،` `:`) where a glyph should be: the glyph's code read as an ordinary character (`.` is code 0x2E, a kāf shape; `/` is 0x2F, a bāʾ shape). They are matched with each stray character standing for the missing glyph, near the cited verses (or anywhere if the quote is long and only one place fits).
4. **Vowels.** Where the same letters occur in several places with different vowels (one-word quotes such as ﴿كَانَ﴾ in a grammar remark), the quote's own glyphs decide: the same glyph sequence read in quotes identified without doubt shows which vowels it carries. 77 quotes were settled this way, 6 remain open.
5. **Quotes that are wrong in the source** (letters or a word missing, e.g. 77:26 typed without أَحْيَآءً) are placed only within the verses the Sheikh cites, written with the correct Tanzil text, and listed for review. A misquoted verse is never printed as Quran.

A visual check rendered quotes in the original fonts next to the output: 12 random exact ones, 12 random repaired ones and all 12 corrected ones. All show the same words; the corrected ones show exactly the letters or word missing from the source.

### Honorifics in glyph fonts

AGA Arabesque symbols, and every character set in the font `CTraditional Arabic` (used for nothing else), stand for an honorific. These fonts are not on any of our machines, so each symbol's meaning was taken from sentences that occur twice in the sources, once with the symbol and once with the words typed out:

| Font | Character | Written as | Evidence: matches with the words typed out |
|---|---|---|---|
| AGA Arabesque | `U` | عز وجل | 2,410 (246 have «تعالى» instead) |
| AGA Arabesque | `Y` | جل جلاله | in 30+ different sentences («عز وجل» in one) |
| AGA Arabesque | `I` | سبحانه وتعالى | 606 |
| AGA Arabesque | `r`, `e` | صلى الله عليه وسلم | 336, 24 |
| AGA Arabesque | `t` | رضي الله عنه | 2,955 |
| AGA Arabesque | `y` | رضي الله عنهم | 72 |
| AGA Arabesque | `u` | عليه السلام | 100 |
| AGA Arabesque | `] } )` / `[ { (` | ﴿ / ﴾ | they open and close the Othmani-font quotes |
| CTraditional Arabic | `:` | رحمه الله | 754, in 310 different sentences |
| CTraditional Arabic | `ب` | رضي الله عنهما | 400, in 56 |
| CTraditional Arabic | `ل` | رضي الله عنها | 223, in 124 |
| CTraditional Arabic | `ت` | رضي الله عنه | no duplicates; all 16 contexts are Companions, one «… ت وأرضاه» |
| CTraditional Arabic | `ن`, `س` | رضي الله عنهم, رضي الله عنه | no duplicates; their only contexts (1 and 2) |

`CTraditional Arabic`'s `ﻷ` (6 times in «المواجهة بين الإسلام…», always after «الله») could not be read; it is left out and counted in the report. These letter-honorifics are also why `clean_txt` has stray letters after names («عباس ب» 74 times).

### Other symbols

Bullets in Symbol, Wingdings and similar fonts become `•`, Symbol's tick `√`, list numbers set in AGA Arabesque their digits. 232 purely decorative glyphs are left out and counted (Webdings and AGA Arabesque separator lines, a few Wingdings stars, and the 6 unread `ﻷ`).

## Acceptance test

`check_extract.py` compares the extraction with Word's own plain text, which Word produces from the documents independently of our XML reading. Word cannot show glyph-font text, so the check puts back, in place of each quote or honorific, the characters Word shows for it, and then compares every word (Arabic, digits, Latin) in order.

| | In Word's text | Missing from the extraction | Extra |
|---|---|---|---|
| Main text (paragraphs, table cells, tables of contents) | 7,527,899 words | 0 | 0 |
| Footnotes | 34,055 notes, 1,103,822 words | 0 | 0 |
| Text boxes | 332 words | 0 | 0 |

All 1,708,156 glyph-font characters are accounted for; 0 of 115 files differ. The check allows for three things Word's own text does: it shows text formatted as all caps in capitals (tables of contents), so the extraction does too; its copy of a footnote typed without an automatic mark drops the hand-written number; it lists text boxes in its own order.

## For review

`data/work/extract/report.md` lists each of these with the source's own letters and the text that was written.

Left out (19). Decision (Hashem, 2026-10-24): the fatawa that contain these quotes are not included in the records at all.

- **1 not identified:** «إلا الله» in `نهائي الطحاوية`, with no reference; shown as ⟦?⟧.
- **6 one- or two-word quotes** without a reference whose vowels the glyphs do not settle; the first candidate is shown. Example: ﴿شَهِدْنَا﴾, which the context points to 7:172 «شَهِدْنَآ».
- **12 quotes that are wrong in the source**, written with the cited verses' correct text: 22:28 typed «لِّيَشْهَدُو» (4 copies), 7:33 with every بـ missing (2), 5:1 without بِ (2), 77:25–26 without أَحْيَآءً, 5:5 «لَّكُ», 6:148 with two kāfs missing, and 8:12–13 with a stray «مَعَكُمْ» glued to the first word.

For information:

- **109 repaired quotes** (stray characters standing in for glyphs). A random dozen were checked by eye: all correct.
- **35 quotes** whose glyphs lack a mark Tanzil has at that place: contextual ones the glyph program never draws (فَمَنِ before a hamzat al-wasl, وَمَآ before a hamza) and a few shaddas missing in the source (إِن for إِنَّ). The output has Tanzil's text.
- **74 quotes** whose written reference names other verses: typos and reversed digits (`[النساء: 06 - 16]` for 60–61 in `الصارم`). The quote text is right; the Sheikh's reference is left as written, and the true verses are in the JSON.

Possible improvement: decoding the vowel-mark glyphs (fonts 4–5) would settle the 6 ambiguous quotes and check every quote's vowels directly.

## Not covered

- `التعددية السياسية.doc`: Office refuses to open it ("Office has detected a problem with this file"). It needs a fresh copy; it is a treatise, not fatawa.
- Pictures are not read. The only ones are small decorations next to headings.

## Quran text

Quran text: Tanzil Quran Text (Uthmani, version 1.1), Copyright (C) 2007-2026 Tanzil Project, Creative Commons Attribution 3.0, https://tanzil.net. Its terms allow verbatim copies only, and an app that uses it must credit the Tanzil Project and link to tanzil.net.

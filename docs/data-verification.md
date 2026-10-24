# Source data verification

Checked 2026-10-24 by Claude for Hashem.

**Question:** is `clean_txt` (Drive, converted Dec 2025) a faithful, complete copy of the Sheikh's Word documents in `sawi_material`?

**Answer: no. Don't build on it.** Where nothing special is going on, the prose came through exactly, character for character. But the conversion dropped or rewrote five kinds of content, and the losses are systematic, not occasional:

| Problem | Scale (all 115 converted files) | Example |
|---|---|---|
| **Footnotes dropped.** Hadith sources and citations are gone; their markers are left as empty `()`. | 0 of 29,639 footnotes kept | every fatwa book |
| **Quran quotes rewritten.** Before every `[سورة: آية]` reference the converter put the whole verse from a database: partial quotes became full verses, quotes already in Unicode got a second copy, and verses typed in one of the glyph fonts were deleted outright. | 14,588 quotes in the sources. Of the 11,466 that could be paired, at least 7,099 are longer than what the Sheikh quoted; 479 duplicates added; 3 books (المحاورة, تهافت العلمانية, تساؤلات أمريكية) have no verses left at all | `03 (2) كتاب العلم`: a 7-word quote of البقرة 61 became the whole 60-word verse |
| **Text dropped wherever a run was tagged with a symbol font.** Ordinary Arabic whose Latin-font slot says "AGA Arabesque" was thrown away with the ornaments. | `الصارم` lost 6,791 words (10%); glued words elsewhere | `الصارم`: a whole section of hadith evidence (from «فمن ذلك ما ذكره سعيد بن المسيب» onward) is gone |
| **Tables mostly dropped.** | 1,366 of 3,294 table cells kept (tables of contents not counted) | quoted poetry laid out in tables, board lists, tables inside fatawa |
| **Two files failed.** | `تساؤلات أمريكية` kept 32 of 26,532 words; `التعددية السياسية` has no text file (Office refuses to open the source; we later repaired a copy, see [extraction.md](extraction.md#repaired-source)) | |

Found later, during the re-extraction ([extraction.md](extraction.md)): about 4,500 honorifics drawn with the font `CTraditional Arabic` on ordinary characters (`ب` for رضي الله عنهما, `ل` for رضي الله عنها, `:` for رحمه الله) come through in `clean_txt` as stray letters or colons («عباس ب» 74 times).

Overall, outside Quran passages and tables of contents the sources hold 7,361,790 Arabic words, and 55,957 of them (0.76%) are missing from `clean_txt`. The losses are concentrated in the files above, and 31 of the 115 files have none. The ordinary prose of the fatawa is otherwise exact.

Not problems: every file is valid UTF-8 with no garbage characters; `clean_txt` invented nothing, since only 199 of its words appear nowhere in the sources; tables of contents were dropped in most files and kept in the 2022–23 `.docx` ones, but they only repeat headings; volumes 33, 35 and 36 are empty templates in the source too.

## How this was checked

1. **All files.** Downloaded all 116 Word files in `sawi_material` and all 115 files in `clean_txt` through the Drive website. The Google Drive connector lists only one of the 116 sources, so it cannot be used for this.
2. **Word as the reference.** `scripts/word_export.ps1` has Microsoft Word open every source read-only with macros disabled and nothing saved, then writes Word's main text, its footnotes and the document XML.
3. **Exact comparison.** `scripts/verify_txt.py` rebuilds each document's visible text from Word's XML, including exactly where Quran glyphs sit, which Word's plain text cannot show. It then compares that text with the `clean_txt` file line by line, word by word and character by character, and separately counts words regardless of order, so moved text cannot hide a loss. Table cells and footnotes are looked up directly; Quran quotes are paired by their verse reference.
4. **The reference itself was checked.** Over all sources, the rebuilt text and Word's own plain text contain the same 7,447,443 Arabic words. About 780 tokens (0.01%) are split differently, all of them words touching a glyph, which Word's plain text glues to a `(` placeholder.
5. The full per-file table is `data/work/verify/report.md` (local, not committed; it holds text excerpts). Reproduce with:

```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_export.ps1 -InputDir data\raw\sawi_material -OutDir data\work\word
python -I -X utf8 scripts\verify_txt.py --sources data\raw\sawi_material --word data\work\word --clean data\raw\clean_txt --out data\work\verify
python -I -X utf8 scripts\overlap.py data\work\word\text
```

## What the sources look like

- **116 files:** for each fiqh chapter `01`–`23`, usually `NN book.doc` (2011), `NN <chapter>.doc` (2020–21) and `NN (2) <chapter>.docx` (2022–23 additions); `24`–`32 book.doc`; volumes 33/35/36 (empty templates); about 30 standalone books and treatises.
- **About 30% duplication:** 129,957 paragraphs of 20+ words, of which 90,273 are distinct. The `book` volumes and the chapter files are two arrangements of largely the same fatawa, so the corpus needs deduplicating before indexing.
- **Quran is not text in most files.** It comes in three encodings: `<w:sym>` glyphs in the HQPB1–5 fonts, private-use characters in the Othmani1–5 fonts (both with AGA Arabesque ornamental brackets), and in a few books, real Unicode text. Turning glyphs back into text needs either the fonts' glyph tables or a canonical Quran text plus the cited verse.
- Footnote references sit inside literal parentheses, which is why dropping them leaves `()`.

## Next step

Re-extract the text from the Word files instead of using `clean_txt`, keeping all text, tables, list numbers and footnotes (attached to their fatwa), and replacing each Quran glyph passage with exactly the words quoted. `verify_txt.py` is the acceptance test for that extraction: 100% of the source's words, nothing extra, every table cell and footnote present, and every quote identical to the source.

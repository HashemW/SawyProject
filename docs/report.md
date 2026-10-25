# Sawy Fatwa Assistant: technical report

A running record of how the fatawa and writings of Dr. Salah Al-Sawy (أ.د. صلاح الصاوي) are being turned into a verbatim, citable answer base for a voice assistant that speaks in his cloned voice. Each step is written up when it is done: what was done, how, how it was checked, the numbers, the problems met and the decisions taken.

Hashem, with Claude. Last updated 2026-10-25.

**Status.** Steps 1 to 3 are complete. The text of all 116 Word files is extracted and checked; one damaged file was repaired first (section 5). It is split into records: the fatwa encyclopedia gives 12,779 distinct fatawa after deduplicating its three editions (section 8), and the Sheikh's own standalone books give 682 more records (section 9). The corpus is 13,461 records. Search over it is built and measured (section 10): on held-out test questions, the right record is among the first 20 candidates for 85% of questions and the first 50 for 95%. Step 4, choosing the answer among the candidates, is next.

## Contents

1. [Introduction (step 0)](#1-introduction-step-0)
2. [Materials](#2-materials)
3. [Step 1a: checking the existing conversion](#3-step-1a-checking-the-existing-conversion)
4. [Step 1b: extracting the text from Word](#4-step-1b-extracting-the-text-from-word)
5. [Step 1c: repairing the damaged source](#5-step-1c-repairing-the-damaged-source)
6. [Decisions](#6-decisions)
7. [Open questions](#7-open-questions)
8. [Step 2a: one record per fatwa (the encyclopedia)](#8-step-2a-one-record-per-fatwa-the-encyclopedia)
9. [Step 2b: the standalone books](#9-step-2b-the-standalone-books)
10. [Step 3: the search index](#10-step-3-the-search-index)
11. [Next: step 4, choosing the answer](#11-next-step-4-choosing-the-answer)
- [Appendix A: reproducing the data](#appendix-a-reproducing-the-data)
- [Appendix B: repository map](#appendix-b-repository-map)
- [Appendix C: glossary](#appendix-c-glossary)

## 1. Introduction (step 0)

### 1.1 Aim

People ask the assistant a religious question by voice or text. It answers with the Sheikh's own fatwa on that question, read out in his voice (an ElevenLabs clone, "sawy v2", trained on about two hours of his khutbahs), and it says where the fatwa comes from. The Sheikh asked for this project.

### 1.2 The constraint: only his words

Because everything the assistant says comes out in his voice, any sentence it generates would sound like him saying it. The project therefore runs on one rule (CLAUDE.md, "Core rule"):

1. Answers are his text, verbatim: the matching fatwa, or an excerpt of it that keeps the ruling and its conditions. No paraphrase, summary, translation, or merging of several fatawa.
2. When no fatwa clearly matches, the assistant says so with a fixed message. It never falls back to general knowledge, "the majority view", calculations or free advice.
3. Every answer cites the collection, chapter, fatwa title and the original question, so the listener can judge whether it fits their case.
4. A language model may choose, never write. It normalizes the question, ranks candidate fatawa and names the one that answers it, or none. Its output is an ID, so even a manipulated question can at worst select the wrong fatwa or none; it cannot put new words in his mouth. Everything that is not a fatwa (greeting, "not found", disclaimers) comes from a short list of fixed, pre-approved messages.

One exception was decided later (section 6): for questions about the asker's own case, which go to a person, the bot may show AI-written commentary on related fatawa as labelled text on screen, never in his voice.

### 1.3 Starting point

Before this repository, the team had cloned the voice and built a prototype ElevenLabs agent. The agent used ElevenLabs' built-in knowledge-base retrieval, and a general language model wrote each answer from what it retrieved (Gemini Flash in the November 2025 notes; Gemini 2.0 Flash and GPT-5 were also tried). The answers were generated, not quoted, so they could not be guaranteed to be his words, and testing was thin. An older system prompt also allowed exceptions (the majority opinion, calculations, "universally agreed" matters, free advice); these conflict with the rule above and were dropped.

A plain-text conversion of the Sheikh's Word files also existed (`clean_txt`, December 2025); whether it was faithful had not been checked.

### 1.4 Approach

The work replaces the generated answers with retrieval of verbatim passages and keeps ElevenLabs for the voice:

| Step | What | Status |
|---|---|---|
| 1 | Ingest: get every word of the sources out exactly, including footnotes, tables, Quran quotes and honorifics | done (sections 3–5) |
| 2 | Segment: one record per fatwa (title, question, answer, notes, source) and one per treatise section; dedupe across editions | done (sections 8–9) |
| 3 | Index: Arabic-aware keyword search plus multilingual embeddings, over questions and answers | |
| 4 | Select: rerank candidates, then a strict check that a candidate answers the question; otherwise the fixed "not found" message | |
| 5 | Voice: TTS of the verbatim text, cached and reviewed per passage; Quran quotes need special care | |
| 6 | Evaluate: the team's Golden Dataset, paraphrased questions, questions that must be refused, injection attempts. Target: no non-Sheikh text in any answer | |

The first steps are about data quality, because nothing later can be better than the text it retrieves and reads out.

## 2. Materials

### 2.1 The Word sources

The source of truth is the Drive folder `sawi_material`: 116 Word files (`.doc` and `.docx`, written between 2003 and 2023, about 7.6 million words of text and 1.1 million words of footnotes).

| Group | Files | Notes |
|---|---|---|
| Fatwa encyclopedia (`موسوعة فتاوى المغتربين`), three editions | 32 volumes `01 book.doc` … `32 book.doc` (saved 2011–2017); 25 chapter files of 2020–21 (`NN <chapter>.doc`, chapter 01 as `01-1`…`01-3`); 23 chapter files of 2022–23 (`NN (2) <chapter>.docx`, chapter 04 as `(3)`) | Each volume spans every chapter (creed, politics, knowledge, purification, prayer, … miscellaneous), with fatawa numbered continuously across volumes («794. حكم الوشم»). The later editions are arranged by chapter, one file each. The dates come from the files' own properties; the 2022–23 files were last saved under the Sheikh's account. Nine 2022–23 files are marked `تحت الإجراء` (in progress): chapters 04, 05, 07, 08, 10, 14, 15, 17, 21. Chapter numbers 16–18 differ between the 2020–21 and 2022–23 files. |
| Volumes 33, 35, 36 | three files | empty templates (headings only) |
| Standalone books and treatises | about 30 | e.g. `الصارم`, `نهائي الطحاوية`, `ما لا يسع المسلم جهله`, `مالا يسع التاجر جهله`, `نوازل فقهية على الساحة الأمريكية`, `التعددية السياسية` |

The editions overlap heavily: of 129,957 paragraphs of 20 or more words, 90,273 are distinct (`scripts/overlap.py`). The `book` volumes and the chapter files are largely two arrangements of the same fatawa.

### 2.2 Other sources

| Source | Use |
|---|---|
| `clean_txt` (Drive, December 2025): 115 `.txt` files, one per source | checked in step 1a and rejected |
| Tanzil Quran text, Uthmani, version 1.1 (downloaded 2026-10-24 from tanzil.net) | to identify Quran quotes typed in glyph fonts and write them as text. Its terms allow verbatim copies only, and the app must credit the Tanzil Project with a link to tanzil.net; accepted by Hashem. |
| Video fatawa (Drive `sawi_material/YouTube Fatwas/`) | a `metadata` sheet of 1,308 YouTube clips from his live fatwa programmes, 2020–2024, each titled with one question and mostly under 4 minutes, with a Whisper machine transcript per clip (`open_ai_whisper_1/`, February 2025). Left out for now: machine transcripts are not verbatim and are not trusted (decision, section 6). |
| fatawaalsawy.com | the public fatwa archive; the team has asked the site manager for an export |
| `sawi.mp3`, about 2 hours of khutbahs | the voice clone's training audio |
| Golden Dataset and earlier model tests (Google Sheets, linked in CLAUDE.md) | for step 6 |

### 2.3 Environment

All processing runs on Hashem's Windows 11 PC: Microsoft Word (needed to read the `.doc` files, see 4.1), Python 3.13 with the standard library only up to step 2, and PowerShell. The search index (step 3) uses a project venv with PyTorch on the PC's NVIDIA RTX 3070 (8 GB), sentence-transformers and PyStemmer (`requirements.txt`); its embedding models are stored in `data/models/`, on drive D: (drive C: has about 5 GB free). The Quran glyph fonts HQPB1–5 are installed there; Othmani1–5, AGA Arabesque and CTraditional Arabic are not. The Google Drive connector only lists files Hashem has opened, so the sources were downloaded through the Drive website in Chrome, as zips (`scripts/extract_zip.py` keeps the Arabic file names intact). The books and everything derived from them stay outside git (`data/` is ignored) and the repository is private.

## 3. Step 1a: checking the existing conversion

Full write-up: [data-verification.md](data-verification.md).

**Question.** Is `clean_txt` a faithful and complete copy of the Word files?

**Method.** Every source was read by Microsoft Word itself (`scripts/word_export.ps1`: read-only, macros disabled, nothing saved), which writes Word's own plain text, its footnotes and the document's XML. `scripts/verify_txt.py` rebuilds each document's visible text from that XML, including exactly where Quran glyphs sit (Word's plain text cannot show them), and compares it with the `clean_txt` file line by line, word by word and character by character; it also counts words regardless of order, so moved text cannot hide a loss. Table cells and footnotes are looked up directly, and Quran quotes are paired by their verse reference. The reference was itself checked: the rebuilt text and Word's plain text contain the same 7,447,443 Arabic words.

**Results.** The plain prose is exact, character for character, and `clean_txt` invents nothing. But five kinds of content were systematically dropped or rewritten:

| Problem | Scale |
|---|---|
| Footnotes dropped (hadith sources, citations); their markers left as empty `()` | 0 of 29,639 kept |
| Quran quotes rewritten: the converter inserted the whole verse from a database before every reference, so partial quotes became full verses, quotes already in Unicode were duplicated, and verses typed in glyph fonts were deleted | of 11,466 quotes that could be paired, at least 7,099 longer than what the Sheikh quoted; 479 duplicates; 3 books with no verses left |
| Text dropped wherever a run carried a symbol font in its Latin slot, although the text was ordinary Arabic | `الصارم` lost 6,791 words (10%), including a whole section of hadith evidence |
| Tables mostly dropped | 1,366 of 3,294 cells kept |
| Files failed | `تساؤلات أمريكية` kept 32 of 26,532 words; `التعددية السياسية` has no text file |

About 4,500 honorifics drawn as letters in a special font also came through as stray letters («عباس ب»). Overall, 0.76% of the Arabic words outside Quran passages are missing, concentrated in a few files.

**Conclusion.** `clean_txt` cannot be used: an answer read out in his voice must not lose its evidence, misquote the Quran or drop paragraphs. The text had to be extracted again.

## 4. Step 1b: extracting the text from Word

Full write-up: [extraction.md](extraction.md).

### 4.1 Reading through Word

Most sources are old binary `.doc` files, and LibreOffice is not installed, so Word is the reader. `word_export.ps1` opens each file read-only with macros disabled, accepts tracked changes (there are none) and turns automatic list numbers into text, all in memory, and saves Word's XML of that state together with Word's own plain text of the main story, the footnotes and the text boxes. Nothing is ever written back. (Word's Save As hangs on these files, so everything is read from memory.)

### 4.2 From XML to text

`scripts/extract_text.py` reads the XML and keeps what a reader sees: every paragraph, table cell (with its table, row and column), text box and footnote, hidden text and field codes left out and field results kept, footnotes with the numbers Word shows. Each book becomes `json/<book>.json`: blocks in reading order, each with its Word style (fatwa titles carry heading styles in the 2020–23 files), outline level, formatting (alignment, share of bold letters, most common font size; added in step 2b for finding headings) and text, plus spans marking where the text came from something special (Quran quote, honorific, footnote reference, bullet). Footnotes are kept with the same structure.

Three kinds of content are not ordinary characters in these files.

### 4.3 Quran quotes typed in glyph fonts

Most quotes are typed in the HQPB1–5 or Othmani1–5 fonts (the same glyph set, as `<w:sym>` symbols or as private-use characters). These fonts draw the Madinah mushaf piece by piece: one character per letter shape, vowel mark, verse-end ornament or digit, so the stored characters are not readable text. Ornamental brackets come from AGA Arabesque.

1. **Letters.** Every glyph of fonts 1–3 was labelled with the letter it draws, read off the installed fonts, then checked by aligning 11,552 quotes that carry a verse reference with the Tanzil text: 11,500 then read exactly as the cited verses, and every label agrees with at least 97% of its aligned occurrences. Vowel marks (fonts 4–5) are not decoded; vowels come from Tanzil.
2. **Placement.** The letters of each quote are looked up in Tanzil: in the verses the Sheikh cites (13,028 exact quotes found there), then three verses either side (199), then anywhere (2,366). The match must be letter for letter, and verse-end ornaments must fall at verse ends. The quote is then written as Tanzil's words for exactly the quoted span; a partial quote stays partial.
3. **Typing artefacts**, each still matched letter for letter: quotes starting inside a word, words the glyph program joins, words typed without a space, swapped neighbours, brackets stored inside the quote, and 109 quotes where a stray character (`.` `/` `،` `:`) stands where a glyph should be.
4. **Vowels.** Where the same letters occur at several places with different vowels, the quote's own glyphs decide, by how the same glyph sequence reads in quotes identified without doubt (77 settled, 6 open).
5. **Quotes that are wrong in the source** (a word or letters missing) are placed only within the cited verses, written with the correct Tanzil text and listed for review; a misquote is never printed as Quran.

A visual check rendered quotes in the original fonts next to the output (12 random exact, 12 random repaired, all 12 corrected): the words agree, and the corrected ones show exactly what the source was missing.

### 4.4 Honorifics and other symbols

AGA Arabesque symbols, and every character in the font `CTraditional Arabic`, stand for honorifics (عز وجل, صلى الله عليه وسلم, رضي الله عنه, رحمه الله, …). These fonts are not installed anywhere we have, so each symbol's meaning was taken from sentences that occur twice in the sources, once with the symbol and once with the words typed out (for example `t` → رضي الله عنه, matched 2,955 times). One glyph (`ﻷ`, 6 times, in one book) could not be read and is left out. Bullets become `•`, list numbers set in a symbol font become digits, and purely decorative glyphs are dropped and counted.

### 4.5 Acceptance test

`scripts/check_extract.py` compares the extraction with Word's own plain text, which Word produces independently of our XML reading. Word shows glyph-font text as `(` or a private-use character, so the check puts those characters back in place of each quote or honorific and then compares every word (Arabic, digits, Latin) in order: main text, each footnote, and the text boxes.

### 4.6 Results

All 116 files are extracted, one of them from the repaired copy described in section 5, and none differs from Word's text:

| | Words in Word's text | Missing | Extra |
|---|---|---|---|
| Main text (paragraphs, table cells, tables of contents) | 7,566,612 | 0 | 0 |
| Footnotes (34,158 notes) | 1,104,810 | 0 | 0 |
| Text boxes | 332 | 0 | 0 |

All 1,712,929 glyph-font characters are accounted for. Of 15,735 Quran quotes typed in glyph fonts, 15,607 (99.2%) match the Quran letter for letter as quoted, 109 more around stray characters, and 19 need a human decision; 33 more are phrase glyphs (the basmala, «قال تعالى:», «صدق الله العظيم»). 15,331 honorifics are written out in words. The books hold 277,496 paragraphs, 18,798 table-cell paragraphs and 37,953 footnote paragraphs.

### 4.7 Quotes left for review

Nineteen quotes could not be written with certainty: 1 not identified, 6 one- or two-word quotes whose vowels the glyphs do not settle, and 12 that are wrong in the source (for example 22:28 typed «لِّيَشْهَدُو» in four copies). **Decision (2026-10-24):** every fatwa containing one of them is left out of the records; the 109 repaired quotes stay. The full list is in `data/work/extract/report.md`.

## 5. Step 1c: repairing the damaged source

### 5.1 Symptom

One of the 116 files, `التعددية السياسية.doc` (the treatise «التعددية السياسية في الدولة الإسلامية», 843,264 bytes, last modified 2004-07-29), would not open. Word refuses it ("Office has detected a problem with this file. To help protect your computer this file cannot be opened."), also with Open and Repair and with the "Recover Text from Any File" converter. Google Docs, which uses its own reader, opens it as an empty page. Drive keeps only this one version, so there is no older copy to fall back on. `clean_txt` has no text for it.

### 5.2 Diagnosis

The file was read directly, without Word, following Microsoft's published specifications of the compound-file and Word binary formats (MS-CFB, MS-DOC):

- **Container:** a valid compound file (version 3, 512-byte sectors) with consistent sector chains and the usual streams (`WordDocument` 683,660 bytes, `1Table` 132,884, `Data`, the summary streams).
- **Text:** the piece table is intact and gives 236,984 characters: 230,787 of main text, 6,107 in 103 footnotes, plus headers and text boxes. The text begins «التعددية السياسية في الدولة الإسلامية … تأليف الأستاذ الدكتور/ صلاح الصاوي».
- **Formatting:** all 99 paragraph-formatting pages are valid. Of the 306 entries of the character-formatting bin table (PlcfBteChpx, which maps each stretch of text to the 512-byte page that holds its character formatting), one is broken: entry 198 points at page 0, which is the file header, not a formatting page. The surrounding entries point at consecutive pages 1157, 1158, 1159, (0), 1160, 1161, so the page for this stretch was apparently never written. Fixing this one entry is enough for Word to open the file (5.6), so it is what Word's file validation rejects; Google's reader most likely fails on the same entry.

### 5.3 What was lost

Entry 198 covers 41 characters. They sit in a passage quoted from al-Qurtubi: «… لا تجالس القدرية وعادهم في الله لقوله تعالى: ﴿لَّا تَجِدُ قَوْمًا يُؤْمِنُونَ بِٱللَّهِ وَٱلْيَوْمِ ٱلْـَٔاخِرِ يُوَآدُّونَ مَنْ حَآدَّ ٱللَّهَ وَرَسُولَهُۥ﴾ قلت: …» (58:22). The 41 characters are a space, the opening bracket, the glyphs of the first five words of the verse and the first glyph of the sixth, and the spaces between them. The characters themselves are intact. What is lost is their formatting, and for a glyph quote that is the essential part: which of the fonts Othmani1–5 each glyph is drawn in (the same code draws different shapes in different fonts), and which AGA Arabesque symbol stands behind Word's `(` placeholder for the bracket.

### 5.4 Evidence for the lost formatting

The glyph program that typed these quotes produces the same codes in the same fonts for the same words. Three independent pieces of evidence give the same answer:

1. **The same paragraph quotes the verse twice.** About 380 characters earlier, the Sheikh's own text quotes 58:22 in the same glyphs, and that copy is intact. Its glyphs have fonts `5 2 | 4 1 4 1 5 1 | 1 4 2 4 2 5 2 | 5 2 2 4 2 4 2 4 2 4 2 | 5 1 5 1 4 1 | 4 …`, and its opening bracket is AGA Arabesque F029.
2. **Other books.** `scripts/find_glyph_fonts.py` lists every occurrence of the same glyph words in the other 115 books: the first five words occur 7 times in 6 books, and «بِٱللَّهِ وَٱلْيَوْمِ» 29 times in 11 books. Every occurrence has exactly the same font for every glyph (one distinct assignment each time), and the same as the intact copy.
3. **The rest of the damaged quote.** From the second glyph of «وَٱلْيَوْمِ» onward, the quote's formatting survived, and it matches those occurrences glyph for glyph.

The book uses AGA Arabesque F029 as the opening bracket of its glyph quotes 39 times and F028 as the closing one 41 times (the closing bracket of this very quote is F028).

### 5.5 The repair

`scripts/repair_doc.py` writes a repaired copy (`data/work/repaired/`); the original is never modified. It builds a new 512-byte formatting page for the 41 characters: the leading space formatted like the body text before it, the bracket as AGA Arabesque F029 formatted like the quote's closing bracket, the spaces like the quote's other spaces, and each glyph in its Othmani font with the formatting of the quote's other glyphs (size, colour, bold, language), all copied byte for byte from runs of the same paragraph. Revision-save ids are left out so the page fits; they do not affect how text looks or reads. The page goes into page 469 of the WordDocument stream, which nothing references (it lies among the formatting pages and looks like one left over from an earlier save), and entry 198 is pointed at it. In total 344 bytes of the file change; its size and structure do not.

The script refuses to run on any other file (it checks the SHA-256 of the original) and asserts every assumption: that entry 198 is the only broken one, that the 41 characters are the expected ones, that the intact copy has these fonts and this bracket, and that the copied runs are what they are taken for.

### 5.6 Verification

- The script re-reads its output: every bin-table entry is now valid, the text is identical to the original's (236,984 characters), and the new page reads back with the intended fonts.
- Word opens the repaired copy normally, without any validation bypass: 1,164 paragraphs, 103 footnotes.
- Word's own plain text of the repaired copy equals the main text stored in the original file, 230,787 characters, paragraph for paragraph (933 of 933 paragraphs; Word ends table cells with an extra paragraph mark, which is the only difference before normalizing).
- The copy then went through the normal pipeline (`word_export.ps1`, `extract_text.py`, `check_extract.py`) with the other 115 books; results in 5.7.

### 5.7 Result

In the full run with the other 115 books, the acceptance check passes for this book as for every other: main text and all 103 footnotes, 0 words missing, 0 extra. It holds 930 paragraphs, 156 table-cell paragraphs (its table of contents is a table) and 117 footnote paragraphs. All 54 of its Quran quotes are identified exactly, including the repaired one, which now reads «لقوله تعالى: ﴿لَّا تَجِدُ قَوْمًا يُؤْمِنُونَ بِٱللَّهِ وَٱلْيَوْمِ ٱلْـَٔاخِرِ يُوَآدُّونَ مَنْ حَآدَّ ٱللَّهَ وَرَسُولَهُۥ﴾ قلت: …». Its 67 honorifics are written out. One quote is listed for information only: the glyphs of «وَقُلِ ٱلْحَقُّ» (18:29) lack the connecting kasra, as these glyphs do in 125 of the 126 quotes where they occur; the output has Tanzil's text.

**Lesson.** When a file will not open, read it at the binary level before writing it off. Here the container and the text were sound; the damage was one 4-byte index entry and the formatting page it should have pointed to. A repair that changes formatting only, rebuilt from evidence and verified by Word, keeps the book in the corpus without changing a word of it.

## 6. Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-10-24 | Answers are the Sheikh's text, word for word; never summarized | any generated sentence would be spoken in his voice |
| 2026-10-24 | Questions may come in any language; the answer is always his Arabic text. A translation may be shown as text, labelled as machine translation, and is never spoken in his voice | same |
| 2026-10-24 | The old system prompt's exceptions (majority view, calculations, "agreed" matters, free advice) are not carried over | they conflict with the core rule |
| 2026-10-24 | `clean_txt` is not used; the text is extracted again from the Word files | section 3 |
| 2026-10-24 | Quran quotes are written with Tanzil's Uthmani text of exactly the quoted words; where the source misquotes, the correct text is used and the quote flagged | a misquote must never be read out as Quran |
| 2026-10-24 | Fatawa containing any of the 19 flagged quotes are left out of the records; the 109 repaired quotes stay | section 4.7 |
| 2026-10-24 | Scope: his fatawa and treatises go in; clean data first | Hashem: the base should be complete, and correct before anything is built on it |
| 2026-10-24 | The video fatawa are left out for now | their Whisper transcripts are machine-made and not trusted |
| 2026-10-24 | Duplicates: keep the newest edition of each fatwa; where that is a 2022–23 file marked `تحت الإجراء`, keep the 2020–21 copy. Fatawa found only in a `تحت الإجراء` file are kept | in-progress files are not final, but the Sheikh's team gave us these files |
| 2026-10-24 | Specific personal cases go to a person, unless a fatwa matches every fact (almost never). The bot may offer related fatawa from his books, verbatim and cited, but never a ruling that is not in his books | a fatwa answers its asker's facts; a case that differs may need a different ruling |
| 2026-10-24 | In those cases the bot may add AI-written commentary on the related fatawa: text on screen only, labelled as AI-written, never spoken in his voice, never itself a ruling | the one exception to "the model only chooses"; like machine translation, it is kept visibly apart from his words. Generated text can be steered by a manipulated question, so the label and the separation are what protect it |
| 2026-10-24 | Front end: the ElevenLabs agent for now (custom LLM pointing at this backend), our own app later | the agent exists; our own app later allows reviewed, cached audio |
| 2026-10-24 | `التعددية السياسية.doc` is used through the repaired copy | section 5 |
| 2026-10-24 | Standalone books: his single-author books go in as sections, others' forewords left out; the two books co-authored with Dr. Abdullah al-Muslih (and three files excerpted from one of them) are left out; of `الصارم` (his abridgment of Ibn Taymiyya) and `المواجهة` (a multi-speaker debate) only his own parts go in, and the same rule covers the debate transcript later found in `تهافت العلمانية` and documents appended to his books; the two interviews become question-answer records; five files that name no author are held until the Sheikh's team confirms them (changed the same day, below) | only text that is his may be read in his voice; section 9 has the evidence (author lines, signed prefaces, shared paragraphs) |
| 2026-10-24 | The five files that name no author are left out rather than held | Hashem: there is plenty of his own work without them |
| 2026-10-24 | `حكم الدين في من تطاول على النبيين` is used in full, including the 19% of it that also appears in `الصارم` | Hashem: what is in his book goes in |
| 2026-10-24 | Answers reworded between editions need no review; the newest copy stays | both wordings are his. Of the 12 pairs that differ most, 4 changed the ruling between the 2011–17 volumes and the 2020–21 files; keeping the newest gives his later view ([segmentation.md](segmentation.md#limits)) |

## 7. Open questions

For the Sheikh's team:
- Which parts of the two co-authored books are his? They are left out until then.

For a person to review (lists in `data/work/records/`):
- 165 exchanges of the extremism dialogue (`نهائي تطرف`), split by formatting;
- 26 encyclopedia records held (doubtful Quran quotes, articles, quoted fatawa).

For Hashem (2026-10-25):
- Which LLM does step 4's final check use, and whose API key and billing?
- Where an in-progress 2022–23 copy gave way to the 2020–21 one, 13 copies differ noticeably ([segmentation.md](segmentation.md#limits)): should the newer copy be used in those?

Answered on 2026-10-24 (section 6): the five files without an author line, the passages `حكم الدين` shares with `الصارم`, and the 54 reworded answers.

One point to plan for: with the ElevenLabs agent, every answer is synthesized live, so the plan to review each passage's audio before release, Quran pronunciation included (step 5), only fully applies in our own app.

## 8. Step 2a: one record per fatwa (the encyclopedia)

Full write-up: [segmentation.md](segmentation.md).

**Question.** Where does each fatwa begin and end, which parts of the books are not fatawa, and which copy of a fatwa that appears in several editions should the assistant use?

**Material.** The 80 files of the encyclopedia: the 32 volumes of 2011–2017, the 25 chapter files of 2020–21 and the 23 of 2022–23, about 265,000 paragraphs. The standalone books and treatises are step 2b.

### 8.1 Boundaries

A fatwa runs: title, the asker's question, «الجواب» on a line of its own, the basmala and «الحمد لله والصلاة والسلام على رسول الله…», the answer, and «والله تعالى أعلى وأعلم». The «الجواب» lines (21,718) are reliable anchors. The work is to find where one answer ends and the next title begins. A first version that split after the last closing formula was checked by reading samples of every kind of record. The review found the following problems, each fixed by a rule backed by a measurement:

- **Titles have a form per file.** Each file sets its titles consistently, but the files differ (numbered `heading 2`, `heading 3`, `عنوان2`, an outline level). The script learns each file's form from the paragraphs that follow the Sheikh's closing formula, and the last title of that form before an anchor starts the next fatwa. List numbers count only as the next number in sequence, because lists inside answers restart at 1.
- **Askers write closing formulas too.** «والله أعلم», and sometimes his full formula, end some questions. That had cut questions in half. Only his formula and its known variants and typos count, and a formula after a title is the asker's (7 cases). Title-styled paragraphs inside answers occur in 14 of 21,711 records, so letting the title form win is safe.
- **Plain-paragraph titles** (a third of the titles in some 2020–21 files) are found by the closing formula. Where that is missing too, they are found by their measured shape: 97% end without punctuation and 99.97% have at most 20 words (9 cases).
- **Editors' notes** («هذه الفتوى مكررة مع سابقتها», «إلى هنا»), some set in a heading style, are left out of the text and listed with their record (33). They are not the Sheikh's words.
- **Two-paragraph titles, numbers on their own line, ornaments and chapter headings** («***», «كتاب الصلاة») are handled so that no title is lost or invented. The chapter of each fatwa in the volumes comes from those headings.
- **Quoted fatawa.** The Sheikh's own answers open with his formula: 21,684 of 21,711, plus 22 one-line answers in a list of short questions. The 5 that do not are other scholars' fatawa that had become records of their own (Hani al-Jubair, Rashid Rida) or two of his one-line answers. They are held, so that no other scholar's words are read in his voice.

**Check.** Every non-empty paragraph of the 80 files is in exactly one record or one listed part (234,091 in 21,720 records, 30,884 in 816 parts: front and back matter, chapter headings, ornaments, tables of contents). The script refuses to finish otherwise.

### 8.2 Copies across editions

The editions overlap heavily: 7,895 of the volumes' 10,123 fatawa have a copy in the 2020–21 files, and 942 of the 2,283 fatawa in the 2022–23 files (41%) repeat a 2020–21 one. Measured on known pairs, copies share 90–100% of their question's words and 50–100% of their answer (answers are revised and often extended: 580 characters became 3,435). Different fatawa can share answer text, because the Sheikh reuses paragraphs and council resolutions, but their questions share under 15%. So two records are one fatwa when their questions match and their answers are related, or when the question is identical. Links are made strongest first, never join two records of the same file into one group, and never join the parts of a series («(1)», «(2)»).

The kept copy follows the decisions: the newest edition; a 2020–21 copy instead of an in-progress 2022–23 one (393 times); in-progress copies kept where no 2020–21 copy exists (510); a held copy passed over for a usable one.

### 8.3 Result

| | |
|---|---|
| Records in all editions | 21,711 fatawa, 9 articles |
| Held for review, not used | 26: 12 with a flagged Quran quote, 9 articles (titled texts without «الجواب», some of mixed authorship), 5 not opening with his formula |
| Distinct fatawa | 12,789 |
| **Corpus (kept copies)** | **12,779**: 1,869 from 2022–23, 8,732 from 2020–21, 2,178 found only in the volumes |
| Listed | 54 fatawa whose answer was reworded between editions (newest kept; no review needed, section 6); 79 answers given to two different questions (kept as separate fatawa) |

Each corpus record carries its title, question, answer, footnotes, chapter, source, its other copies, the Quran and honorific spans, and a normalized copy of its text for search only. That normalized copy is the last item of the original step 2 plan.

## 9. Step 2b: the standalone books

Full write-up: [segmentation.md](segmentation.md#the-standalone-books-segment_bookspy).

**Question.** Which of the 33 books outside the encyclopedia are the Sheikh's own words, and how do they divide into passages the assistant can cite?

**Authorship first.** Before anything was split, each book's title page, signed prefaces and shared paragraphs were read. Two books are co-authored with Dr. Abdullah al-Muslih, and three smaller files turned out to be excerpts of one of them (105 of 107, 68 of 72 and two-thirds of their paragraphs). `الصارم` is his abridgment of Ibn Taymiyya. Two books contain whole debate transcripts with other speakers, two have forewords by others, and several append others' fatawa or council resolutions. Five files name no author. The decisions (section 6) follow from this: 18 of his books go in, two in part, two interviews as question-answer records, and the rest is left out (the five without an author were first held, then left out). The stretches of others' text inside his books are named in a reviewable table and left out. One finding needed care: in `المواجهة`, the profiles of the secularist debaters state their positions as headlines, which would sound like his rulings if read in his voice. They are left out with the rest of the debate.

**Method.** These books mark headings by formatting (centred, larger, bold) rather than styles, so the extraction now records each paragraph's alignment, bold share and font size. The text is unchanged and the acceptance check still passes. A heading is a short paragraph set apart from the book's own body text, and its level follows its size. Books of questions become question-answer records, like the fatawa: the 108 questions of `تساؤلات أمريكية`, the 82 issues of `المسائل الأساسية` with their «أفكار أولية حول الإجابة», and the 130 «*»/«الجواب:» exchanges of `تكلم الدعاة`. Each step was checked by reading every book's list of sections and parts. That review caught a debate transcript taken for his text, a foreword kept while his own introduction was dropped, an interview's framing taken for questions, contents lines taken for questions, and chapters a file repeats twice; each was fixed and re-checked.

**Result.** 859 records from the books (374 sections, 485 questions and answers), 694 usable. The 165 exchanges of `نهائي تطرف`, a dialogue whose questions are not reliably marked, are held for a person to check. With 12 copies of already-kept records left out, **the corpus is 13,461 records: 12,779 fatawa and 682 book records**, every one the Sheikh's own text with its source.

## 10. Step 3: the search index

Full write-up: [retrieval.md](retrieval.md).

**Question.** Given a question in the user's own words, in any language or dialect, which records may answer it? Search only proposes candidates; step 4 decides whether one of them answers, and the answer is always a record's own text. So the measure that matters is whether the right record is among the first 20 to 50 candidates.

**Method.** Each record is searched through its title and question, and through its answer cut into 21,599 passages of up to 220 words. A passage is a span of the answer, so the one that matched can be quoted exactly. Two kinds of search were compared: keyword search (BM25) over normalized Arabic words with four ways of stemming them, and three multilingual embedding models that run locally on Hashem's GPU, so no text leaves the machine and nothing is billed. Rankings are combined by reciprocal rank fusion.

**Test set.** None existed (the Golden Dataset has 4 questions), so one was made: 150 records drawn at random (books oversampled), and for each, three writers who never saw the search wrote what an ordinary person would ask. That is a full question (a quarter of them in Egyptian, Levantine, Gulf or Maghrebi dialect), a short search-box form and an English question: 450 questions (`eval/retrieval.jsonl`). 100 records were used for every choice; 50 were held out and run once at the end. Only the record a question was written for counts as found, so the scores are a lower bound.

**Findings.**
- Stemming helps keyword search (MRR +0.085 over none); Snowball's Arabic stemmer beats light10, the standard light stemmer (+0.041, 95% interval +0.004 to +0.079).
- Embeddings find far more than keywords: on full Arabic questions the record comes first 68% of the time (keywords: 44%), and English questions find the Arabic records nearly as well. Of the three models, bge-m3 (MIT licence) and e5-large-instruct (MIT) are close and complementary; Qwen3-Embedding-0.6B was weaker and 13 times slower here, and was dropped.
- Matching the user's question to the asker's question (title and question) carries most of the signal; the answers' passages add recall, and are what finds book sections.
- Fusing with equal weights and the usual constant (k = 60) raised recall but pushed good first places down. The chosen search fuses both models over title and question (weight 1) and over passages (0.5) with keyword search over title and question (0.5), at k = 10.

**Result.** On the held-out test, averaged over the three kinds of question: the record comes first for 51% of questions, is in the first 10 for 83%, the first 20 for 85% and the first 50 for 95% (MRR 0.624). On dev: 54%, 86%, 92%, 97% (MRR 0.661). Fatawa are found best (first 20: 89–98%). Book sections, whose headings say little, are the weak point. All four Golden Dataset questions return their fatwa first. Of the 46 questions (of 450) whose record was not in the first 20, 26 had another fatwa on the same question first and 18 related records; 2 found nothing relevant. A search takes 76 ms on the GPU and 384 ms on the CPU.

**Problems met.** An embedding build stalled when its progress bars went through PowerShell's `*>` redirection, and ran normally without it. Six interview records had empty titles (their question began with an empty line); fixed in `segment_books.py`, and only those titles changed. In PowerShell, an empty `$env:` value removes the variable, so a run meant for the CPU used the GPU. On the CPU, transformers kept the models in half precision, which is slow there, so `load_model` now uses float32. An interrupted build lost its record of finished parts, so the index metadata is now written after each part.

**Decision** (2026-10-25, from the measurements): the search described above is the default (`search.DEFAULT`); `build_index.py` builds exactly its parts.

## 11. Next: step 4, choosing the answer

Take the first 30 to 50 candidates (95–97% contain the record), rerank them with a multilingual cross-encoder, and have a strict LLM check say which record, if any, answers the question; otherwise the fixed "no fatwa found" message. For a long book section, the passage that matched is the natural unit to quote verbatim. The review lists (section 7) can go to the Sheikh's team in the meantime.

## Appendix A: reproducing the data

From the repository root on Hashem's PC, with the 116 Word files in `data/raw/sawi_material` and Tanzil's text in `data/raw/quran/quran-uthmani.txt`:

```
python -I -X utf8 scripts\repair_doc.py --src "data\raw\sawi_material\التعددية السياسية.doc" --out "data\work\repaired\التعددية السياسية.doc"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_export.ps1 -InputDir data\raw\sawi_material -OutDir data\work\word
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\word_export.ps1 -InputDir data\work\repaired -OutDir data\work\word -Force
python -I -X utf8 scripts\extract_text.py --word data\work\word --quran data\raw\quran\quran-uthmani.txt --out data\work\extract
python -I -X utf8 scripts\check_extract.py --word data\work\word --extract data\work\extract
python -I -X utf8 scripts\segment.py --extract data\work\extract --out data\work\records
python -I -X utf8 scripts\segment_books.py --extract data\work\extract --out data\work\records
python -I -X utf8 scripts\dedupe.py --records data\work\records
.venv\Scripts\python -I -X utf8 scripts\build_index.py --records data\work\records --out data\work\index
.venv\Scripts\python -I -X utf8 scripts\eval_retrieval.py --index data\work\index --queries eval\retrieval.jsonl --split test --configs eval\configs\test_final.json
```

The first export records the damaged file as an error; the second replaces that entry with the repaired copy. The corpus is `data/work/records/corpus.jsonl`. `build_index.py` builds the parts the chosen search uses; for the whole comparison of section 10, add `--stemmers none,light10,light10-keepwaw,snowball --models bge-m3,e5-large-instruct` and run `eval_retrieval.py --split dev` with each file in `eval/configs/`. The test questions are in git; `sample_targets.py` (which records) and `merge_queries.py` (joining the writers' files) show how they were made. The `clean_txt` check (section 3) is reproduced with `verify_txt.py` and `overlap.py` as shown in [data-verification.md](data-verification.md).

## Appendix B: repository map

| Path | What |
|---|---|
| `CLAUDE.md` | project rules, sources, plan, decisions and open questions |
| `docs/report.md` | this report |
| `docs/data-verification.md` | step 1a in full |
| `docs/extraction.md` | step 1b–1c in full |
| `docs/segmentation.md` | step 2 in full |
| `scripts/word_export.ps1` | reads every source through Word: plain text, footnotes, text boxes, XML |
| `scripts/verify_txt.py` | checks a text conversion (here `clean_txt`) against Word's reading |
| `scripts/overlap.py` | paragraph overlap between sources |
| `scripts/extract_zip.py` | unpacks Drive zips with Arabic file names intact |
| `scripts/quran_glyphs.py` | glyph tables, honorific fonts, Tanzil index, quote identification |
| `scripts/extract_text.py` | Word XML → JSON and text per book, and the review report |
| `scripts/check_extract.py` | acceptance test of the extraction against Word's own text |
| `scripts/repair_doc.py` | repaired copy of `التعددية السياسية.doc` |
| `scripts/find_glyph_fonts.py` | where given glyph words occur in the books, and in which fonts |
| `scripts/segment.py` | the encyclopedia → one record per fatwa, non-fatwa parts, review flags, coverage check |
| `scripts/segment_books.py` | the standalone books → sections and question-answer records, per the authorship table, with others' text left out |
| `scripts/dedupe.py` | copies of each fatwa across editions → the corpus, one kept copy each, plus the book records, each with a search copy of its text |
| `scripts/build_index.py` | the corpus → the search index: passages, keyword-search matrices, embeddings |
| `scripts/search.py` | search over the index (text normalization, stemming, BM25, embeddings, fusion); used by the evaluation and, later, the answer service |
| `scripts/eval_retrieval.py` | measures search against the test questions |
| `scripts/sample_targets.py`, `scripts/merge_queries.py` | how the test questions were made: the records picked, the writers' files joined |
| `eval/retrieval.jsonl` | the 450 test questions (150 records, dev and test splits) |
| `eval/configs/` | the search configurations compared in each round |
| `docs/retrieval.md` | step 3 in full |
| `requirements.txt` | the Python packages of step 3 |

## Appendix C: glossary

- **Fatwa (pl. fatawa):** a scholar's answer to a religious question; here, the Sheikh's written answer to a question someone asked him.
- **Tashkeel:** Arabic vowel marks.
- **Uthmani text:** the Quran's standard script, as in the Madinah mushaf; Tanzil publishes it as Unicode text.
- **Glyph font:** a font whose characters draw pieces of the mushaf (HQPB1–5, Othmani1–5) or symbols (AGA Arabesque); the stored characters mean nothing without the font.
- **Honorific:** a formula after a name (صلى الله عليه وسلم, رضي الله عنه, …), often drawn as one glyph.
- **CFB (compound file):** the container format of `.doc` files, a small file system of streams.
- **Piece table:** the part of a `.doc` file that says where the text is stored.
- **BM25:** the standard keyword-search score: a record scores higher the more of the question's rarer words it contains, with diminishing returns for repeats and a correction for length.
- **Stemming:** reducing a word to a common form, so that «بالزكاة» and «الزكاة» match; a light stemmer only strips prefixes and suffixes.
- **Embedding:** a vector that a neural model computes for a text, close to the vectors of texts with similar meaning, in any language the model knows.
- **Reciprocal rank fusion (RRF):** combining rankings by adding w/(k + rank) for each list a record appears in.
- **R@k, MRR:** the share of questions whose record is among the first k results; the mean of 1/rank of that record.
- **FKP and bin table:** a `.doc` stores character formatting in 512-byte pages (FKPs); the bin table maps each stretch of text to its page.
- **Office file validation:** Office's check of a binary file's structure before opening it; files that fail are not opened.

# Sawy Fatwa Assistant

A voice chatbot that answers people's questions **only** with the fatawa of Dr. Salah Al-Sawy (أ.د. صلاح الصاوي), spoken in his own voice cloned in ElevenLabs. The Sheikh asked for this project.

**Status:** the voice is cloned ("sawy v2"). An ElevenLabs agent prototype answers using ElevenLabs' built-in knowledge-base RAG, with an LLM writing the answers (Gemini Flash in the Nov 2025 notes). Those answers are generated rather than quoted, and testing was weak. This repo builds our own retrieval pipeline (the "professional RAG" route in the team notes) and keeps ElevenLabs for the voice. The text of all 116 books has been extracted and checked (step 1 below; one damaged file was repaired first) and split into records (step 2): a corpus of 13,461 records of the Sheikh's own text. Search over it is built and measured (step 3): the right record is among the first 20 candidates for 85% of held-out test questions and the first 50 for 95%. Choosing the answer (step 4) is next. Every step is written up in `docs/report.md`.

## Core rule: only the Sheikh's words

Everything the bot says comes out in his voice, so any generated sentence would sound like him saying it.

1. **Answers are his text, verbatim**: the matching fatwa, or a verbatim excerpt that keeps the ruling and its conditions. No LLM paraphrase, summary, translation, or merging several fatawa into a new answer.
2. **Abstain when there is no clear match** with a fixed "no fatwa found" message. Never fall back to general knowledge, "the majority view", inheritance/zakat calculations, or free-form advice.
3. **Always cite** the collection, chapter/book, fatwa title, and the original question it answered, so the user can judge whether it fits their case.
4. **The LLM only chooses; it never writes.** It normalizes the question, ranks candidates, and says which fatwa (if any) answers it. Because its output is a fatwa ID or "none", a prompt-injected question can at worst pick the wrong fatwa or none; it can never put new words in his mouth. Anything that isn't a fatwa (greeting, "not found", disclaimers) comes from a short list of fixed, pre-approved messages.

One exception (decided 2026-10-24): when a question is about the asker's own case and goes to a person (see Decisions), the bot may show AI-written commentary on the related fatawa. It is text on screen only, labelled as AI-written and not the Sheikh's words, never spoken in his voice, and never itself a ruling. Like machine translation, it is kept visibly apart from his text. That channel is generated text, so rule 4's protection does not cover it; the label and the separation have to.

The older system prompt in Drive (`Prompt Engineering/Prompt`) allowed exceptions: majority opinion, calculations, "universally agreed" matters, and free advice. They conflict with this rule and are intentionally not carried over.

## Accounts and cost: read before acting

- The **ElevenLabs account belongs to the project leader**, not Hashem. **Ask before anything that spends credits** (TTS, agent test conversations, cloning or editing voices, anything else billable; if unsure, ask) and give a rough estimate. TTS bills per character, and one fatwa can run to thousands. Browsing the dashboard is fine. Don't change the existing agent's settings without asking; it is the team's working prototype.
- Voice: **"sawy v2"**. Its voice ID and all API keys go in `.env` (gitignored), never in code or commits.
- Keep this repo **private**: it links to the team's Drive and will hold the Sheikh's texts.

## Sources

| What | Where | Notes |
|---|---|---|
| Original books (`.doc`/`.docx`) — **the source of truth** | Drive `sawi_material`: https://drive.google.com/drive/folders/18PA1HGQ28p13M7sZQDInA_0wMhGo6T8B | 116 Word files (2003–2023), plus folders `Progress/`, `Prompt Engineering/`, `YouTube Fatwas/`. The fatwa encyclopedia (`موسوعة فتاوى المغتربين`) comes in three editions: 32 volumes `01`–`32 book.doc` (saved 2011–2017; each volume spans all chapters, fatawa numbered continuously), 25 chapter files `NN <chapter>.doc` (2020–21; chapter 01 as `01-1`…`01-3`) and 23 chapter files `NN (2) <chapter>.docx` (2022–23, 9 marked `تحت الإجراء`; 41% repeat a 2020–21 fatwa). Volumes 33/35/36 are empty templates; ~33 standalone books and treatises. Editions overlap heavily (deduped in step 2). Chapter numbers 16–18 differ between the 2020–21 and 2022–23 files (match by content, not number). `التعددية السياسية.doc` is damaged (Word and Google Docs refuse it; Drive has no other version): `scripts/repair_doc.py` writes a repaired copy, see `docs/extraction.md`. |
| Video fatawa | Drive `sawi_material/YouTube Fatwas/` | `metadata` sheet: 1,308 clips (video ID, Arabic title, duration in seconds, URL) from his live fatwa programmes, 2020–2024, each titled with one question, mostly under 4 minutes. `open_ai_whisper_1/`: Whisper machine transcripts per clip (`<id>-dn.json`, `<id>-dn.srt`, made by a teammate in Feb 2025). **Left out for now** (decision 2026-10-24): machine transcripts are not verbatim text and are not trusted. |
| Converted text (Dec 2025) — **do not use** | Drive `clean_txt` (Hashem): https://drive.google.com/drive/folders/1ZqNNZKHYjJP1768VDBWNyEJCUGrl68SP | 115 `.txt` files, one per source. Verified 2026-10-24 against Word (`docs/data-verification.md`): all 29,639 footnotes dropped, most tables dropped, runs tagged with a symbol font dropped (whole sections lost in some books), Quran quotes replaced by the full verse, duplicated or deleted, two files failed. The plain prose is otherwise exact. |
| Quran text | Tanzil Uthmani v1.1, `data/raw/quran/quran-uthmani.txt` (downloaded 2026-10-24 from https://tanzil.net/download/) | Used to identify each quote typed in glyph fonts and to write it as text. Terms accepted with Hashem's OK: verbatim copies only, and the app must credit the Tanzil Project with a link to tanzil.net. |
| Fatwa website | https://fatawaalsawy.com | Large archive. The team asked the site manager for the data; prefer an export over scraping. |
| Voice training audio | `sawi.mp3`, ~2 h of khutbahs: https://drive.google.com/file/d/1DcygMVxmADH2B7EGxDp54cTsoOG6Hql8 | Already used for the clone. |

What's inside the Word sources:
- Fatawa (e.g. `03 (2) كتاب العلم.doc`) run: title line → the asker's question → `الجواب` → `بسم الله الرحمن الرحيم` → `الحمد لله والصلاة والسلام على رسول الله…` → answer → `والله تعالى أعلى وأعلم.` Footnotes (hadith sources etc.) are real Word footnotes; their reference marks sit inside literal parentheses `(…)`. Books open with a header and end with a table of contents (`الفهرس`).
- **Quran is not Unicode text.** Verses are glyphs in Quran fonts: `<w:sym>` characters in HQPB1–5, or private-use characters (U+F0xx) in Othmani1–5 (same codes), with ornamental brackets (HQPB2 or AGA Arabesque). Word's plain text shows them as `(` or nothing. HQPB1–5 are installed on Hashem's PC. `scripts/quran_glyphs.py` reads each quote's letters, finds them in the Tanzil text (cited verses first) and writes Tanzil's words for exactly that span; see `docs/extraction.md`. The Sheikh often quotes only part of a verse.
- **Honorifics are glyphs too.** AGA Arabesque symbols (`U` عز وجل, `r`/`e` صلى الله عليه وسلم, `t` رضي الله عنه …) and the font `CTraditional Arabic`, which draws honorifics on ordinary characters (`ب` رضي الله عنهما, `ل` رضي الله عنها, `:` رحمه الله …). Read as plain text they become stray letters.
- Some runs carry a symbol font (AGA Arabesque) in the Latin-font slot while containing ordinary Arabic; any filter on font names will drop real text. `AF_Najed`, `AL-Mateen` and the like are ordinary display fonts.

Reading the sources: `scripts/word_export.ps1` drives Word (read-only, macros off, never saves; Word's SaveAs hangs on these files) and writes main text, footnotes and the flat XML. `scripts/extract_text.py` turns the XML into the text we use (`data/work/extract/`), and `scripts/check_extract.py` is its acceptance test against Word's own text. `scripts/segment.py` and `scripts/dedupe.py` turn that into records (`data/work/records/`). `scripts/build_index.py` builds the search index (`data/work/index/`), `scripts/search.py` searches it, and `scripts/eval_retrieval.py` measures it against the test questions in `eval/retrieval.jsonl`. `scripts/verify_txt.py` was used to check `clean_txt`.

Everything before the index uses only the standard library. The index scripts need the project venv (`.venv`, gitignored; setup in `requirements.txt`: PyTorch with CUDA for the RTX 3070, sentence-transformers, PyStemmer): run them with `.venv\Scripts\python -I -X utf8`. The embedding models (4.3 GB) live in `data/models/`, which `search.py` sets as `HF_HOME`.

## Planned pipeline

1. **Ingest** (done, `docs/extraction.md`): `scripts/repair_doc.py` for the one damaged file, `scripts/word_export.ps1` (Word is installed on Hashem's PC; LibreOffice is not), then `scripts/extract_text.py`, not `clean_txt`. Keeps all text, tables, list numbers and footnotes; Quran glyph quotes become Tanzil's text of exactly the words quoted, honorific glyphs become their words. `scripts/check_extract.py` is the acceptance test: every word of Word's own text, in order, nothing extra. Quotes it could not take verbatim are listed in `data/work/extract/report.md`.
2. **Segment** (done, `docs/segmentation.md`): `scripts/segment.py` (encyclopedia) and `scripts/segment_books.py` (standalone books, per the authorship table in it) → `scripts/dedupe.py` → `data/work/records/corpus.jsonl`: **13,461 records**, 12,779 distinct fatawa and 682 book records (sections, and question-answer records from his books of questions and the interview). Held for review, never used until checked: 26 encyclopedia records, 165 dialogue records of `نهائي تطرف`. Review lists: `report.md`, `books.md`, `dedupe.md` in that folder. The notes below are the original plan; `docs/segmentation.md` has what was actually done.
   - Boundaries: a fatwa runs title → asker's question → `الجواب` → answer → `والله تعالى أعلى وأعلم`. In the 2020–23 chapter files titles carry Word heading styles (`heading 3`); check what the 2011 `book` volumes, the 2020–21 chapter files and the standalone books use before relying on styles. Front matter, introductions and tables of contents are not fatawa.
   - Record: `{id, title, question, answer, notes, collection, chapter, source_file}`, text exactly as extracted. Footnotes go with the fatwa that references them; keep the `quran` and `honorific` spans (TTS needs the Quran spans).
   - Leave out every fatwa that contains one of the 19 flagged quotes (span `status` `unresolved`, `ambiguous` or `corrected`); list them in the segmentation report.
   - Dedupe: most fatawa exist in several editions (`NN book.doc` 2011, `NN <chapter>.doc` 2020–21, `NN (2) <chapter>.docx` 2022–23, volumes 24–32). Keep the newest copy, except that a copy in a file marked `تحت الإجراء` gives way to its 2020–21 copy (see Decisions), and record where the others are.
   - Check: every block ends up in exactly one record or in a listed non-fatwa part; nothing is dropped silently.
   - Then a separate normalized copy for search only: strip tashkeel, tatweel and `()`, and unify ا/أ/إ/آ, ى/ي, ة/ه.
3. **Index** (done, `docs/retrieval.md`): `scripts/build_index.py` → `data/work/index/`, searched by `scripts/search.py`. Each record is searched by its title and question and by its answer in passages (≤ 220 words; spans of the answer, so the match can be quoted verbatim). Chosen on measurements: reciprocal rank fusion (k = 10) of bge-m3 and multilingual-e5-large-instruct embeddings over title+question (weight 1) and passages (0.5), plus BM25 with Snowball stems over title+question (0.5, Arabic questions only). Models run locally (no API, no cost). Test set: `eval/retrieval.jsonl`, 450 questions written for 150 random records (dialects, short forms, English), measured by `scripts/eval_retrieval.py`; held-out test: R@20 0.85, R@50 0.95, MRR 0.624, lower bounds, since another fatwa on the same issue counts as a miss. Book sections are found less reliably than fatawa. Search takes 76 ms on the GPU and 384 ms on the CPU.
4. **Select**: take the top 30–50 candidates (`search.Index.search`), rerank, then run a strict LLM check of whether a candidate answers the question. A match returns the verbatim fatwa with its citation; no match returns the abstain message. For a long book section, quote the passage that matched (each hit carries it). Translating a non-Arabic question into Arabic first may let keyword search help it (untested).
5. **Voice**: ElevenLabs TTS ("sawy v2") on the verbatim text, cached by text hash so each passage is paid for once and can be reviewed before release. Quran quotations need special handling: mispronouncing Quran in his voice is unacceptable.
6. **Evaluate** with the Golden Dataset, paraphrases of existing questions (the source fatwa should come back), questions that must get the abstain message, and injection attempts. Target: zero non-Sheikh text in answers.

Front end (decided): the ElevenLabs agent for now, for voice in and out, pointed at this backend as a custom LLM; later our own app that calls TTS directly. Through the agent every answer is synthesized live, so step 5's cached, reviewed audio only fully applies in our own app; the agent phase needs its own plan for checking Quran pronunciation.

## Decisions

- **Verbatim only** (confirmed 2026-10-24): answers are the Sheikh's text word for word, never summarized.
- **Languages** (2026-10-24): people may ask in any language; the answer is always the Sheikh's Arabic text. Translation is either the user's own tool or an optional machine translation the bot shows as text, labelled as such. A translation is never spoken in his voice.
- **Quran text** (2026-10-24): quotes are written with Tanzil's Uthmani text of exactly the quoted words (Hashem accepted Tanzil's terms). Where the document's own quote is garbled or misses a word, the cited verses' correct text is used and the quote is flagged for review; it is never printed as a misquote.
- **Flagged quotes** (2026-10-24): the fatawa containing any of the 19 quotes that need a decision (1 unreadable, 6 with undecided vowels, 12 wrong in the source) are left out of the records entirely. The 109 repaired quotes (stray characters standing in for glyphs, words matched letter for letter) stay.
- **Scope** (2026-10-24): his fatawa and his treatises go in. Clean data first: the books are segmented and checked before anything is indexed. The video fatawa are left out for now: their Whisper transcripts are not trusted.
- **Duplicates** (2026-10-24): keep the newest edition of each fatwa. Where the newest copy is in a 2022–23 file marked `تحت الإجراء` (in progress; 9 files: chapters 04, 05, 07, 08, 10, 14, 15, 17, 21), keep the 2020–21 copy instead. Fatawa that exist only in a `تحت الإجراء` file are kept: the Sheikh's team gave us these files. Answers reworded between editions (54) need no review: both wordings are his, and keeping the newest gives his later view where it changed.
- **Specific cases** (2026-10-24): questions about a person's own case (a particular divorce, inheritance shares, …) go to a person, unless a fatwa matches every fact of the case, which is almost never. The bot may still offer related fatawa from his books, verbatim and cited, but never a ruling that is not in his books. It may add AI-written commentary on them as labelled on-screen text, never in his voice (the exception under the core rule).
- **Front end** (2026-10-24): the ElevenLabs agent for now; our own app later.
- **Standalone books, authorship** (2026-10-24): only text that is the Sheikh's own goes in.
  - His single-author books go in as sections; forewords by others (عبد الغفار عزيز in `تهافت العلمانية`, علي السالوس in `وقفات هادئة`) are left out. `دعاة لا قضاة` and `قراءة في كتاب دعاة لا قضاة` are the same file (his reading of that book); one copy is used.
  - Co-authored with Dr. Abdullah al-Muslih: left out (`ما لا يسع المسلم جهله`, `مالا يسع التاجر جهله`, and the excerpts of the latter: `البيوع وأحكامها`, `المضاربة وأحكامها`, `المعاملات الربوية والبدائل الشرعية`).
  - `الصارم` (his abridgment of Ibn Taymiyya's «الصارم المسلول») and `المواجهة بين الإسلام والعالمانية` (a debate with other speakers; preface by Dr. Muhammad Imara): only his own parts, where they can be told apart; the rest is listed as left out. The same rule covers what was found later: the 1992 debate transcript in `تهافت العلمانية`, the appendices of `وقفات هادئة` (others' fatawa and council resolutions) and the Hidaya association's fatwa in `فاعلم أنه لا إله إلا الله`.
  - Interviews `تكلم الدعاة` and `نهائي تطرف`: question-answer records (the interviewer's question, his answer); the framing text about him is left out.
  - No author line: left out rather than held for the team to confirm (Hashem: there is plenty of his own work): `أصول الإيمان`, `نهائي الطحاوية`, `وجيزالزكاة`, `من التطبيقات المعاصرة للزكاة`, `قضايا معاصرة`.
  - `حكم الدين في من تطاول على النبيين` is used in full, including the 19% of it that also appears in `الصارم`: what is in his book goes in.
- **Damaged source** (2026-10-24): `التعددية السياسية.doc` is used through the repaired copy from `scripts/repair_doc.py`, which rebuilds 41 characters' lost formatting (fonts of a 58:22 glyph quote) from an intact copy of the same verse earlier in the same paragraph, confirmed by the same words in 11 other books. The text itself is untouched (Word's text of the copy equals the text stored in the original).

## Open decisions (ask; don't assume)

- For the Sheikh's team: which parts of the two co-authored books are his (they are left out until then)?
- For a reviewer: the 165 held records of the extremism dialogue (`نهائي تطرف`), the 26 held encyclopedia records.

## Links

- Team notes ("Basic Documentation"): https://docs.google.com/document/d/1FLi4CSPaRdOqKcnQDqZfRuUAlQg4Nheq8FrJP4XV9Mk
- Old system prompt: https://docs.google.com/document/d/1FVYkRlmk0Edkh3xs233jujF0C6xSIbPDHtDdOpU8L_4
- Golden Dataset: https://docs.google.com/spreadsheets/d/1qPyczx6wLq5sj-0nzJMGZUsR36_T666uD_73crGa1js
- Earlier model tests: Gemini 2.0 Flash (weak) https://docs.google.com/spreadsheets/d/1wHQVW7DPXQPOBj9BprLput2qXApCOlr21rYGAT_yyOA, GPT-5 https://docs.google.com/spreadsheets/d/1KduUOR_d1fB1ZhkW7A0QAHxUf710JusTIfj6cFmBhEQ

## Conventions

- **Keep `docs/report.md` current.** It is the project's technical report, written like a research paper from step 0 onward: for each step, what was done, how, how it was checked, the numbers, problems met and decisions taken (with dates). Update it in the same commit as the work; the step documents (`docs/data-verification.md`, `docs/extraction.md`, …) hold the full detail.
- The books stay in Drive, not in git: everything under `data/` is gitignored (`data/raw/` downloads, `data/work/` derived files).
- Downloading from Drive: the Google Drive connector lists only files Hashem has opened (1 of the 116 sources), so use Chrome. Drive's select-all only covers rows that have loaded (scroll to the end first), and Chrome blocks repeat zip downloads in one tab; use a fresh tab per zip.
- UTF-8 everywhere. On Windows, run Python with `PYTHONUTF8=1` (or `-X utf8`); otherwise piped output and file I/O default to cp1252 and fail on Arabic. `python -I` leaves the script's folder off the import path, so scripts that import a sibling module add it themselves.
- Drive C: has only about 5 GB free. Keep large downloads and caches on D: (pip: set `TMP`, `TEMP` and `PIP_CACHE_DIR` to `data\tmp`; models: `data/models`).
- Don't send a long job's progress bars through PowerShell's `*>` redirection: an embedding build run that way made no progress in 14 minutes; without it, the same step took 86 seconds.
- PowerShell 5.1 drops empty arguments to programs: write `--models=`, not `--models ""`.

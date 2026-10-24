# Sawy Fatwa Assistant

A voice chatbot that answers people's questions **only** with the fatawa of Dr. Salah Al-Sawy (أ.د. صلاح الصاوي), spoken in his own voice cloned in ElevenLabs. The Sheikh asked for this project.

**Status:** the voice is cloned ("sawy v2"). An ElevenLabs agent prototype answers using ElevenLabs' built-in knowledge-base RAG, with an LLM writing the answers (Gemini Flash in the Nov 2025 notes). Those answers are generated rather than quoted, and testing was weak. This repo builds our own retrieval pipeline (the "professional RAG" route in the team notes) and keeps ElevenLabs for the voice.

## Core rule: only the Sheikh's words

Everything the bot says comes out in his voice, so any generated sentence would sound like him saying it.

1. **Answers are his text, verbatim**: the matching fatwa, or a verbatim excerpt that keeps the ruling and its conditions. No LLM paraphrase, summary, translation, or merging several fatawa into a new answer.
2. **Abstain when there is no clear match** with a fixed "no fatwa found" message. Never fall back to general knowledge, "the majority view", inheritance/zakat calculations, or free-form advice.
3. **Always cite** the collection, chapter/book, fatwa title, and the original question it answered, so the user can judge whether it fits their case.
4. **The LLM only chooses; it never writes.** It normalizes the question, ranks candidates, and says which fatwa (if any) answers it. Because its output is a fatwa ID or "none", a prompt-injected question can at worst pick the wrong fatwa or none; it can never put new words in his mouth. Anything that isn't a fatwa (greeting, "not found", disclaimers) comes from a short list of fixed, pre-approved messages.

The older system prompt in Drive (`Prompt Engineering/Prompt`) allowed exceptions: majority opinion, calculations, "universally agreed" matters, and free advice. They conflict with this rule and are intentionally not carried over.

## Accounts and cost: read before acting

- The **ElevenLabs account belongs to the project leader**, not Hashem. **Ask before anything that spends credits** (TTS, agent test conversations, cloning or editing voices, anything else billable; if unsure, ask) and give a rough estimate. TTS bills per character, and one fatwa can run to thousands. Browsing the dashboard is fine. Don't change the existing agent's settings without asking; it is the team's working prototype.
- Voice: **"sawy v2"**. Its voice ID and all API keys go in `.env` (gitignored), never in code or commits.
- Keep this repo **private**: it links to the team's Drive and will hold the Sheikh's texts.

## Sources

| What | Where | Notes |
|---|---|---|
| Original books (`.doc`/`.docx`) — **the source of truth** | Drive `sawi_material`: https://drive.google.com/drive/folders/18PA1HGQ28p13M7sZQDInA_0wMhGo6T8B | 116 Word files (2003–2023), plus folders `Progress/`, `Prompt Engineering/`, `YouTube Fatwas/`. Per fiqh chapter `01`–`23` there are usually three files: `NN book.doc` (2011), `NN <chapter>.doc` (2020–21) and `NN (2) <chapter>.docx` (2022–23 additions, some marked `تحت الإجراء`), plus `24`–`32 book.doc`, volumes 33/35/36 (headings only) and ~30 standalone books. Expect heavy overlap between variants; dedupe before indexing. `التعددية السياسية.doc` will not open in Office (file validation error). |
| Converted text (Dec 2025) — **do not use** | Drive `clean_txt` (Hashem): https://drive.google.com/drive/folders/1ZqNNZKHYjJP1768VDBWNyEJCUGrl68SP | 115 `.txt` files, one per source. Verified 2026-10-24 against Word (`docs/data-verification.md`): all 29,639 footnotes dropped, most tables dropped, runs tagged with a symbol font dropped (whole sections lost in some books), Quran quotes replaced by the full verse, duplicated or deleted, two files failed. The plain prose is otherwise exact. |
| Fatwa website | https://fatawaalsawy.com | Large archive. The team asked the site manager for the data; prefer an export over scraping. |
| Voice training audio | `sawi.mp3`, ~2 h of khutbahs: https://drive.google.com/file/d/1DcygMVxmADH2B7EGxDp54cTsoOG6Hql8 | Already used for the clone. |

What's inside the Word sources:
- Fatawa (e.g. `03 (2) كتاب العلم.doc`) run: title line → the asker's question → `الجواب` → `بسم الله الرحمن الرحيم` → `الحمد لله والصلاة والسلام على رسول الله…` → answer → `والله تعالى أعلى وأعلم.` Footnotes (hadith sources etc.) are real Word footnotes; their reference marks sit inside literal parentheses `(…)`. Books open with a header and end with a table of contents (`الفهرس`).
- **Quran is not Unicode text.** Verses are glyphs in Quran fonts: `<w:sym>` characters in HQPB1–5, or private-use characters (U+F0xx) in Othmani1–5, with AGA Arabesque ornamental brackets. Word's plain text shows them as `(` or nothing. Decoding needs the glyph → text mapping; the cited `[سورة: آية]` follows each passage, but the Sheikh often quotes only part of a verse.
- Some runs carry a symbol font (AGA Arabesque) in the Latin-font slot while containing ordinary Arabic; any filter on font names will drop real text.

Reading the sources: `scripts/word_export.ps1` drives Word (read-only, macros off, never saves; Word's SaveAs hangs on these files) and writes main text, footnotes and the flat XML. `scripts/verify_txt.py` rebuilds the visible text from that XML and checks any conversion against it.

## Planned pipeline

1. **Ingest** from the Word sources via `scripts/word_export.ps1` (Word is installed on Hashem's PC; LibreOffice is not), not from `clean_txt`. Keep all text, tables, list numbers and footnotes; decode Quran glyphs to exactly the words quoted. `scripts/verify_txt.py` is the acceptance test: 100% of the source's words, nothing extra.
2. **Segment** into one record per fatwa: `{id, title, question, answer, collection, chapter, source_file}`. Keep the original text exactly as written for display and voice. Build a separate normalized copy for search only: strip tashkeel, tatweel and `()`, and unify ا/أ/إ/آ, ى/ي, ة/ه.
3. **Index** with hybrid retrieval: Arabic-aware BM25 plus multilingual embeddings, over title+question and over the answer. User questions usually resemble the original askers' questions.
4. **Select**: take the top-k, rerank, then run a strict LLM check of whether a candidate answers the question. A match returns the verbatim fatwa with its citation; no match returns the abstain message.
5. **Voice**: ElevenLabs TTS ("sawy v2") on the verbatim text, cached by text hash so each passage is paid for once and can be reviewed before release. Quran quotations need special handling: mispronouncing Quran in his voice is unacceptable.
6. **Evaluate** with the Golden Dataset, paraphrases of existing questions (the source fatwa should come back), questions that must get the abstain message, and injection attempts. Target: zero non-Sheikh text in answers.

Front end: either keep the ElevenLabs agent for voice in/out and point it at this backend as a custom LLM, or build our own app that calls TTS directly.

## Decisions

- **Verbatim only** (confirmed 2026-10-24): answers are the Sheikh's text word for word, never summarized.
- **Languages** (2026-10-24): people may ask in any language; the answer is always the Sheikh's Arabic text. Translation is either the user's own tool or an optional machine translation the bot shows as text, labelled as such. A translation is never spoken in his voice.

## Open decisions (ask; don't assume)

- Scope: fatawa only, or also his treatises and lectures?
- Topics that should always be referred to a person (e.g., specific divorce cases, inheritance shares)?
- Front end: ElevenLabs agent with a custom LLM, or our own app?

## Links

- Team notes ("Basic Documentation"): https://docs.google.com/document/d/1FLi4CSPaRdOqKcnQDqZfRuUAlQg4Nheq8FrJP4XV9Mk
- Old system prompt: https://docs.google.com/document/d/1FVYkRlmk0Edkh3xs233jujF0C6xSIbPDHtDdOpU8L_4
- Golden Dataset: https://docs.google.com/spreadsheets/d/1qPyczx6wLq5sj-0nzJMGZUsR36_T666uD_73crGa1js
- Earlier model tests: Gemini 2.0 Flash (weak) https://docs.google.com/spreadsheets/d/1wHQVW7DPXQPOBj9BprLput2qXApCOlr21rYGAT_yyOA, GPT-5 https://docs.google.com/spreadsheets/d/1KduUOR_d1fB1ZhkW7A0QAHxUf710JusTIfj6cFmBhEQ

## Conventions

- The books stay in Drive, not in git: everything under `data/` is gitignored (`data/raw/` downloads, `data/work/` derived files).
- Downloading from Drive: the Google Drive connector lists only files Hashem has opened (1 of the 116 sources), so use Chrome. Drive's select-all only covers rows that have loaded (scroll to the end first), and Chrome blocks repeat zip downloads in one tab; use a fresh tab per zip.
- UTF-8 everywhere. On Windows, run Python with `PYTHONUTF8=1` (or `-X utf8`); otherwise piped output and file I/O default to cp1252 and fail on Arabic.

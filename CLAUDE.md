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
| Original books (`.doc`) | Drive `sawi_material`: https://drive.google.com/drive/folders/18PA1HGQ28p13M7sZQDInA_0wMhGo6T8B | Old Word files. As of 2026-10-24 only one `.doc` is left in it (`03 (2) كتاب العلم.doc`), plus the `Progress/` and `Prompt Engineering/` docs. |
| Converted text | Drive `clean_txt` (Hashem, Dec 2025): https://drive.google.com/drive/folders/1ZqNNZKHYjJP1768VDBWNyEJCUGrl68SP | *موسوعة فتاوى الصاوي* split by fiqh chapter (`01 كتاب العقيدة` … `22 كتاب الحديث الشريف`, including the 3-volume *موسوعة فتاوى المغتربين – كتاب العقيدة*), plus standalone books (تهافت العلمانية, نظرية السيادة, نهائي الطحاوية, …). Variants tagged `(2)`, `تحت الإجراء` (in progress), or `NN book.txt` may overlap; dedupe before indexing. |
| Fatwa website | https://fatawaalsawy.com | Large archive. The team asked the site manager for the data; prefer an export over scraping. |
| Voice training audio | `sawi.mp3`, ~2 h of khutbahs: https://drive.google.com/file/d/1DcygMVxmADH2B7EGxDp54cTsoOG6Hql8 | Already used for the clone. |

Text format, checked in `clean_txt/16 (2) كتاب الرضاع.txt`: clean Unicode Arabic. Each fatwa runs: title line → the asker's question → `الجواب` → `بسم الله الرحمن الرحيم` → `الحمد لله والصلاة والسلام على رسول الله…` → answer → `والله تعالى أعلى وأعلم.` Footnote markers survive as empty `()` and the footnote text is lost (re-convert from `.doc` if it is needed). Quran is quoted in Uthmani script as `﴿…﴾ [سورة: آية]`. Files open with a book header and end with `***` / `الفهرس`.

## Planned pipeline

1. **Ingest** text from `clean_txt`. If a `.doc` needs re-converting, use Word COM automation (Word is installed on Hashem's PC; LibreOffice is not).
2. **Segment** into one record per fatwa: `{id, title, question, answer, collection, chapter, source_file}`. Keep the original text exactly as written for display and voice. Build a separate normalized copy for search only: strip tashkeel, tatweel and `()`, and unify ا/أ/إ/آ, ى/ي, ة/ه.
3. **Index** with hybrid retrieval: Arabic-aware BM25 plus multilingual embeddings, over title+question and over the answer. User questions usually resemble the original askers' questions.
4. **Select**: take the top-k, rerank, then run a strict LLM check of whether a candidate answers the question. A match returns the verbatim fatwa with its citation; no match returns the abstain message.
5. **Voice**: ElevenLabs TTS ("sawy v2") on the verbatim text, cached by text hash so each passage is paid for once and can be reviewed before release. Quran quotations need special handling: mispronouncing Quran in his voice is unacceptable.
6. **Evaluate** with the Golden Dataset, paraphrases of existing questions (the source fatwa should come back), questions that must get the abstain message, and injection attempts. Target: zero non-Sheikh text in answers.

Front end: either keep the ElevenLabs agent for voice in/out and point it at this backend as a custom LLM, or build our own app that calls TTS directly.

## Open decisions (ask; don't assume)

- Verbatim only, or is any summarizing acceptable? Until the Sheikh says otherwise: verbatim.
- Languages: Arabic only, or English questions too? An English rendition voiced as him is no longer his words.
- Scope: fatawa only, or also his treatises and lectures?
- Topics that should always be referred to a person (e.g., specific divorce cases, inheritance shares)?
- Front end: ElevenLabs agent with a custom LLM, or our own app?

## Links

- Team notes ("Basic Documentation"): https://docs.google.com/document/d/1FLi4CSPaRdOqKcnQDqZfRuUAlQg4Nheq8FrJP4XV9Mk
- Old system prompt: https://docs.google.com/document/d/1FVYkRlmk0Edkh3xs233jujF0C6xSIbPDHtDdOpU8L_4
- Golden Dataset: https://docs.google.com/spreadsheets/d/1qPyczx6wLq5sj-0nzJMGZUsR36_T666uD_73crGa1js
- Earlier model tests: Gemini 2.0 Flash (weak) https://docs.google.com/spreadsheets/d/1wHQVW7DPXQPOBj9BprLput2qXApCOlr21rYGAT_yyOA, GPT-5 https://docs.google.com/spreadsheets/d/1KduUOR_d1fB1ZhkW7A0QAHxUf710JusTIfj6cFmBhEQ

## Conventions

- The books stay in Drive, not in git (`data/raw/` is gitignored).
- UTF-8 everywhere. On Windows, run Python with `PYTHONUTF8=1` (or `-X utf8`); otherwise piped output and file I/O default to cp1252 and fail on Arabic.

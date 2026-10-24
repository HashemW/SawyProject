# Sawy Fatwa Assistant

A voice assistant that answers questions **only** with the fatawa of Dr. Salah Al-Sawy, spoken in his voice (cloned in ElevenLabs at his request).

## How it will work

```
question
  → search the Sheikh's fatawa (Arabic-aware keyword + semantic search)
  → check whether one of them actually answers the question
  → yes: return that fatwa verbatim, with its source, and speak it in his voice
  → no:  say that no fatwa was found (it never makes up an answer)
```

## Status

- [x] Voice cloned in ElevenLabs ("sawy v2")
- [x] Prototype ElevenLabs agent (built-in RAG)
- [x] Source documents collected (116 Word files) and the first-pass text (`clean_txt`) checked against them: not usable as is, see [docs/data-verification.md](docs/data-verification.md)
- [ ] Re-extract the text from Word, keeping footnotes, tables and the exact Quran quotes
- [ ] Split the text into one record per fatwa
- [ ] Search index and strict answer selection
- [ ] Voice output with audio caching
- [ ] Evaluation: golden set, abstention, and injection tests

Project rules, sources and open decisions are in [CLAUDE.md](CLAUDE.md).

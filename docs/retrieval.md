# Step 3: the search index

Scripts: `scripts/build_index.py` (builds the index), `scripts/search.py` (searches it; the answer service will use it), `scripts/eval_retrieval.py` (measures it), with the test questions in `eval/retrieval.jsonl` (made with `sample_targets.py` and `merge_queries.py`). Done 2026-10-24 to 25.

**Question.** Given a question in the asker's own words, in any language or dialect, which records of the corpus may answer it? Search only proposes candidates; whether one of them answers the question is decided in step 4, and the answer is always a record's own text. What matters here is that the right record is among the first 20 or so candidates.

## What is indexed

Each of the 13,461 records is searched through three fields:

| Field | Text | Used by |
|---|---|---|
| `q` | a fatwa's title and question; a book section's book title and heading path (a heading repeated on two levels once) | keyword search and embeddings |
| `p` | the answer, in passages | keyword search and embeddings |
| `doc` | title, question and answer as one text | keyword search |

**Passages.** An answer is cut at paragraph ends into passages of at most 220 words; a longer paragraph is cut at sentence ends, and a sentence over the limit every 220 words. A short last passage (under 50 words) joins the one before. Paragraphs that are only the opening or the closing formula (the basmala, «الحمد لله والصلاة والسلام على رسول الله…», «والله تعالى أعلى وأعلم») belong to no passage, since every answer has them. Each passage is a span (start and end offsets) of the record's answer, so the passage that matched can be quoted exactly as it stands. Result: 21,599 passages, median 149 words, 90% under 213, longest 269; every record has at least one.

A record is ranked by its best unit: its `q` text, or its best-scoring passage.

## Keyword search

**Normalization.** The corpus's search copy (`dedupe.search_text`): no diacritics, tatweel, invisible marks, brackets or footnote numbers; ا/أ/إ/آ/ٱ, ى/ي, ة/ه, ؤ/و and ئ/ي unified. Arabic-Indic digits are read as ASCII digits, and the Persian ک and ی as ك and ي, for questions typed on other keyboards.

**BM25** (Okapi, k1 = 1.2, b = 0.75, Lucene's idf), kept as a sparse matrix of term weights per unit, so that a question scores every unit with one column sum. Keyword search is used only for questions that contain Arabic letters.

**Stemming.** Arabic attaches articles, conjunctions, prepositions and pronouns to words («بالزكاة», «وصلاته»), so the same word rarely appears in the same form in a question and in an answer. Four ways of reducing words were compared:

- none: the normalized words as they are;
- light10 (Larkey, Ballesteros and Connell, 2007), a standard light stemmer for Arabic retrieval: a leading «و» off if three letters remain, one article («ال», «وال», «بال», «كال», «فال», «لل») if two remain, then the suffixes «ها ان ات ون ين يه ه ي» in turn;
- light10 keeping a bare leading «و»: the published rule cuts the «و» of words that begin with it (وضوء becomes ضوء, «light»; وصية, ورثة), which fiqh vocabulary is full of;
- Snowball's Arabic stemmer (through PyStemmer), which also removes broken-plural and verb affixes. It expects ة, ى and hamzas as written, so it is given the words before letters are unified, and its stems are unified afterwards.

## Embeddings

Three multilingual embedding models were compared, chosen for strong multilingual retrieval (Arabic and English questions against Arabic text), a licence that allows this use, and a size that runs on Hashem's GPU (RTX 3070, 8 GB) in half precision:

| Model | Parameters | Licence | Revision |
|---|---|---|---|
| `BAAI/bge-m3` | 568M | MIT | `5617a9f6` |
| `intfloat/multilingual-e5-large-instruct` | 560M | MIT | `274baa43` |
| `Qwen/Qwen3-Embedding-0.6B` | 596M | Apache-2.0 | `97b0c614` |

They run locally, so the Sheikh's texts are not sent to any service and nothing is billed. The models (4.3 GB) are pinned to the revisions above and read from the Hugging Face cache: `HF_HOME` if set (on Hashem's PC user-wide, `D:\Caches\huggingface`), else `data/models` (gitignored).

**Text.** Diacritics, tatweel, invisible marks and footnote numbers are removed, but letters stay as written: the models learned standard spelling. Each passage is preceded by its record's title, so that a passage that never names its subject («فإن ذلك جائز بشرط…») is still embedded with it. Questions for e5 and Qwen3 get the instruction those models are trained with («Given a question about an Islamic ruling, retrieve the fatwa or passage that answers it»); bge-m3 takes none.

**Length.** Texts are cut at 512 tokens. With the two XLM-R models (bge-m3, e5) every passage fits (in a sample of 3,000: median 271 tokens, longest 495); with Qwen3's tokenizer 1.9% of passages lose their last words. 2–3% of `q` texts are longer (askers' questions run to 2,000 words) and lose their end; the title, at the start, always fits.

## Fusion

Each component (a kind of search over one field) ranks the records; the rankings are combined by reciprocal rank fusion (RRF): a record scores w / (60 + rank) in each list it appears in, w being that list's weight. RRF needs no calibration between BM25 scores and cosine similarities.

## Test questions

There was no test set of user questions with known answers: the team's Golden Dataset has 4 questions, the original askers' own. So one was made.

- **Records.** 150 picked at random (seed 20261024): 125 encyclopedia fatawa, 13 book sections and 12 question-answer records from the books (books oversampled; they are 5% of the corpus). 100 are for development (`dev`), 50 held out for a final measurement (`test`).
- **Questions.** For each record, three writers (separate model instances that saw only the records, never the search) wrote what an ordinary person would ask: `ar`, one or two sentences in their own words, a quarter of them in a spoken dialect (12 Egyptian, 9 Levantine, 9 Gulf, 9 Maghrebi); `ar_short`, the issue in at most 8 words as typed into a search box; and `en`, what an English-speaking Muslim in the US would say. 450 questions. They were told not to reuse the asker's phrasing and not to put the ruling in the question. Example, for «شراء السلع الموسمية المرتبطة بعيد الكريسماس»: «بالمحلات هون بشهر ديسمبر في شوكولا وأغراض حمام وبيجامات عليها رسومات الكريسماس، بيجوز اشتري منها واستعملها بهالفترة؟»; «شراء حلويات وملابس الكريسماس»; «Every December the stores fill up with Christmas stuff: candy, body wash gift sets, pajamas with Santa on them. Is it okay to buy and use these things?»
- **Scoring.** A question counts as answered at k if the record it was written for is among the first k results (R@k); MRR is the mean of 1/rank over the first 100. Another fatwa that answers the question equally well counts as a miss, and the Sheikh often answered the same issue several times, so these numbers are a lower bound (see the failure analysis).
- All choices were made on `dev`; `test` was run once, at the end.

Writers' notes on hard cases: some interview records ask about something named only earlier in the conversation; one encyclopedia entry is a whole guide to Hajj and Umrah; several fatawa cover two issues (the questions ask about the main one).

The configurations compared are in `eval/configs/` (one file per round); each table below is one run of `eval_retrieval.py` with that file.

## Results on dev

**Keyword search alone** (`dev_stemmers.json`; Arabic questions only, since it does not apply to English):

| Stemmer | `q` R@20 (ar / short) | `q` MRR (ar / short) | `doc` MRR | `p` MRR |
|---|---|---|---|---|
| none | 0.61 / 0.57 | 0.362 / 0.292 | 0.385 / 0.329 | 0.118 / 0.169 |
| light10 | 0.67 / 0.72 | 0.467 / 0.357 | 0.464 / 0.382 | 0.147 / 0.211 |
| light10 keeping «و» | 0.68 / 0.71 | 0.456 / 0.362 | 0.432 / 0.378 | 0.124 / 0.209 |
| Snowball | **0.73** / 0.66 | **0.509 / 0.397** | 0.437 / 0.417 | 0.125 / 0.201 |

Paired over the 200 Arabic questions (bootstrap, 2,000 resamples): stemming helps (light10 over none, MRR +0.085, 95% interval +0.042 to +0.128); Snowball beats light10 (+0.041, +0.004 to +0.079); keeping the «و» makes no difference (−0.003, n.s.). The title and question carry the match: the answers' passages alone find few records (MRR 0.12–0.21), because a user's question looks like the asker's question, not like the Sheikh's answer. Equal-weight fusion of the `q` and `p` lists is worse than `q` alone (Snowball: MRR 0.509 falls to 0.333). Chosen: Snowball, on `q`.

**Embeddings alone** (round 1, `dev_round1.json`; Qwen3 measured separately, on `q` only), R@20 / MRR:

| Model | field | ar | ar_short | en |
|---|---|---|---|---|
| bge-m3 | `q` | 0.91 / **0.756** | 0.78 / 0.563 | 0.79 / 0.601 |
| e5-large-instruct | `q` | **0.93** / 0.699 | **0.86** / 0.548 | **0.86 / 0.644** |
| Qwen3-Embedding-0.6B | `q` | 0.71 / 0.536 | 0.71 / 0.401 | 0.70 / 0.469 |
| bge-m3 | `p` | 0.78 / 0.453 | 0.75 / 0.453 | 0.68 / 0.349 |
| e5-large-instruct | `p` | 0.77 / 0.419 | 0.84 / 0.515 | 0.68 / 0.371 |

Embeddings find far more than keyword search: on the full Arabic questions, bge-m3 over title and question puts the record first 68% of the time (keyword search: 44%). They also work across languages: English questions find the Arabic records almost as well as Arabic ones. Unlike keyword search, embeddings of the passages do find records (MRR 0.35–0.52), so they can carry the book sections, whose headings say little.

Qwen3 was measured on `q` only and then dropped: it is clearly weaker here, and on this GPU it embeds 12 texts a second against 156 for bge-m3, so a full index takes over an hour. Its half-precision vectors were checked against float32 ones computed on the CPU (cosine at least 0.9998), so the weakness is not a precision artefact.

**Fusion.** Round 1 fused the lists of one model and keyword search with equal or simple weights and the usual RRF constant k = 60. Averaged over the three kinds of question, that raised recall deep in the list (R@50 from 0.89–0.93 for one model over `q` to 0.93–0.96) but pulled good first places down (MRR from 0.63–0.64 to 0.48–0.58). RRF with k = 60 is flat (first place scores 1/61, tenth 1/70), so records that are mediocre in several weak lists overtake the best record of the strongest list. Round 2 (`dev_round2.json`, 27 configurations) tried weights favouring the title-and-question embeddings, k = 10, and the two models together. Mean over ar, ar_short and en:

| Configuration | R@1 | R@10 | R@20 | R@50 | MRR |
|---|---|---|---|---|---|
| bge-m3 + e5 over `q` only | **0.56** | 0.83 | 0.87 | 0.94 | **0.661** |
| bge-m3 + e5 over `q` and `p`, keyword `q`, equal weights, k = 60 | 0.48 | 0.83 | **0.93** | 0.96 | 0.591 |
| same, k = 10 | 0.51 | **0.88** | **0.93** | **0.97** | 0.633 |
| **chosen**: embeddings `q` 1, `p` 0.5, keyword `q` 0.5, k = 10 | 0.54 | 0.86 | 0.92 | **0.97** | **0.661** |
| chosen weights, e5 only | 0.49 | 0.85 | 0.91 | 0.96 | 0.616 |
| chosen weights, bge-m3 only | 0.48 | 0.83 | 0.87 | 0.94 | 0.607 |

Paired over the 300 dev questions, the chosen configuration beats the same weights with e5 alone (MRR +0.045, +0.018 to +0.073) and with bge-m3 alone (+0.054, +0.031 to +0.079), equal weights at k = 10 (+0.028, +0.008 to +0.049), its own weights at k = 60 (+0.053, +0.033 to +0.074), and dropping keyword search (+0.061, +0.037 to +0.086). Against the embeddings over `q` alone its MRR is the same (+0.000, −0.025 to +0.026), but it finds more of the records deeper down (R@20 0.92 against 0.87, R@50 0.97 against 0.94), and those are what step 4 will choose from.

## The chosen search

`search.DEFAULT`: reciprocal rank fusion with k = 10 of five lists: bge-m3 and e5 over title and question (weight 1 each), bge-m3 and e5 over the passages (0.5 each), and BM25 with Snowball stems over title and question (0.5; only for questions with Arabic in them). Each hit carries the passage that matched best. `build_index.py` builds exactly these parts by default.

## Results on test

The 50 held-out records (150 questions), run once with the chosen configuration and the main alternatives (`test_final.json`):

| Configuration | R@1 | R@5 | R@10 | R@20 | R@50 | MRR |
|---|---|---|---|---|---|---|
| **chosen** | **0.51** | **0.77** | **0.83** | 0.85 | **0.95** | **0.624** |
| bge-m3 + e5 over `q` only | 0.50 | 0.70 | 0.76 | 0.81 | 0.87 | 0.597 |
| chosen weights, e5 only | 0.49 | 0.71 | 0.77 | 0.84 | 0.91 | 0.591 |
| chosen weights, bge-m3 only | 0.43 | 0.71 | 0.79 | 0.83 | 0.94 | 0.568 |
| all six lists, equal weights, k = 60 | 0.41 | 0.75 | 0.82 | **0.89** | **0.95** | 0.556 |
| keyword search alone, Snowball (mean of the two Arabic kinds; it does not apply to English) | 0.32 | 0.55 | 0.62 | 0.69 | 0.72 | 0.427 |

By kind of question, chosen configuration: full Arabic questions R@1 0.64, R@20 0.90, R@50 0.98 (MRR 0.710); short ones R@20 0.84, R@50 0.96; English R@20 0.82, R@50 0.90. The ordering of the configurations is the same as on dev, and the chosen one is again best or tied on every measure but R@20, where the flat fusion's extra depth finds two more questions in fifty. The test numbers are a little lower than dev's (R@20 0.85 against 0.92): the choice was made on dev, and 50 records give wide margins (about ±0.1 on R@20).

**By kind of record** (chosen configuration, R@20, full Arabic / short / English): fatawa 0.98 / 0.91 / 0.92 on dev (87 records) and 0.92 / 0.89 / 0.92 on test (38); book sections 0.83 / 1.00 / 0.83 on dev (6) but 0.71 / 0.43 / 0.43 on test (7); questions from the books 0.71 / 0.86 / 0.71 on dev (7) and 1.00 / 1.00 / 0.60 on test (5). Fatawa are found well. Book sections are the weak point: their only "question" is a heading such as «كلمة أخيرة», so they are found through their passages alone.

**The team's Golden Dataset** (its 4 questions are the original askers' own): each question's fatwa comes first. One check needed care: the sheet writes 382, the corpus «٣٨٢»; search reads both as the same number.

## What the misses are

Of the 450 dev and test questions, 46 did not have their record in the first 20. Reading the first results of each (from their titles):

- 26 found another record on the same question first: other fatawa on interest-based mortgages, forex trading, vanilla extract with alcohol, a woman marrying when her guardian refuses, a husband who lied that he had divorced; and, for the interview, the neighbouring exchange on the same point;
- 18 found related records that answer part of the question (conditional divorce for a divorce made only in thought; the Sheikh's own chapters on the way out of division for an interview question about it);
- 2 found nothing relevant, both for one record, «أكل في نهار رمضان ناسيًا»: the short «نسيت وأكلت وأنا صائم» and its English twin. «نسيت» and «ناسيًا» share a root but not a stem, and the embeddings did not bridge them either.

So the strict score undercounts: in most misses search still offered a fatwa that answers the question. Whether that fatwa fits the asker's case is for step 4 to judge.

## Cost

On Hashem's PC, building takes about a minute per stemmer for keyword search (all three fields) and, for the embeddings, about 4 minutes per model when the GPU is free (138 passages a second); the GPU was shared with other programs during the real build (bge-m3 took 11 minutes, e5 8.5). The chosen index is 144 MB (`data/work/index/`). A search takes 76 ms on the GPU (95th percentile 84 ms) and 384 ms on the CPU alone (472 ms), after 18 seconds to load the two models once; on the CPU the models run in float32 and need about 4.5 GB of memory.

## Problems met

- **An embedding build stalled.** Run with its progress bars sent through PowerShell's `*>` redirection, it made no visible progress in 14 minutes; without the redirection the same step took 86 seconds. Builds now print one line per field instead of progress bars.
- **Qwen3 was slow and weak** (above). It was stopped after its first field.
- **Six interview records had no title.** Their question starts with an empty line and the title was taken from the first line; `segment_books.py` now takes the first non-empty line. Only those six titles changed in the corpus.
- **Equal-weight fusion hid good first places**; fixed by weights and k = 10 (above).
- **A test run meant for the CPU ran on the GPU**: in PowerShell, setting `$env:CUDA_VISIBLE_DEVICES = ""` removes the variable instead of hiding the GPU; `-1` hides it. On the CPU, transformers also kept the models' half precision, which is slow there; `load_model` now uses float32 on the CPU.
- **An interrupted build lost its record** of what it had finished, because `index.json` was written at the end. It is now updated after each part.

## Limits

- The test questions were written by model instances from the records, not by real users. They are varied (dialects, short forms, English), but real questions, such as the 1,308 titles of the YouTube fatawa, may be harder or easier.
- The strict score counts only the record the question was written for, so it is a lower bound.
- 150 records give wide margins, especially the 50 of the test split; small differences between configurations are not meaningful, which is why the choice rests on paired comparisons and on the pattern across both splits.
- English questions use the embeddings only. Translating a question into Arabic first (step 4's question normalization) may let keyword search help them too.
- Book sections are found less reliably than fatawa.
- Search always returns candidates; deciding that none of them answers is step 4's job.

## Rebuilt 2026-10-25

12 records changed when in-progress 2022–23 copies that revise their 2020–21 copy were kept instead of it ([segmentation.md](segmentation.md#limits)). The index was rebuilt: 21,605 passages (6 more). The test scores of every configuration in `test_final.json` and the dev scores of the chosen search are unchanged.

## Next: step 4

Done: [selection.md](selection.md). The first 50 candidates are reranked by a cross-encoder fused with the search order, and a strict model check over the first 10 decides which record, if any, settles the question.

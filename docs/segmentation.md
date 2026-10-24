# Records: one per fatwa

Done 2026-10-24 by Claude for Hashem, for the 80 files of the fatwa encyclopedia (`موسوعة فتاوى المغتربين`): the 32 volumes of 2011–2017 (`NN book.doc`), the 25 chapter files of 2020–21 (`NN <chapter>.doc`, chapter 01 as `01-1`…`01-3`) and the 23 chapter files of 2022–23 (`NN (2) <chapter>.docx`). The standalone books and treatises come next. Volumes 33, 35 and 36 are empty templates and are skipped.

**Result.** 21,711 fatawa and 9 titled articles, with every non-empty paragraph of the 80 files in exactly one record or one listed non-fatwa part. After grouping the copies of each fatwa across editions, **12,779 distinct fatawa** form the corpus (1,869 from the 2022–23 files, 8,732 from 2020–21, 2,178 found only in the volumes). 26 records are held for review and kept out (12 with a doubtful Quran quote, 9 articles, 5 quoted fatawa of other scholars or short answers without his opening).

Everything is local (`data/work/records/`, gitignored). Reproduce with:

```
python -I -X utf8 scripts\segment.py --extract data\work\extract --out data\work\records
python -I -X utf8 scripts\dedupe.py --records data\work\records
```

## What a record holds

`corpus.jsonl`, one fatwa per line:

| Field | |
|---|---|
| `id` | `V07-0384` (volume 7, 384th fatwa), `C05-0241` (2020–21 chapter 5), `N11-0117` (2022–23 chapter 11), `C01-2-0097` |
| `source`, `edition`, `collection`, `chapter`, `number` | where it is: the file, its edition, `موسوعة فتاوى المغتربين`, the chapter (`كتاب الصلاة`), and the fatwa's number in the volumes (`794`) |
| `title`, `question`, `answer` | the text exactly as extracted: one line per paragraph; empty paragraphs and editors' notes left out. The answer starts after «الجواب» and ends with his closing formula |
| `notes` | the footnotes the record references, with their numbers |
| `spans` | per field, where Quran quotes (with verses and status), honorifics and footnote references sit |
| `editorial` | editors' notes found inside the record and left out of its text |
| `flags`, `status` | how its boundaries were found (below) and whether it is usable (`ok`) |
| `group`, `copies` | its copies in other editions and files |
| `search` | the normalized copy for search only: no diacritics, tatweel, invisible marks, brackets or footnote numbers; ا/أ/إ/آ/ٱ, ى/ي, ة/ه, ؤ/و, ئ/ي unified |

`records.jsonl` has every copy before dedupe (21,720), `parts.jsonl` every stretch that is not a fatwa, `groups.jsonl` every group of copies, and `report.md` / `dedupe.md` the counts and review lists.

## How a fatwa is found (`segment.py`)

A fatwa in these files runs: title → the asker's question → «الجواب» on a line of its own → basmala → «الحمد لله والصلاة والسلام على رسول الله…» → answer → «والله تعالى أعلى وأعلم».

1. **Anchors.** Every paragraph that is just «الجواب» (or «الجواب:») starts an answer: 21,718 of them. Invisible marks are ignored (one «الجواب» began with a right-to-left mark).
2. **Titles by their form.** Each file is consistent about how it sets titles, but the files differ: numbered `heading 2` in the volumes («794.⇥حكم الوشم»), `heading 3` in 2022–23, numbered `عنوان2` in `01-1…3`, an outline level in `20 (2)`, `heading 2` in most of 2020–21. The script learns each file's form from the first paragraph after the Sheikh's closing formula (a form counts if it covers a tenth of those cases and is set deliberately, by a style or an outline level 1–2). Between two anchors, the last title before the second anchor starts the next fatwa. Titles can run over two paragraphs («شرح قوله تعالى:» and the verse), and a volume's number can stand in a paragraph of its own before its title. List numbers count as titles only where titles are numbered, and only as the next number in sequence (lists inside answers restart at 1).
3. **The closing formula, where titles are plain paragraphs.** Most 2020–21 files set many titles as ordinary paragraphs (in `13 كتاب النكاح`, 308 of 947 titles are not in `heading 2`). There the split is after the last paragraph that ends with his formula: «والله تعالى أعلى وأعلم», with the variants and typos he or his typists used («والله أعلى وأعلم», «وهو تعالى أجل وأعلم», «الله تعالى أعلى وأعلم», «والله تعالى على وأعلم», «…أعلى وعلم»). Askers sometimes write «والله أعلم» or even his full formula at the end of their question. «والله أعلم» alone does not count, and his formula after a title (7 cases) is taken as the asker's: a title-styled paragraph inside an answer occurred in only 14 records of the whole corpus, nearly all of them errors of exactly this kind or untitled articles (item 7).
4. **Where neither marks the split** (an answer without a closing formula followed by a plain title), the next title is found by its shape. 97% of plain-paragraph titles in the 2020–21 files end without punctuation (or with «)» or «»»), and 99.97% have at most 20 words. So the next title is a short paragraph shaped like that, right after a paragraph that ends a sentence, followed by question paragraphs and nothing that opens an answer (9 cases). A numbered question («3- هل يقع…؟») directly before an anchor starts a new record (23, a list of short questions in `14 كتاب الطلاق`). «والله تعالى أعلم» ends 4 more. Anchors with none of these between them are follow-up questions in one fatawa (or a fatwa he quotes) and stay in one record (6).
5. **Not fatawa.** Chapter headings (`heading 1`, «كتاب الصلاة» and the 2011 volumes' «كتاب» / «القرآن الكريم» pairs), ornaments («***»), front matter, tables of contents and back matter become parts (816). The chapter of each fatwa in a volume is taken from these headings.
6. **Editors' notes** are left out wherever they appear and listed with their record (33). They are short lines such as «هذه الفتوى مكررة مع سابقتها», «مكرر نصا مع ما سبق!!!!», «تكرار الجواب مع اختلاف صيغة السؤال» and «إلى هنا», all in the 2022–23 files, some set in a heading style.
7. **Articles.** A titled text with no «الجواب» between an answer and the next fatwa becomes an article record (9). Examples are a series' part (3) without a question, and the deliberations on a company's report. Two contain other people's words (a commenter's critique answered by the Sheikh), so all articles are held for review.

**Check.** Every non-empty paragraph of the 80 files is in exactly one record or part (265,231 blocks: 234,091 in records, 30,884 in parts, 256 empty ones outside both); the script stops if one is not. Of the 21,711 answers, 21,681 open with the basmala and 3 with «الحمد لله»; 22 are the short-question list's one-line answers, and the last 5 are held (below).

## Held for review (26)

| Why | Records |
|---|---|
| A Quran quote in it is one of the 19 flagged ones (decision 2026-10-24) | 12 |
| Article (titled text without «الجواب») | 9 |
| The answer does not open with his formula. His own answers do (21,684 of 21,711, apart from the short-question list), so these are other scholars' fatawa he quotes (Dr. Hani al-Jubair's on video games, two of Rashid Rida's on acting) and two of his one-line answers | 5 |

Each is listed in `report.md`. A held record is never in the corpus; where another edition has a usable copy, that copy is used.

## Copies across editions (`dedupe.py`)

Most fatawa exist in more than one edition. The 2020–21 chapter files rearrange the volumes by chapter: 7,895 of the volumes' 10,123 fatawa have a copy there. And 942 of the 2,283 fatawa in the 2022–23 files (41%) repeat a 2020–21 one; they are not only additions.

**Same fatwa.** Two records are the same fatwa when their questions match and their answers are related. Measured on known pairs, copies of one fatwa share 90–100% of the words of title and question, and 50–100% of their answer's 5-word sequences (answers are revised, extended or reworded). Different fatawa can share answer text, because the Sheikh reuses paragraphs and quotes the same council resolutions, but their questions share under 15%. Rule: question overlap ≥ 0.5 and answer overlap ≥ 0.3 (or one answer 50% contained in the other); or question ≥ 0.3 with nearly identical answers (≥ 0.85); or an identical question (≥ 0.9) whatever the answer. «ﷺ» is read as «صلى الله عليه وسلم», since editions differ there. Links are made strongest first. Two groups that each hold a different record of the same file are never joined (162 refusals), because that would chain neighbouring fatawa. Titles that differ only in a part number («(1)», «(2)») are parts of a series, not copies.

**Kept copy** (decisions 2026-10-24): the newest edition, so 2022–23 over 2020–21 over the volumes (later volume first). A copy in a 2022–23 file marked «تحت الإجراء» gives way to a 2020–21 copy if one exists (393 times); otherwise it is kept (510 fatawa found only in in-progress files). Within one file the first copy is kept. A held copy is passed over for the next usable one (3 times); 10 groups have no usable copy.

| | |
|---|---|
| Fatawa records, all editions | 21,711 |
| Groups (distinct fatawa) | 12,789: 4,288 single, 8,098 pairs, 387 triples, 16 larger |
| Kept | 12,779: 2022–23 1,869; 2020–21 8,732; volumes only 2,178 |
| Same question, answer extended in a later copy | 448 (one fatwa; the longer, newer copy kept) |
| Same question, answer reworded | 54, listed in `dedupe.md` to check for a changed view |
| Same answer, different questions | 79, kept as separate fatawa and listed |

Recall check: of the 2,178 fatawa kept only from the volumes, 104 share a title with a fatwa in a later edition; in a sample these are different askers with different questions under a generic title («العمل في المصارف الربوية»).

## Limits

- Boundaries come from layout and formulas, so a fatwa whose title is a plain paragraph, whose answer has no closing formula, and whose question has no shape cue stays joined to the previous one (it would be among the 6 follow-ups).
- Authorship cannot always be read from the layout. An answer that quotes another scholar's fatwa or a council resolution in full is kept whole, as the Sheikh published it; only the 5 cases where a quoted fatwa stood as a record of its own are held.
- The 54 reworded answers keep the newest wording; an older wording may reflect an earlier view.

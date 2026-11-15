# Contracts between Jussi (database, API) and Kristian (Verda, Gemma, React)

Fixed on 2026-11-14. **Change a format only by editing this file in the same commit**, with a line
under "Changes" at the bottom. Mocks of (c) are in `web/mocks/worklist.json` and
`web/mocks/compare.json`. The mocks hold realistic **fake** data for Sauli Niinistö (Q29207): the
sentences are plausible, but the numbers, distances and judgements are made up.

Conventions for all three:
- `lang` is `fi`, `sv` or `en`.
- `page_id` is the page id **in that language's Wikipedia** (fi 1137, sv 119870 and en 1042690 are
  all Niinistö). Topics are joined across languages by `wikidata_id` (`"Q29207"`).
- Sentences are numbered from 0 per (lang, page_id), in text order: `sent_no`.
- Sentences are split with **`ingest.sentences.text_sentences(text)`** on dataset S's `text`, by both
  of us, so the numbers agree. `sent_no` = the index in the list it returns. (S text is Markdown-like
  plain text, not wikitext: the function drops `#` headings and `|` table rows, strips `- ` list
  markers, then uses the same splitter and filters as `sentences()`: at least 3 words, repeats within
  an article kept once.)
- **Distances are cosine distances** (`VEC_DISTANCE_COSINE`, 0 = same direction, 2 = opposite),
  between bge-m3 embeddings. Lower = more similar.

## a) Sentence embeddings (Kristian produces on Verda; Jussi imports into `lang_sentence`)

`data/verda/sentences-{lang}.parquet`, one file per language, one row per sentence:

| column | type | |
|---|---|---|
| `lang` | string | `fi` / `sv` / `en` |
| `page_id` | int32 | that language's page id (dataset S `page_id`) |
| `wikidata_id` | string | e.g. `Q29207` |
| `sent_no` | int32 | 0-based, text order |
| `text` | string | the sentence as split, before normalisation |
| `embedding` | list<float32>, length 1024 | bge-m3 dense vector, **L2-normalised** |
| `model` | string | `bge-m3` |

Scope: every sentence of the 2,919 topics that exist in all three languages.

## b) Gemma judgements (Kristian produces; Jussi imports into `pair_judgement`)

`data/verda/judgements.parquet`, one row per judged pair:

| column | type | |
|---|---|---|
| `wikidata_id` | string | |
| `fi_sent_no` | int32 | the Finnish sentence |
| `other_lang` | string | `sv` / `en` |
| `other_sent_no` | int32 | its matched sentence in `other_lang` |
| `label` | string | `same` \| `contradiction` \| `framing` \| `partial` |
| `reason` | string | one English sentence |
| `tone_fi` | string | `neutral` \| `loaded` \| `partisan` |
| `tone_other` | string | `neutral` \| `loaded` \| `partisan` |
| `fi_claim` | string | the specific fact the Finnish sentence states, in a few English words |
| `other_claim` | string | the same for the other sentence |
| `same_specific_fact` | bool | both state a value for the very same thing (same quantity / event / date / name, same scope) |
| `model` | string | e.g. `google/gemma-3-27b-it` |

Import: `python -m ingest.load_judgements [file …]` (default: every `data/verda/judgements*.parquet`).
It refuses a file whose sentence numbers are not in `lang_sentence`, or whose
`sentences-{lang}.parquet` texts differ from ours. Re-runnable: a model's rows for the topics in the
file are replaced; another model's rows (e.g. `judgements-v2-12b.parquet`) are kept beside them.

Labels: `same` = the same claim (differences in wording, naming or a minor extra detail only);
`contradiction` = **only if `same_specific_fact` is true** and the two clearly disagree on that fact
(number, date, name); `framing` = the same fact told with a different slant or tone; `partial` = they
overlap only partly, or estimates / ranges for the same quantity differ moderately (< 25 %).
`label = contradiction` with `same_specific_fact = false` never occurs (enforced in code).

## c) API (Jussi builds; Kristian's React view uses it)

Both responses carry `sql`: the MariaDB query behind the view, for the SQL drawer.

### `GET /api/worklist?limit=50`

```json
{"sql": "SELECT … FROM article_divergence …",
 "data": [{"wikidata_id": "Q29207",
           "titles": {"fi": "Sauli Niinistö", "sv": "Sauli Niinistö", "en": "Sauli Niinistö"},
           "fi_page_id": 1137,
           "score": 0.81,
           "fi_sv": 0.212, "fi_en": 0.168,
           "missing_sv": 41, "missing_en": 23,
           "missing_in_fi": {"sv": 11, "en": 42},
           "contradictions": 2, "framing": 5, "judged_pairs": 110,
           "edit_war_score": 0.74}]}
```
- Ordered by `score` (descending); `score` is in 0..1, higher = needs an editor more.
- Topics flagged as **different subject** (one Wikidata id, but the language versions are about
  different things, e.g. *Renki* = a Finnish farmhand vs *Farmworker*) are left out;
  `?include_flagged=1` puts them back, at the end of the list.
- `fi_sv`, `fi_en`: whole-article cosine distance between the language versions (raw; the score
  uses it after removing what the length difference explains).
- `missing_sv` / `missing_en`: Finnish sentences with **no sentence in that language closer than 0.418**
  (the nearest one, mutual or not).
- `missing_in_fi`: the reverse, sv / en sentences with no Finnish sentence closer than 0.418.
- `contradictions`, `framing`: pairs the **primary model** (`judged_by` at the top of the response,
  `google/gemma-3-27b-it`) labelled so; `judged_pairs`: how many pairs it judged. All three `null`
  for a topic not judged yet. Not part of `score` yet.
- `edit_war_score`: 0..1, from the Finnish article's history (reverts, sentences that came back).
- Any number can be `null` when that stage has not run yet.

### `GET /api/compare/{wikidata_id}`

```json
{"sql": "…",
 "topic": {"wikidata_id": "Q29207",
           "titles": {"fi": "…", "sv": "…", "en": "…"},
           "urls": {"fi": "https://fi.wikipedia.org/wiki/…", "sv": "…", "en": "…"},
           "edit_urls": {"fi": "https://fi.wikipedia.org/w/index.php?title=…&action=edit", "sv": "…", "en": "…"},
           "page_ids": {"fi": 1137, "sv": 0, "en": 0}},
 "scores": {"fi_sv": 0.212, "fi_en": 0.168, "sv_en": 0.143},
 "rows": [{"fi": {"sent_no": 0, "text": "…"},
           "sv": {"sent_no": 0, "text": "…", "distance": 0.11},
           "en": {"sent_no": 0, "text": "…", "distance": 0.09},
           "covered_by": {"sv": null, "en": null},
           "status": "match",
           "judgements": [{"lang": "en", "label": "same", "reason": "…", "model": "…",
                           "tone_fi": "neutral", "tone_other": "neutral",
                           "fi_claim": "…", "other_claim": "…", "same_specific_fact": true,
                           "note": null, "both_models_agree": null}]}],
 "contradictions": [{"row": 5, "lang": "sv", "fi": {"sent_no": 3, "text": "…"},
                     "other": {"sent_no": 4, "text": "…", "distance": 0.09},
                     "note": "Possible contradiction, check the sources (both models agree)",
                     "both_models_agree": true, "models": ["…12b…", "…27b…"],
                     "reason": "…", "fi_claim": "…", "other_claim": "…"}]}
```
- `rows` follow the Finnish text order. A sentence that exists only in sv or en gets a row of its own
  (`fi: null`), placed after the Finnish sentence it is nearest to.
- `status`:

| status | meaning |
|---|---|
| `match` | the fi sentence is aligned **or** covered in sv **and** en |
| `missing_sv` | nothing in sv closer than 0.418 (`sv` and `covered_by.sv` are null) |
| `missing_en` | nothing in en closer than 0.418 |
| `only_sv` / `only_en` | a sv / en sentence with no Finnish sentence closer than 0.418 (`fi: null`) |

  A fi sentence missing from **both** languages has `status: "missing_en"` and both `sv` and `en`
  are null.
- `judgements` is `[]` until Gemma has run; `lang` says which pair (fi–sv or fi–en) it judges. One
  entry per model that judged the pair. Order: "both models agree" first, then contradiction,
  framing, partial, same.
- A `contradiction` is never shown as a fact: `note` is **"Possible contradiction, check the
  sources"** (+ " (both models agree)"); `note` is `null` for other labels.
- `both_models_agree` (contradictions only): `true` when two or more models call the pair a
  contradiction, `false` when a second model judged the pair and did not, `null` with one model.
- `contradictions` (top level): one entry per pair that any model called a contradiction, "both
  models agree" first, then in text order; `row` is the index into `rows` (rows stay in text order).
- A topic without sentence data answers `200` with `"rows": []` and
  `"note": "sentence data not computed yet for this topic"` (`topic` and `scores` are filled).
- **Alignment** (`sv` / `en` cells): a sentence and its partner are each other's best match (**mutual**)
  and closer than **0.418**. Each sv / en sentence is aligned in at most one row.
- **`covered_by`** (`{"sv": cell|null, "en": cell|null}`, on every row): when a Finnish sentence is not
  aligned in a language but its nearest sentence there is closer than 0.418, that sentence is given here
  (typically one English sentence saying what two Finnish ones say). The same sv / en sentence can cover
  several rows. Always `{"sv": null, "en": null}` on `only_*` rows.
- An sv / en sentence that is close to a Finnish sentence but aligned with none is not listed as a row
  of its own (it is not missing in Finnish); it may appear in `covered_by`.

## Changes

- 2026-11-14: first version.
- 2026-11-14: sentences are split with `text_sentences()` (new, for S's Markdown-like text), not
  `sentences()` / `split_sentences()`.
- 2026-11-14: worklist `?include_flagged=`; compare `note` when there is no sentence data; matched =
  mutual best match below 0.418. Both responses also carry `ms` (database time).
- 2026-11-14 (stage 1c): **missing = nothing within 0.418** (no longer "no mutual match"); worklist
  **`missing_in_fi`**; compare rows **`covered_by`**, and `status` counts a covered sentence as present.
  Mocks updated.
- 2026-11-14: (b) gains `fi_claim`, `other_claim`, `same_specific_fact` (written by Gemma before the
  label); labels tightened: contradiction only for the same specific fact, moderate estimate
  differences are `partial`, wording / naming / minor extra detail is `same`. Labels unchanged.
- 2026-11-14 (judgements): contract b gains `fi_claim`, `other_claim`, `same_specific_fact` (Jesse's
  27B run already has them). Worklist: `framing`, `judged_pairs`, top-level `judged_by`; counts from
  `pair_judgement` (primary model). Compare: judgement objects carry tones, claims, `note`,
  `both_models_agree`; new top-level `contradictions`. Mocks updated.
- 2026-11-15 (demo app): compare `topic.page_ids` (the article page opens Kristian's views of the
  Finnish article by its page id). New routes for the demo app are in `api/explore.py` (not part of
  this contract): `/api/topics`, `/api/chips`, `/api/similar/{id}`, `/api/topic-places`.

# Verda process log (P3 keeps this live — required for the Verda challenge)

Why two machine types:
- **GPU instance** for scoring: every distinct sentence of every revision goes through Gemma
  (page 1150 alone: ~6,500 distinct sentences; all of dataset M: millions). Batch inference with
  vLLM's continuous batching — not a laptop job.
- **CPU instance** for MariaDB + API: the history queries are CPU/IO-bound and must stay up for
  the demo; no reason to pay for a GPU there.

## 1. GPU: Gemma with vLLM

```bash
# on the Verda GPU instance (fill in type: ___ , €/h: ___ )
pip install vllm
export HF_TOKEN=...            # Gemma licence accepted on Hugging Face
vllm serve google/gemma-3-12b-it --max-model-len 4096 --port 8000
# structured output (response_format json_schema) is on by default; check the flags of the
# installed vLLM version with `vllm serve --help` if requests come back as free text
```

Smoke test:

```bash
curl http://<gpu-ip>:8000/v1/models
```

## 2. Score

From any machine that reaches both MariaDB and the GPU:

```bash
SCORING_URL=http://<gpu-ip>:8000/v1 GEMMA_MODEL=google/gemma-3-12b-it \
  python -m scoring.score --backend llm --concurrency 64 --pages 1150   # hero first
SCORING_URL=... python -m scoring.score --backend llm --concurrency 128  # everything
```

`score.py` prints sentences/s and the invalid-JSON rate. Re-running only scores what is missing.

## 3. CPU: MariaDB + API + web

```bash
git clone <repo> && cd Junction26
INNODB_BUFFER_POOL=8G docker compose --profile app up -d --build        # MariaDB + API/web on :8000
docker compose run --rm app python -m ingest.download --all
docker compose run --rm app python -m ingest.replay --dataset large --workers $(nproc) --record
docker compose run --rm app python -m ingest.geo
docker compose run --rm app python -m ingest.event_time
docker compose run --rm app python -m scoring.score          # or with SCORING_URL for Gemma
docker compose run --rm app python -m db.benchmark --record
```

## 4. GPU: sentence embeddings (docs/contracts.md a)

`scripts/verda/embed_sentences.py`: dataset S (`data/s`), the 2,919 topics in fi + sv + en, split with
`ingest.sentences.text_sentences()`, embedded with BAAI/bge-m3 (sentence-transformers,
`normalize_embeddings=True`, same as `ingest/embed_cpu.py`) → `data/verda/sentences-{fi,sv,en}.parquet`
+ `embed_run.json` (device, timings, sentences/s). Device auto: CUDA (fp16, batch 256) if present, else CPU.

```bash
# on the Verda GPU instance
pip install -r scripts/verda/requirements.txt
# copy data/s/articles-{fi,sv,en}.parquet (37 MB) to the instance, then:
python scripts/verda/embed_sentences.py              # all 2,919 topics
```

**CPU test first (laptop, 2026-11-14):** `--pages "Sauli Niinistö,Suomen sisällissota"`, Intel i9-8950HK
(6 cores, torch 6 threads), torch 2.2.2 CPU, sentence-transformers 3.3.1, fp32, batch 32:
**2,145 sentences in 328 s = 6.5 sentences/s** (fi 1,112 · sv 306 · en 727; model load 74 s, wall 408 s).
Sentence counts equal Jussi's stage 1 split exactly (Niinistö 242/45/169, 1918 war 870/261/558), all
vectors 1024-dim with norm 1.0. For comparison Jussi's Windows PC did 13.7 sentences/s (16 threads).
At 6.5/s all 2,919 topics would take many hours on this laptop: that is the case for the GPU.

Intel Mac note: current torch has no Intel-Mac build (stops at 2.2.2) and transformers 5 needs torch ≥ 2.6,
so the laptop pins transformers 4.46 / sentence-transformers 3.3 / numpy < 2 / pyarrow < 20 (see
`scripts/verda/requirements.txt`). Same model weights, so `model` stays `bge-m3`; Ollama was not needed.

**Full run on Verda (2026-11-14, times UTC):** A100-SXM4-80GB, €2.159/h, 22 vCPU, 117 GB RAM, 96 GB disk.

| step | time (UTC) | result |
|---|---|---|
| stop vLLM, check GPU / disk | 20:48–20:50 | GPU 0 MiB used; disk **11 GB free** (52 GB of it is the Gemma 27B HF cache) |
| repo + data | 20:50–20:51 | repo is private and the GPU has no GitHub credentials → `git bundle` of `combined` (17 MB) sent by scp, cloned from it; dataset S articles fi/sv/en downloaded, SHA256 OK |
| venv | 20:51 | `uv venv ~/embed-venv` layered on the vLLM venv's torch 2.14 cu130 + transformers 5.20 via a `.pth` file; only sentence-transformers 6.3, scikit-learn, scipy, pyarrow (+ joblib, threadpoolctl, narwhals) installed, `--no-deps`: 334 MB instead of ~7 GB for a second CUDA torch (the disk could not take it) |
| fp16 check, 2 hero topics | 20:51:49 (25 s wall) | GPU fp16 vs laptop CPU fp32 vectors, same keys and texts: cosine **min 0.99998, mean 0.999999**, 0 of 2,145 below 0.999 → fp16 kept. 1,720 sentences/s |
| **all 2,919 topics** | **20:52:40–20:55:12** | **358,553 sentences** (fi 167,278 · sv 72,023 · en 119,252); split 9.7 s, model load 4 s, **embedding 124 s = 2,892 sentences/s** (batch 256, fp16), wall 154 s |
| copy back to the Mac | 20:55:36–20:56:18 (42 s) | `sentences-{fi,sv,en}.parquet` **705 MB** (fi 331 MB · en 236 MB · sv 142 MB), SHA256 equal both ends |
| restart Gemma 27B | 20:56–21:09 | first start failed: FlashInfer JIT needs `ninja`, which is in `/root/vllm/bin` and not on PATH when the binary is called without activating the venv; restarted with `PATH=/root/vllm/bin:$PATH`, `HF_HUB_OFFLINE=1` (weights in the HF cache, so no HF token on the server), `--host 127.0.0.1`: startup complete 21:09, 74 GB GPU memory, `/v1/models` answers through the SSH tunnel |

- **Speed: 2,892 sentences/s on the A100 vs 6.5/s on the laptop CPU = ~445×.** The laptop would need
  ~15 hours (358,553 / 6.5 s) for what the GPU did in 2 minutes.
- **Cost:** the embedding job **€0.07** (124 s) / €0.09 wall incl. model load; the whole session from
  stopping vLLM to Gemma back up (20:49–21:09, ~20 min of instance time) **≈ €0.74**, most of it setup
  and the vLLM restart, not compute. Per 1,000 sentences: €0.0002.
- Disk after the run: 5.1 GB free (95 %). The outputs stay on the GPU in `~/Junction26/data/verda/`
  until we need the space.

## 5. GPU: Gemma judges sentence pairs (docs/contracts.md b)

`scoring/judge_pairs.py`: for each Finnish sentence, its **mutual-best** sv and en match (cosine distance
≤ 0.418, Jussi's stage-1 threshold) from `data/verda/sentences-*.parquet`; Gemma labels each pair
same / contradiction / framing / partial with a one-line reason and both tones, via
`response_format: json_schema` (vLLM guided decoding; `reason` comes first in the schema so the model
explains before it labels). Endpoint from `.env`: `SCORING_URL`, `SCORING_API_KEY`, `GEMMA_MODEL`.

```bash
# Verda: vllm serve google/gemma-3-12b-it --max-model-len 4096 ; laptop reaches it by SSH tunnel
python -m scoring.judge_pairs --topics Q29207,Q211855 --concurrency 32 --gpu "A100 80GB" --eur-per-hour 2.159
```

**Hero run (2026-11-14):** Verda **A100 80GB, €2.159/h, vLLM 0.33**, google/gemma-3-12b-it, from the
laptop over an SSH tunnel, concurrency 32. Start **21:05:22**, end **21:05:59 EET**.
- **430 pairs** (Niinistö fi–sv 26, fi–en 84; 1918 war fi–sv 79, fi–en 241), all judged,
  **0 invalid JSON** (0 / 430 responses), 0 failures.
- **11.6 pairs/s**; 170k prompt + 30k output tokens = 5,400 tokens/s.
- **Cost of the run: 37 s × €2.159/h = €0.022** (≈ €0.05 per 1,000 pairs). The instance is billed for
  its whole uptime, not per request: at this speed the GPU is idle most of the time unless the job is big.
- Labels: sv partial 81 · framing 11 · contradiction 10 · same 3; en partial 264 · framing 31 ·
  contradiction 22 · same 8. "partial" dominates: two different-language editions rarely say exactly the
  same thing in one sentence.
- Quality, read by hand: many "contradictions" are real (orphans 20,000 vs 15,000; Viipuri 7,000 vs
  15,000 Reds; Seraphim collar 2014 vs 2016) but some are wrong pairings (different elections) or a
  different scope read as a disagreement. Measured on 30 hand-labelled pairs: `scoring/eval/pairs_labels.csv`,
  `python -m scoring.eval_pairs`.
- **Accuracy against 30 hand-labelled pairs** (stratified by Gemma's label: 8 contradiction, 8 framing,
  4 same, 10 partial; labeller did not see Gemma's label): **60 % on the 4 labels** (18/30; also 60 %
  when the labeller's second-choice label is accepted), **70 %** on "problem (contradiction/framing) or not".
  - contradiction: precision **3/8**, recall **3/3**. Gemma finds the real ones but over-flags: different
    estimates or scopes (8,000 vs 10,000 men; battle deaths vs all deaths; 40,000 vs 39,000 paroled)
    become "contradictions".
  - framing: precision 4/8, recall 4/4. same: precision 4/4, recall 4/9 (too strict: a missing
    "Finnish media" or country name makes it "partial").
  - So contradictions are **candidates for an editor to check**, not verdicts: which fits the tool
    (a human edits). 30 pairs is a small sample; the stratification also inflates the recall estimates.
  - Next steps if time: give Gemma the neighbouring sentences as context, a second "is this really a
    contradiction?" pass, or gemma-3-27b-it on the same A100.
**v2 run, "claims first" (2026-11-14):** same A100 80GB / vLLM 0.33 / gemma-3-12b-it, concurrency 32.
Start **21:31:38**, end **21:32:47 EET** (68.8 s). Schema now has `fi_claim`, `other_claim`,
`same_specific_fact` before the label; prompt rules: contradiction only for the same specific fact
that clearly disagrees, moderate (< 25 %) estimate differences = partial, wording / naming / minor
extra detail = same (examples in the prompt deliberately not taken from the 30 labelled pairs).
Code also downgrades contradiction → partial when `same_specific_fact` is false: **fired 0 times**.
- 430 pairs, 0 invalid JSON, **6.3 pairs/s** (more output tokens per pair), **€0.041**.
- Labels: sv same 43 · partial 57 · framing 3 · contradiction 2; en same 179 · partial 133 · framing 9 ·
  contradiction 4 (v1: 11 same, 32 contradiction, 42 framing in total).
- On the same 30 labels (v1 → v2): contradiction precision **3/8 → 2/3**, recall 3/3 → 2/3;
  framing precision 4/8 → 1/1 but recall **4/4 → 1/4**; same precision 4/4 → 8/20, recall 4/9 → 8/9;
  partial 7/10 → 4/6, recall 7/14 → 4/14. Accuracy **60 % → 50 %**; problem-vs-not 70 % → 83 %.
- Reading: the rule fixed over-flagging but over-corrected toward "same" (9 of the 14 human
  "partial" and 3 of 4 "framing" became "same"). Remaining false contradictions: two different
  elections (37 % vs 62.7 %) and battle deaths vs all deaths, both with `same_specific_fact` wrongly
  true, so the 12B model's scope judgement is the weak point. Contradiction precision 67 % < the 75 %
  target → next: **gemma-3-27b-it**.
- Note: the 30 pairs informed the new rules, so they are not a clean test any more. **Held-out set:
  20 new pairs** in `scoring/eval/pairs_test.csv` (stratified by v2 label, excluding the 30, Gemma's
  label hidden).
- **Held-out result (20 pairs, labelled after v2 was frozen):** v2 accuracy **65 %** (13/20; 70 % accepting
  the labeller's second choice) vs v1 50 % (10/20). v2 per label: contradiction precision **2/3**,
  recall 2/3; same 4/5 and 4/5; partial 6/7, recall 6/11; framing precision **1/5** (the new weak
  spot: added detail or reasoning read as framing). v1 never said "same" (recall 0/5).
  The sample is stratified by v2's labels, so v2's precision figures are the fairer comparison.
- **Contradiction precision, v2, all 50 labelled pairs: 4/6 (67 %)**, still under the 75 % target.
  Both false ones: two different elections read as one (37 % vs 62.7 %) and battle deaths vs all deaths.
  Missed: the Tampere Red Guard losses (500–800 vs 1,000–1,500 killed), which v2 called partial.
- 3 of the 20 held-out pairs are **misaligned** (unrelated sentences paired by embedding); v2 labelled
  all three partial. That is a matching problem (threshold / mutual-best), not a Gemma one.
**v2 prompt on gemma-3-27b-it (2026-11-14):** same A100 80GB, vLLM 0.33, same prompt, schema and 430
pairs, concurrency 32. Start **22:07:02**, end **22:09:16 EET** (134 s). 0 invalid JSON, 1 contradiction
downgraded by the same_specific_fact rule. **3.2 pairs/s, €0.081.** Labels: sv same 18 · partial 70 ·
framing 12 · contradiction 5; en same 78 · partial 203 · framing 34 · contradiction 10.

| | v1 · 12B | v2 · 12B | v2 · 27B |
|---|---|---|---|
| accuracy, 30 dev pairs | 60 % | 50 % | **70 %** |
| accuracy, 20 held-out | 50 % | 65 % | **70 %** |
| accuracy, all 50 | 56 % | 56 % | **70 %** |
| problem-vs-not, all 50 | 70 % | 78 % | 78 % |
| contradiction precision / recall (50) | 5/10 · 5/6 | **4/6** · 4/6 | 3/6 · 3/6 |
| framing precision / recall (50) | 4/12 · 4/5 | 2/6 · 2/5 | 2/4 · 2/5 |
| same precision / recall (50) | 4/4 · 4/14 | 12/25 · 12/14 | **11/14 · 11/14** |
| partial precision / recall (50) | 15/24 · 15/25 | 10/13 · 10/25 | **19/26 · 19/25** |
| pairs/s (concurrency 32) | 11.6 | 6.3 | 3.2 |
| cost of the 430-pair run | €0.022 | €0.041 | €0.081 |
| € per 1,000 pairs | 0.05 | 0.10 | 0.19 |

- 27B is clearly better at same vs partial (the bulk of the labels) and is the best overall, at 2× the
  cost of 12B (v2) and half the speed. Per 1,000 pairs still €0.19.
- **Contradiction precision did not improve (3/6).** 27B flags scope differences as contradictions
  (battle deaths vs all deaths; a total death toll) and *misses* obvious ones: the Seraphim collar
  2014 vs 2016 and the Tampere Red Guard losses are "partial" for 27B.
- **Agreement of 12B and 27B (both say contradiction):** 4 of 430 pairs; on the labelled ones
  precision **3/4**, but recall 3/6. Either model: 17 pairs, precision 4/8, recall 4/6. The samples
  are tiny (6 human contradictions in 50 pairs): treat these as directions, not results.
- Conclusion for the product: show contradictions as **candidates** ("possible contradiction, check
  the sources"), sorted by agreement of the two models; use 27B labels for same / partial / framing.
**Top-300 worklist run (2026-11-14/15):** Jussi's `data/verda/top_topics.txt` (top 300 of /api/worklist,
different-subject topics excluded), mutual one-to-one pairs within 0.418, v2 prompt, from the laptop
over the SSH tunnel.

| step | time | result |
|---|---|---|
| **27B judges all pairs** (`--tag 27b-top300`, concurrency 128) | 23:13:13–23:50:27 EET (2,234 s) | **7,401 pairs** from all 300 topics, 7,399 judged (2 failed after retries, 6 invalid JSON = 0.08 %), **3.3 pairs/s**, 4.8 M prompt + 0.8 M output tokens, **€1.34** |
| stop vLLM, delete only the 27B model cache (`huggingface_hub` `delete_revisions`) | 21:57:30–21:57:42 UTC | 54.9 GB freed; bge-m3 kept; disk 5.1 → 57 GB free |
| **download gemma-3-12b-it** (HF token in the environment for that one command only, via ssh stdin; unset after; in no file) | 21:57:50–21:58:37 UTC | **24.4 GB in 47 s** (≈ 520 MB/s) |
| start vLLM 12B (`--host 127.0.0.1`, same key, `HF_HUB_OFFLINE=1`) | 21:58:46–22:00:56 UTC | KV cache 129,711 tokens (31.7 × 4k requests; 27B had 36,037 = 8.8 ×) |
| **12B judges the 27B contradictions** (`--only-pairs … --only-label contradiction --tag 12b-contra`) | 00:01:30–00:02:06 EET (35 s) | **269 pairs**, 0 invalid JSON, **7.6 pairs/s**, **€0.021** |

- 27B labels: sv same 1,334 · partial 1,617 · contradiction 111 · framing 90; en same 1,337 · partial
  2,579 · contradiction 158 · framing 173. 18 contradictions were downgraded by the
  same_specific_fact rule.
- **Concurrency 128 did not speed 27B up:** with 27B's weights on the A100 the KV cache holds only
  ~36k tokens, so vLLM ran ~52 requests at a time and queued the rest (log: "Running: 52 reqs,
  Waiting: 46 reqs"). Memory, not the client, is the limit; 12B has 3.6× the KV room.
- **12B agrees on 47 of the 269** (17 %, in 38 topics); it calls 167 partial, 52 same, 3 framing.
  Agreed examples: Lorentz Creutz's term as governor (different end years), a death year in *Poika ja
  ilves*, population density of Haukipudas, the date the Treaty of Tartu ratifications were exchanged.
  On the hero labels, both-agree contradictions were right 3 of 4 times: these 47 are the strongest
  candidates for the worklist.
- Swap overhead (delete + download + vLLM start): ≈ 3.5 min ≈ €0.12. Total for this run ≈ €1.48.
- Outputs (on the laptop, `data/verda/`): `judgements-27b-top300.parquet` + `judgements-detail-27b-top300.csv`
  + `judge_run-27b-top300.json`; `judgements-12b-contra.parquet` + detail CSV + run JSON.
- Prompt iteration: one smoke test of 8 pairs called "leader until 2001" vs "succeeded in 2001" a
  contradiction; added "first ask whether both could be true at the same time". It still does: noted.

## Log

| Time | What | Machine | Result |
|---|---|---|---|
| 2026-11-14 17:57 | embed_sentences.py, 2 hero topics (CPU test) | laptop i9-8950HK, CPU | 2,145 sentences, 6.5 sentences/s |
| 2026-11-14 21:05 | judge_pairs.py, 2 hero topics, 430 pairs | Verda A100 80GB, vLLM 0.33, gemma-3-12b-it | 11.6 pairs/s, 0 % invalid JSON, €0.022 |
| 2026-11-14 21:31 | judge_pairs.py v2 (claims first), same 430 pairs | Verda A100 80GB, vLLM 0.33, gemma-3-12b-it | 6.3 pairs/s, 0 % invalid JSON, €0.041 |
| 2026-11-14 22:07 | judge_pairs.py v2, same 430 pairs | Verda A100 80GB, vLLM 0.33, gemma-3-27b-it | 3.2 pairs/s, 0 % invalid JSON, €0.081 |
| 2026-11-14 20:52 UTC | embed_sentences.py, all 2,919 topics, 358,553 sentences | Verda A100 80GB, fp16 | 2,892 sentences/s, 124 s, €0.07 (session ≈ €0.74) |
| 2026-11-14 23:13 | judge_pairs.py v2, top-300 topics, 7,401 pairs | Verda A100 80GB, vLLM 0.33, gemma-3-27b-it, conc. 128 | 3.3 pairs/s, 37 min, 0.08 % invalid JSON, €1.34 |
| 2026-11-14 21:57 UTC | swap 27B → 12B: delete 27B cache, download 12B (24.4 GB in 47 s), start vLLM | Verda A100 80GB | 3.5 min, ≈ €0.12 |
| 2026-11-15 00:01 | judge_pairs.py v2, the 269 27B contradictions | Verda A100 80GB, vLLM 0.33, gemma-3-12b-it | 7.6 pairs/s, 35 s, €0.021; agrees on 47 |

## Throughput & cost (→ docs/numbers.md and the pitch)

| Model | GPU | Sentences/s | €/h | €/1k sentences | All of dataset M (est.) | All fi-Wikipedia (est.) |
|---|---|---|---|---|---|---|
| | | | | | | |

| Job | Model | GPU | Throughput | €/h | €/1k items |
|---|---|---|---|---|---|
| pair judgements | gemma-3-12b-it, prompt v1 (vLLM 0.33) | A100 80GB | 11.6 pairs/s (concurrency 32) | 2.159 | 0.05 |
| pair judgements | gemma-3-12b-it, prompt v2 | A100 80GB | 6.3 pairs/s | 2.159 | 0.10 |
| pair judgements | gemma-3-27b-it, prompt v2 | A100 80GB | 3.2 pairs/s | 2.159 | 0.19 |
| sentence embeddings | bge-m3, fp16, batch 256 | A100 80GB | 2,892 sentences/s | 2.159 | 0.0002 |
| sentence embeddings (CPU test) | bge-m3 | none (laptop i9) | 6.5 sentences/s | – | – |

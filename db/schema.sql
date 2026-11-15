-- AikaKone — the one schema of the app. Applied by
-- `python -m common.schema`. Change only by team agreement, and log it in docs/decisions.md.
--
-- Part 1 (sentences): article, article_sentence, sentence_score, sentence_event_time, article_geo,
--                     article_stats, load_log.
-- Part 2 (places):    article_list, place, page_place, place_link (where articles sit on the map).
-- page_origin is created and filled by ingest/build_origin.py, next to its query.
--
-- Core idea: we version *sentences*, not just articles. Every distinct sentence of an article is
-- a row in article_sentence; when a revision removes it, MariaDB moves it to history; when a
-- later revision brings the exact same sentence back, it gets a new row with the same sent_hash.
-- So "how many lives did this sentence have" = COUNT(*) FOR SYSTEM_TIME ALL, i.e. edit wars are
-- plain SQL.
--
-- Historical time: the loader writes Wikipedia's real edit times into row_start/row_end with
-- SET system_versioning_insert_history = 1 (MariaDB >= 10.11). A Wikipedia edit time *is* a
-- transaction time, so FOR SYSTEM_TIME AS OF '2012-01-01' means "what Wikipedia said that day".
-- All sessions use time_zone '+00:00' (Wikipedia times are UTC).

-- One row per article = what Wikipedia shows today; every earlier version is a history row.
-- ALL versions are kept here, vandalism included: the place views (ingest/place_links.py) apply
-- their own 48-hour revert filter, and the sentence views (ingest/history.py) apply the blanking
-- filter when they build article_sentence. Neither filter removes rows from this table.
-- Columns come from both builds: parent_id / len / content (always loaded) from the place build,
-- n_sentences / sentence_order from the sentence build.
-- A table loaded before the merge is brought to this shape by `python -m common.migrate`.
CREATE TABLE IF NOT EXISTS article (
  page_id        INT UNSIGNED NOT NULL,        -- Wikipedia's own id
  title          VARCHAR(512) NOT NULL,        -- can change over time: pages get renamed
  rev_id         BIGINT UNSIGNED NOT NULL,     -- Wikipedia's id of this version
  parent_id      BIGINT UNSIGNED,              -- the version this one was edited from
  editor         VARCHAR(255),                 -- user name or IP address
  anonymous      BOOL NOT NULL DEFAULT 0,      -- IP or temporary account (~2026-…)
  comment        TEXT,                         -- the edit summary
  minor          BOOL NOT NULL DEFAULT 0,
  sha1           CHAR(40),                     -- same hash = same wikitext (reverts)
  len            INT UNSIGNED,                 -- length of the wikitext in bytes
  n_sentences    INT UNSIGNED NOT NULL DEFAULT 0,
  -- Order of the sentences in this revision: concatenated 32-byte sent_hash values.
  -- Kept here (versioned with the article) so article_sentence rows never have to be updated
  -- just because a sentence moved; an update would create a fake "new life".
  sentence_order MEDIUMBLOB COMPRESSED,
  content        MEDIUMTEXT COMPRESSED,        -- raw wikitext, compressed value by value
  row_start      TIMESTAMP(6) GENERATED ALWAYS AS ROW START INVISIBLE,
  row_end        TIMESTAMP(6) GENERATED ALWAYS AS ROW END INVISIBLE,
  PERIOD FOR SYSTEM_TIME (row_start, row_end),
  PRIMARY KEY (page_id),
  KEY rev_key (rev_id),
  KEY title_key (title),
  KEY (sha1),
  -- MariaDB's own history index is ordered by row_end; "as of <old date>" otherwise scans every
  -- later version (measured in mariadb-system-versioning-wikipedia).
  KEY start_key (page_id, row_start)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  WITH SYSTEM VERSIONING;

-- One row per (article, distinct sentence) while the sentence is in the article.
CREATE TABLE IF NOT EXISTS article_sentence (
  page_id    INT UNSIGNED NOT NULL,
  sent_hash  BINARY(32) NOT NULL,              -- SHA-256 of the normalised sentence
  position   INT UNSIGNED NOT NULL,            -- position when (re)introduced; current order is in article.sentence_order
  text       TEXT NOT NULL,
  rev_id     BIGINT UNSIGNED NOT NULL,         -- revision that (re)introduced it
  editor     VARCHAR(255),
  anonymous  BOOL NOT NULL DEFAULT 0,
  -- The sentence this one rewrote: removed in the same revision, most similar wording.
  -- Its life ended exactly at this row's row_start, so the chain is walked with
  -- WITH RECURSIVE … JOIN article_sentence FOR SYSTEM_TIME ALL ON (sent_hash, row_end).
  prev_hash  BINARY(32) NULL,
  row_start  TIMESTAMP(6) GENERATED ALWAYS AS ROW START INVISIBLE,
  row_end    TIMESTAMP(6) GENERATED ALWAYS AS ROW END INVISIBLE,
  PERIOD FOR SYSTEM_TIME (row_start, row_end),
  PRIMARY KEY (page_id, sent_hash),            -- MariaDB adds row_end implicitly: many lives allowed
  KEY start_key (page_id, row_start),
  KEY hash_key (sent_hash)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
  WITH SYSTEM VERSIONING;

-- The sentence order of every revision, when `article` was loaded before the sentence tables
-- (the combined app: `article` holds every version and its history rows cannot be updated).
-- One row per revision id; `kept` = 0 for a revision the vandalism filter dropped, which carries
-- the order of the last kept revision. Queries read this first, then article.sentence_order.
CREATE TABLE IF NOT EXISTS article_sentence_order (
  rev_id          BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  page_id         INT UNSIGNED NOT NULL,
  kept            BOOL NOT NULL,
  n_sentences     INT UNSIGNED NOT NULL,
  sentence_order  MEDIUMBLOB COMPRESSED,
  KEY (page_id)
);

-- Gemma's judgement of a sentence (written by scoring/score.py). Not versioned: a sentence's
-- text never changes, so neither does its score. Keyed by hash, shared across articles.
CREATE TABLE IF NOT EXISTS sentence_score (
  sent_hash    BINARY(32) NOT NULL PRIMARY KEY,
  event_name   VARCHAR(255),                   -- name used for the article's main event, if any
  tone         ENUM('neutral','loaded','partisan'),
  neutrality   DECIMAL(3,2),                   -- 0 = partisan … 1 = neutral
  loaded_terms JSON,
  model        VARCHAR(64),
  scored_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY event_key (event_name)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- BITEMPORAL: the second time axis. article_sentence's system time says *when Wikipedia said
-- it*; this application-time period says *when the events the sentence talks about happened*
-- (from the years it mentions: "1918", "6.12.1917", "1800-luvulla" -> 1800-01-01 .. 1900-01-01).
-- Together: "what did Wikipedia say on 2012-01-01 about the events of 1917-1918?" =
--   article_sentence FOR SYSTEM_TIME AS OF '2012-01-01'  JOIN  event_from < 1919 AND event_to > 1917.
-- Keyed by hash: a sentence's text decides what it is about. Sentences without years have no row.
CREATE TABLE IF NOT EXISTS sentence_event_time (
  sent_hash   BINARY(32) NOT NULL PRIMARY KEY,
  event_from  DATE NOT NULL,
  event_to    DATE NOT NULL,                  -- exclusive, as in every MariaDB period
  source      VARCHAR(32) NOT NULL DEFAULT 'years-regex',
  PERIOD FOR event_time (event_from, event_to),
  KEY event_time_key (event_from, event_to)
) CHARACTER SET utf8mb4;

-- Where an article is on Earth (for the globe). From the article's own coordinates, or the place
-- its infobox names (source = 'place:<title>'). Not versioned: we place the article where it is now.
-- pt is a MariaDB spatial POINT(lon lat) with a SPATIAL INDEX: "what is near where I clicked"
-- is MBRContains + ST_Distance_Sphere.
CREATE TABLE IF NOT EXISTS article_geo (
  page_id  INT UNSIGNED NOT NULL PRIMARY KEY,
  lat      DOUBLE NOT NULL,
  lon      DOUBLE NOT NULL,
  pt       POINT NOT NULL,
  source   VARCHAR(300),
  SPATIAL INDEX (pt)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Per-article history summary, written once at load time (ingest/replay.py; backfill with
-- python -m ingest.stats). The globe reads this instead of re-aggregating 800k revisions and
-- 1.4M sentence lives on every request.
CREATE TABLE IF NOT EXISTS article_stats (
  page_id             INT UNSIGNED NOT NULL PRIMARY KEY,
  title               VARCHAR(512),               -- copies of the current article row, so the article
  n_sentences         INT UNSIGNED,               -- picker never scans the history rows of `article`
  revisions           INT UNSIGNED NOT NULL,
  reverts             INT UNSIGNED NOT NULL,      -- wikitext identical to an earlier version, not the previous one
  lives               INT UNSIGNED NOT NULL,      -- article_sentence rows, all system time
  distinct_sentences  INT UNSIGNED NOT NULL,      -- returns = lives - distinct_sentences
  first_rev           TIMESTAMP(6) NULL,
  last_rev            TIMESTAMP(6) NULL,
  KEY title_key (title)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Load bookkeeping: makes the loader resumable and feeds /stats.
CREATE TABLE IF NOT EXISTS load_log (
  page_id     INT UNSIGNED NOT NULL PRIMARY KEY,
  dataset     VARCHAR(32) NOT NULL,
  revisions   INT UNSIGNED NOT NULL,
  lifetimes   INT UNSIGNED NOT NULL,
  seconds     DOUBLE NOT NULL,
  loaded_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;


-- ============================================================ Part 2: places (the globe)
-- Which article linked which place, and when: the second system-versioned table.

-- The articles loaded, with why they were chosen.
CREATE TABLE IF NOT EXISTS article_list (
  page_id  INT UNSIGNED NOT NULL PRIMARY KEY,
  title    VARCHAR(255) NOT NULL,
  why      VARCHAR(255)
) CHARACTER SET utf8mb4;

-- Title columns of the place tables use the binary collation: under the default accent- and
-- case-insensitive one, 'Salla' and 'Šalla' collide in the primary key.

-- 2. Places: link targets with coordinates (Wikidata P625) whose kind passes the whitelist in
--    kinds.py, plus articles' own locations (category 'own_location' when not whitelisted).
CREATE TABLE IF NOT EXISTS place (
  title      VARCHAR(255) PRIMARY KEY,
  en_label   VARCHAR(255),                    -- English Wikidata label (labels_en.py)
  qid        VARCHAR(20),
  lat        DOUBLE,
  lon        DOUBLE,
  kind       VARCHAR(50),                     -- the P31 label that matched the whitelist
  category   VARCHAR(20),                     -- country/battle/treaty/fortress/settlement/region/island/water
  is_country BOOL NOT NULL DEFAULT 0          -- drawn as a polygon, not a heat point
) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

-- 3. The article's own location: its own P625, else its event location (P276 -> P625).
CREATE TABLE IF NOT EXISTS page_place (
  page_id     INT UNSIGNED PRIMARY KEY,
  place_title VARCHAR(255),
  KEY place_key (place_title)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;

-- 4. Place links over time, one row per (page, linked place). A row lives from the first
--    version containing the link to the first version without it; a link that comes back
--    later is a new history row.
CREATE TABLE IF NOT EXISTS place_link (
  page_id     INT UNSIGNED NOT NULL,
  to_place    VARCHAR(255) NOT NULL,
  mentions    SMALLINT UNSIGNED NOT NULL,     -- times linked in that version
  row_start   TIMESTAMP(6) GENERATED ALWAYS AS ROW START INVISIBLE,
  row_end     TIMESTAMP(6) GENERATED ALWAYS AS ROW END INVISIBLE,
  PERIOD FOR SYSTEM_TIME (row_start, row_end),
  PRIMARY KEY (page_id, to_place),
  KEY start_key (to_place, row_start)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
  WITH SYSTEM VERSIONING;



-- ============================================================ Part 3: languages (the editor tool)
-- Dataset S (release s-2026-10): the CURRENT text of the fi / sv / en articles and one bge-m3
-- vector per article. Names start with lang_ so they never clash with `article` (dataset M).
-- Loaded by `python -m ingest.load_lang`.

CREATE TABLE IF NOT EXISTS lang_article (
  lang          CHAR(2)      NOT NULL,       -- fi, sv, en
  page_id       INT UNSIGNED NOT NULL,       -- that language's own page id
  rev_id        BIGINT UNSIGNED NOT NULL,    -- the version in the snapshot
  wikidata_id   VARCHAR(20),                 -- the same topic across languages, e.g. Q29207
  title         VARCHAR(512) NOT NULL,
  url           VARCHAR(600) NOT NULL,
  date_modified DATETIME,                    -- when that version was saved (UTC)
  content       MEDIUMTEXT COMPRESSED NOT NULL,  -- clean text from FineWiki (Markdown-ish)
  len           INT UNSIGNED NOT NULL,       -- characters
  PRIMARY KEY (lang, page_id),
  KEY wikidata_key (wikidata_id, lang)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- One bge-m3 vector per article (dataset S). The model reads at most 8,192 tokens: `truncated`
-- marks articles longer than that, whose vector covers only their beginning.
CREATE TABLE IF NOT EXISTS lang_article_vector (
  lang       CHAR(2)      NOT NULL,
  page_id    INT UNSIGNED NOT NULL,
  model      VARCHAR(50)  NOT NULL,
  truncated  BOOL         NOT NULL,
  embedding  VECTOR(1024) NOT NULL,           -- a VECTOR INDEX column must be NOT NULL
  PRIMARY KEY (lang, page_id),
  -- M=16, not the default 6: with 1024 dimensions M=6 found only 79 % of the true top 10
  -- (reference/mariadb-vector-wikipedia-rag). Sessions set mhnsw_ef_search = 80.
  VECTOR INDEX (embedding) M=16 DISTANCE=cosine
);

-- The topics that exist in all three languages (same wikidata_id): the editor tool's universe.
CREATE TABLE IF NOT EXISTS lang_topic (
  wikidata_id  VARCHAR(20)  NOT NULL PRIMARY KEY,
  fi_page_id   INT UNSIGNED NOT NULL,
  sv_page_id   INT UNSIGNED NOT NULL,
  en_page_id   INT UNSIGNED NOT NULL,
  KEY (fi_page_id)
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Every sentence of a language version, with its bge-m3 vector. Split with
-- ingest.sentences.text_sentences() (docs/contracts.md). Stage 1: embedded on CPU
-- (ingest/embed_cpu.py); stage 2: imported from Verda (data/verda/sentences-*.parquet).
CREATE TABLE IF NOT EXISTS lang_sentence (
  lang         CHAR(2)      NOT NULL,
  page_id      INT UNSIGNED NOT NULL,
  sent_no      INT UNSIGNED NOT NULL,          -- 0-based, text order
  wikidata_id  VARCHAR(20)  NOT NULL,
  text         TEXT         NOT NULL,
  model        VARCHAR(50)  NOT NULL,          -- bge-m3
  embedding    VECTOR(1024) NOT NULL,          -- L2-normalised
  PRIMARY KEY (lang, page_id, sent_no),
  KEY topic_key (wikidata_id, lang),
  VECTOR INDEX (embedding) M=16 DISTANCE=cosine
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Best match of each sentence in the other language, within the same topic (db/lang_match.py).
-- direction 'fi': for each Finnish sentence, its nearest sv / en sentence;
-- direction 'other': for each sv / en sentence, its nearest Finnish sentence (finds only_sv / only_en).
CREATE TABLE IF NOT EXISTS lang_pair (
  wikidata_id  VARCHAR(20)  NOT NULL,
  other_lang   CHAR(2)      NOT NULL,          -- sv / en
  direction    ENUM('fi', 'other') NOT NULL,
  fi_sent      INT UNSIGNED NOT NULL,
  other_sent   INT UNSIGNED NOT NULL,
  distance     FLOAT        NOT NULL,          -- cosine distance
  mutual       BOOL NOT NULL DEFAULT 0,        -- each sentence is the other's best match
  matched      BOOL NOT NULL DEFAULT 0,        -- mutual AND distance < 0.418 (db/lang_match.THRESHOLD)
  PRIMARY KEY (wikidata_id, other_lang, direction, fi_sent, other_sent),
  KEY other_key (wikidata_id, other_lang, direction, other_sent)    -- "only in sv / en" lookups
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

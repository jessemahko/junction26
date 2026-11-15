-- Article picker: articles whose title matches %(q)s, most-edited first.
-- Reads only article_stats (one small row per article, written at load time). The `article`
-- table also holds every historical revision (862k rows with their sentence-order blobs), so
-- even finding the current rows there means scanning gigabytes.
SELECT page_id, title, revisions, first_rev, last_rev, COALESCE(n_sentences, 0) AS n_sentences
FROM article_stats
WHERE title LIKE %(q)s
ORDER BY revisions DESC, title
LIMIT %(limit)s

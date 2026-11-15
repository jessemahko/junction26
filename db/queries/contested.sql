-- V2: every current sentence with how contested it has been.
--   lives    : how many times this exact sentence entered the article (>1 = removed and came back)
--   rewrites : length of its rewrite chain (the sentence it replaced, the one that one replaced, …)
--              walked with a recursive CTE over FOR SYSTEM_TIME ALL: prev_hash + row_end = row_start.
WITH RECURSIVE chain AS (
  SELECT sent_hash AS root, prev_hash, row_start, 0 AS depth
  FROM article_sentence
  WHERE page_id = %(page_id)s
  UNION ALL
  SELECT c.root, p.prev_hash, p.row_start, c.depth + 1
  FROM chain c
  JOIN article_sentence FOR SYSTEM_TIME ALL p
    ON p.page_id = %(page_id)s AND p.sent_hash = c.prev_hash AND p.row_end = c.row_start
  WHERE c.depth < 500
),
rewrites AS (SELECT root AS sent_hash, MAX(depth) AS rewrites FROM chain GROUP BY root),
lives AS (
  SELECT sent_hash, COUNT(*) AS lives, MIN(row_start) AS first_seen,
         SUM(TIMESTAMPDIFF(SECOND, row_start, LEAST(row_end, NOW(6)))) / 86400 AS total_days_alive
  FROM article_sentence FOR SYSTEM_TIME ALL
  WHERE page_id = %(page_id)s
  GROUP BY sent_hash
)
SELECT cur.sent_hash, cur.text, cur.position, cur.editor, cur.row_start AS since,
       l.lives, l.first_seen, ROUND(l.total_days_alive, 1) AS total_days_alive, r.rewrites
FROM article_sentence cur
JOIN lives l    ON l.sent_hash = cur.sent_hash
JOIN rewrites r ON r.sent_hash = cur.sent_hash
WHERE cur.page_id = %(page_id)s

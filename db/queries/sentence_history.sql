-- One sentence's genealogy: the sentence and every earlier wording it replaced, newest first.
-- Starts from the latest life of %(hash)s and follows prev_hash back through history.
WITH RECURSIVE chain AS (
  SELECT sent_hash, prev_hash, text, editor, anonymous, rev_id, row_start, row_end, 0 AS depth
  FROM article_sentence FOR SYSTEM_TIME ALL
  WHERE page_id = %(page_id)s AND sent_hash = %(hash)s
    AND row_start = (SELECT MAX(row_start) FROM article_sentence FOR SYSTEM_TIME ALL
                     WHERE page_id = %(page_id)s AND sent_hash = %(hash)s)
  UNION ALL
  SELECT p.sent_hash, p.prev_hash, p.text, p.editor, p.anonymous, p.rev_id, p.row_start, p.row_end,
         c.depth + 1
  FROM chain c
  JOIN article_sentence FOR SYSTEM_TIME ALL p
    ON p.page_id = %(page_id)s AND p.sent_hash = c.prev_hash AND p.row_end = c.row_start
  WHERE c.depth < 500
)
SELECT c.sent_hash, c.text, c.editor, c.anonymous, c.rev_id, c.row_start AS `from`,
       c.row_end AS `to`, c.depth, sc.tone, sc.neutrality, sc.event_name
FROM chain c
LEFT JOIN sentence_score sc ON sc.sent_hash = c.sent_hash
ORDER BY c.depth

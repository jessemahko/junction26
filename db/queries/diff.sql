-- V1: what changed between two moments: two AS OF snapshots of the same table, anti-joined.
SELECT 'added' AS kind, t.sent_hash, t.text, t.position, t.editor, t.rev_id
FROM article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(to)s t
LEFT JOIN article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(from)s f
       ON f.page_id = t.page_id AND f.sent_hash = t.sent_hash
WHERE t.page_id = %(page_id)s AND f.sent_hash IS NULL
UNION ALL
SELECT 'removed', f.sent_hash, f.text, f.position, f.editor, f.rev_id
FROM article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(from)s f
LEFT JOIN article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(to)s t
       ON t.page_id = f.page_id AND t.sent_hash = f.sent_hash
WHERE f.page_id = %(page_id)s AND t.sent_hash IS NULL
UNION ALL
SELECT 'kept', NULL, NULL, COUNT(*), NULL, NULL
FROM article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(from)s f
JOIN article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(to)s t
  ON t.page_id = f.page_id AND t.sent_hash = f.sent_hash
WHERE f.page_id = %(page_id)s

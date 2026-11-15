-- V1: the article (revision metadata + sentence order) as it stood at %(ts)s.
-- The row_start/ORDER BY/LIMIT part is logically redundant with AS OF; it lets the optimizer
-- use start_key and read one version instead of walking the row_end-ordered history index.
-- Sentence order: article_sentence_order when `article` was loaded before the sentence tables.
SELECT a.page_id, a.title, a.rev_id, a.editor, a.anonymous, a.comment,
       COALESCE(o.n_sentences, a.n_sentences) AS n_sentences,
       COALESCE(o.sentence_order, a.sentence_order) AS sentence_order,
       a.row_start AS ts
FROM article FOR SYSTEM_TIME AS OF TIMESTAMP %(ts)s a
LEFT JOIN article_sentence_order o ON o.rev_id = a.rev_id
WHERE a.page_id = %(page_id)s AND a.row_start <= %(ts)s
ORDER BY a.row_start DESC
LIMIT 1

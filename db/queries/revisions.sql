-- Every revision of an article (timeline ticks for the slider), oldest first, with reverts:
-- a revision whose wikitext (sha1) equals an earlier one but not the one just before it.
SELECT a.rev_id, a.row_start AS ts, a.editor, a.anonymous, a.comment, a.minor,
       COALESCE(o.n_sentences, a.n_sentences) AS n_sentences,
       COALESCE(a.sha1 <> LAG(a.sha1) OVER (ORDER BY a.row_start)
                AND MIN(a.row_start) OVER (PARTITION BY a.sha1) < a.row_start, 0) AS is_revert
FROM article FOR SYSTEM_TIME ALL a
LEFT JOIN article_sentence_order o ON o.rev_id = a.rev_id
WHERE a.page_id = %(page_id)s
ORDER BY a.row_start

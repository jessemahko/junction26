-- V1: every sentence alive at %(ts)s. Ordered in Python by article.sentence_order (as_of_article).
SELECT sent_hash, text, position, rev_id, editor, anonymous, row_start AS since
FROM article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(ts)s
WHERE page_id = %(page_id)s

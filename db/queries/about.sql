-- BITEMPORAL, one article: what the article said at %(ts)s (system time) about events between
-- %(from)s and %(to)s (application time: the sentence's event_time period overlaps the range).
SELECT s.sent_hash, s.text, s.position, e.event_from, e.event_to
FROM article_sentence FOR SYSTEM_TIME AS OF TIMESTAMP %(ts)s s
JOIN sentence_event_time e ON e.sent_hash = s.sent_hash
WHERE s.page_id = %(page_id)s
  AND e.event_from < %(to)s AND e.event_to > %(from)s

-- V3: sentences that were removed and came back (more than one life), most-fought first, with
-- every life: who added it, when, and who removed it (= the article revision that starts exactly
-- when the life ends).
SELECT s.sent_hash, s.text, w.lives, s.row_start AS `from`, s.row_end AS `to`,
       s.editor, s.anonymous, s.rev_id,
       a.editor AS removed_by, a.anonymous AS removed_by_anonymous, a.rev_id AS removed_rev,
       a.comment AS removed_comment
FROM (SELECT sent_hash, COUNT(*) AS lives
      FROM article_sentence FOR SYSTEM_TIME ALL
      WHERE page_id = %(page_id)s
      GROUP BY sent_hash
      HAVING COUNT(*) > 1
      ORDER BY lives DESC, sent_hash
      LIMIT %(limit)s) w
JOIN article_sentence FOR SYSTEM_TIME ALL s
  ON s.page_id = %(page_id)s AND s.sent_hash = w.sent_hash
LEFT JOIN article FOR SYSTEM_TIME ALL a
  ON a.page_id = s.page_id AND a.row_start = s.row_end
ORDER BY w.lives DESC, w.sent_hash, s.row_start

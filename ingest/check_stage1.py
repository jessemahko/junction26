"""Stage 1 check: the article table answers FOR SYSTEM_TIME AS OF with real Wikipedia times.

    .venv\\Scripts\\python -m ingest.check_stage1
"""
import time
import sys
from common.db import connect

sys.stdout.reconfigure(encoding="utf-8")
con = connect(dict_rows=False)
cur = con.cursor()

cur.execute("SELECT COUNT(DISTINCT page_id), COUNT(*), MIN(row_start), MAX(row_start) "
            "FROM article FOR SYSTEM_TIME ALL")
print("article, all versions: %s articles, %s versions, %s .. %s" % cur.fetchone())

SQL = """SELECT rev_id, title, row_start, row_end, len, LEFT(content, 120)
FROM article FOR SYSTEM_TIME AS OF TIMESTAMP'2010-01-01 00:00:00'
WHERE page_id = 1150"""
t = time.perf_counter()
cur.execute(SQL)
row = cur.fetchone()
ms = (time.perf_counter() - t) * 1000
print("\n" + SQL)
rev_id, title, start, end, length, head = row
print(f"-> rev_id {rev_id} '{title}', saved {start}, current until {end}, {length} bytes ({ms:.2f} ms)")
print(f"   https://fi.wikipedia.org/?oldid={rev_id}")
print("   " + head.replace("\n", " "))
assert str(start) < "2010-01-01" <= str(end), "version is not the one current on 2010-01-01"

# The same version must be the newest one saved before the date.
cur.execute("""SELECT rev_id FROM article FOR SYSTEM_TIME ALL
               WHERE page_id = 1150 AND row_start < '2010-01-01' ORDER BY row_start DESC LIMIT 1""")
assert cur.fetchone()[0] == rev_id
cur.execute("""SELECT COUNT(*) FROM article FOR SYSTEM_TIME ALL WHERE page_id = 1150""")
print(f"   page 1150 has {cur.fetchone()[0]} versions in total; check passed")
con.close()

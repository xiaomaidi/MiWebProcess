import sqlite3, json

con = sqlite3.connect('db.sqlite3')
cur = con.cursor()
print(cur.execute("select count(*) from wp_pages").fetchone())
for r in cur.execute("select id, name, path, version from wp_pages order by id limit 50"):
    print(r)

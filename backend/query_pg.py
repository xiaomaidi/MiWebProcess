import json
import psycopg

conn = psycopg.connect(dbname='webprocess', user='postgres', password='23537777', host='127.0.0.1', port=5432)
cur = conn.cursor()
cur.execute("select schema from wp_pages where id=973")
s = cur.fetchone()[0]
if isinstance(s, str):
    s = json.loads(s)
with open('node_dump.json', 'w', encoding='utf-8') as f:
    json.dump(s['nodes']['dash-linec'], f, ensure_ascii=False, indent=2)

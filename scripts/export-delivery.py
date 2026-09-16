"""Export a credential-free SQLite snapshot and existing execution traces."""
import json
from pathlib import Path
import re
import sqlite3

root = Path(__file__).resolve().parents[1]
output = root / 'delivery' / '2026-09-16'
output.mkdir(parents=True, exist_ok=True)
destination = output / 'agentgate.db'
if destination.exists():
    raise SystemExit('Snapshot exists; refusing to overwrite')
source = sqlite3.connect(f'file:{root / "runtime/agentgate.db"}?mode=ro', uri=True)
db = sqlite3.connect(destination)
source.backup(db)
source.close()
removed = db.execute('SELECT count(*) FROM api_keys').fetchone()[0]
db.execute('DELETE FROM api_keys')
db.commit()
db.execute('VACUUM')
patterns = {
    'private_key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'token': re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    'mobile': re.compile(r'(?<![\dA-Za-z-])1[3-9]\d{9}(?![\dA-Za-z-])'),
    'id_card': re.compile(r'(?<![\dA-Za-z-])[1-9]\d{16}[\dXx](?![\dA-Za-z-])'),
}
counts = {}
hits = []
for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    rows = db.execute(f'SELECT * FROM "{table}"').fetchall()
    counts[table] = len(rows)
    for row in rows:
        for value in row:
            if isinstance(value, str):
                for kind, pattern in patterns.items():
                    if pattern.search(value):
                        hits.append({'table': table, 'kind': kind})
if hits:
    print(json.dumps({'sensitive_matches': hits}, ensure_ascii=False))
    raise SystemExit('Review required; export must not be published')
integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
assert integrity == 'ok', integrity
assert not db.execute('PRAGMA foreign_key_check').fetchall()
with (output / 'execution-traces.jsonl').open('w') as stream:
    for row in db.execute('SELECT payload FROM traces ORDER BY run_id, case_id'):
        stream.write(json.dumps(json.loads(row[0]), ensure_ascii=False) + '\n')
db.close()
print(json.dumps({'tables': counts, 'credentials_removed': removed, 'integrity': integrity}, ensure_ascii=False))

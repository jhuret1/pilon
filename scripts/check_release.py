"""Inspect only Git-tracked content. This is a guardrail, not a full secret audit."""
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
tracked = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
patterns = [r'sk-or-v1-[A-Za-z0-9]{20,}', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
            r'github_pat_[A-Za-z0-9_]{20,}', r'gh[pousr]_[A-Za-z0-9]{30,}', r'C:[/\\]Users[/\\]']
violations = []
for name in filter(None,tracked):
    path = root/name
    if name.startswith(('runtime/','data/','.venv/')) or path.suffix in ('.sqlite','.parquet','.npz'):
        violations.append(name+': forbidden artifact')
    text = path.read_text(encoding='utf-8')
    if any(re.search(pattern,text) for pattern in patterns):
        violations.append(name+': possible secret or private absolute path')
    if path.suffix == '.json' and name.startswith('src/pilon/data/'):
        data = json.loads(text)
        if data.get('synthetic') is not True or not all(i['id'].startswith('synthetic-') for i in data['items']):
            violations.append(name+': packaged corpus must be synthetic')
if violations:
    raise SystemExit('\n'.join(violations))
print(f'Checked {sum(bool(n) for n in tracked)} tracked files: no forbidden corpus artifacts or high-confidence secret patterns.')

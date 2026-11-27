from pathlib import Path
from zipfile import ZipFile

wheel, = Path('dist').glob('*.whl')
with ZipFile(wheel) as archive:
    names = archive.namelist()
    required = ['pilon/data/synthetic-products.json', 'pilon/web/index.html', 'pilon/web/style.css', 'pilon/web/app.js']
    required += ['pilon/facets/example/model.json', 'pilon/facets/example/signals.jsonl']
    assert all(name in names for name in required), 'Missing package assets'
    assert not any('runtime/' in n or 'amazon-home-kitchen.json' in n or n.endswith('.sqlite') for n in names)
print('Wheel assets and data exclusions verified.')

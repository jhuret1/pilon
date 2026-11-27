"""Optional local translations for generated analysis, never for source evidence."""
import json
from pathlib import Path


def load_display_translations(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('language') != 'en':
        raise ValueError('Display translations must declare language=en')
    strings = data.get('strings')
    if not isinstance(strings, dict) or any(not isinstance(k, str) or not k.strip()
            or not isinstance(v, str) or not v.strip() for k, v in strings.items()):
        raise ValueError('Display translations must map nonempty source strings to English strings')
    return strings


def apply_display_translations(view, translations):
    """Localize an already-detached view after grouping, leaving stored decisions intact.

    Model exports, IDs, classifications, source text, exact quotations, offsets,
    matched catalog values and counts are deliberately outside the allowlist.
    Missing translations leave the original generated wording visible.
    """
    if translations is None:
        return view
    seen = set()
    generated_fields = {'label', 'definition', 'interpretation', 'rationale', 'requested_value'}

    def walk(node, *, criterion=False):
        if isinstance(node, list):
            for child in node:
                walk(child, criterion=criterion)
        elif isinstance(node, dict):
            if id(node) in seen:
                return
            seen.add(id(node))
            for key, value in node.items():
                if (key in generated_fields or criterion and key == 'value') and isinstance(value, str):
                    node[key] = translations.get(value, value)
                elif key not in {'model', 'attributes'}:
                    walk(value, criterion=key == 'criteria')

    for section in ('candidates', 'already_represented', 'demands'):
        walk(view.get(section))
    product = view.get('product_view') or {}
    for section in ('filters', 'explore', 'covered', 'uncertain'):
        for item in product.get(section, []):
            walk(item)
            for field in ('values', 'requested_values', 'rationales'):
                item[field] = [value if field == 'values' and value in item.get('model_values', [])
                               else translations.get(value, value) for value in item.get(field, [])]
    view['presentation'] = dict(language='en', translated_generated_text=True, source_evidence_translated=False)
    return view

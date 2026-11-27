"""Canonical identity and broad family registry; never encode observed values here."""
import re
import unicodedata
import numpy as np

FAMILIES = [{'id': 'performance', 'name': 'Performance', 'definition': 'Output quality, speed, accuracy, sound and other performance attributes.'}, {'id': 'power', 'name': 'Power and battery', 'definition': 'Power supply, battery runtime, charging and energy consumption.'}, {'id': 'build', 'name': 'Build and durability', 'definition': 'Materials, physical design, dimensions, reliability and wear.'}, {'id': 'usability', 'name': 'Usability', 'definition': 'Controls, installation, accessibility and ease of use.'}, {'id': 'compatibility', 'name': 'Compatibility', 'definition': 'Compatibility with devices, software, connectors and standards.'}, {'id': 'contents', 'name': 'Package contents', 'definition': 'Included and missing accessories, components and supplies.'}, {'id': 'maintenance', 'name': 'Maintenance', 'definition': 'Cleaning, upkeep, repair and replacement of parts.'}, {'id': 'service', 'name': 'Delivery and support', 'definition': 'Shipment, packaging condition, customer support, returns and refunds.'}, {'id': 'value', 'name': 'Value and expectations', 'definition': 'Price, value for money, claims and overall satisfaction.'}]
FAMILY_VERSION='products-broad-9-v1'
ROUTING_VERSION='identity_guard_v4'

def normalized(text):
    return ' '.join(unicodedata.normalize('NFKC',str(text or '')).casefold().split())

def concept_name(text):
    return re.sub(r'[^\w]+','.',normalized(text),flags=re.UNICODE).strip('.')

def card(fact):
    name=fact.get('name',fact.get('concept',''))
    return 'Concept: '+concept_name(name)+'\nDefinition: '+normalized(fact.get('definition',''))

def family_card(family):
    return 'Broad category: '+family['name']+'\nScope: '+family['definition']

def identity_key(fact):
    return concept_name(fact.get('name',fact.get('concept'))),normalized(fact.get('definition'))

def exact_matches(assertion,facts):
    key=identity_key(assertion)
    return [f for f in facts if identity_key(f)==key]

def collisions(assertion,facts):
    name=concept_name(assertion.get('name',assertion.get('concept')))
    return [f for f in facts if concept_name(f['name'])==name]

def candidates(assertion,vector,facts,vectors,k=8):
    """Exact name/definition hits are mandatory even when absent from geometric top-K."""
    if not facts:return []
    q=np.asarray(vector,dtype=np.float32)
    scores=np.asarray([float(vectors[f['id']]@q) for f in facts])
    name,definition=identity_key(assertion)
    required=[i for i,f in enumerate(facts) if identity_key(f)[0]==name or identity_key(f)[1]==definition]
    order=list(dict.fromkeys(required+np.argsort(-scores,kind='stable')[:k].tolist()))
    return [{**facts[i],'similarity':float(scores[i]),'retrieval_reason':'exact_identity_collision' if i in required else 'definition_vector'} for i in order]


def protect_identity_candidates(assertion, facts, geometric_candidates):
    """Keep same-name/definition candidates even outside top-K. This is not a merge.

    For legacy value-bearing vectors the exact identity may have a low score;
    that is not evidence for creating a different concept. Retain all collisions
    for arbitration instead of silently choosing the first duplicate.
    """
    name, definition = identity_key(assertion)
    required = [f for f in facts if (name and identity_key(f)[0] == name)
                or (definition and identity_key(f)[1] == definition)]
    scored = {f['id']: f for f in geometric_candidates}
    result, seen = [], set()
    for f in required + geometric_candidates:
        if f['id'] in seen:
            continue
        seen.add(f['id'])
        result.append({**f, 'similarity':scored.get(f['id'], {}).get('similarity'),
                       'retrieval_reason':'identity_required' if f in required else 'evidence_vector'})
    return result

def value_preview(value):
    """A conservative, inspectable suggestion. Raw values are never overwritten."""
    raw=str(value);v=normalized(raw);intensity=None
    for prefix in ('extremely ','very ','super ','incredibly '):
        if v.startswith(prefix):
            intensity='strong';v=v[len(prefix):];break
    aliases={'great':'positive','good':'positive','excellent':'positive','wonderful':'positive',
             'fantastic':'positive','amazing':'positive','outstanding':'positive','superb':'positive',
             'bad':'negative','poor':'negative','terrible':'negative',
             'well-equipped':'well equipped','very well-equipped':'well equipped'}
    # Preserve the semantic dimension: helpful and friendly must never collapse together.
    canonical=aliases.get(v,v)
    return {'raw':raw,'canonical':canonical,'intensity':intensity,
            'status':'suggested_alias' if canonical!=raw or intensity else 'unchanged',
            'multiple_aspects':bool(re.search(r'\b(and|but)\b|,',v))}

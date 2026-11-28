"""Original synthetic demand-first, two-snapshot background demonstration."""
from copy import deepcopy
import json
from ..facets.commands import EXAMPLE
from ..facets.io import read_signals


def inputs(*, with_new_source=False):
    model=json.loads((EXAMPLE/'model.json').read_text(encoding='utf-8'))
    records=list(read_signals(EXAMPLE/'signals.jsonl'))
    model.update(version='business-model-v1', facets=[
        dict(key='width',label='Width',definition='Overall shoe width.',values=['standard','wide']),
        dict(key='terrain',label='Terrain',definition='Intended running surface.',values=[]),
        dict(key='size',label='Size',definition='Shoe size.',values=[]),
    ],assignments=[])
    model['aliases']['removable insole']=['removable insole','semelle intérieure amovible']
    model['aliases']['arch support']=['arch support','soutien de la voûte']
    model['intent_hints']=[
        dict(label='Toe box',definition='Shape and available space around the toes, distinct from overall shoe width.'),
        dict(label='Removable insole',definition='Whether the inner insole can be removed from the shoe.'),
        dict(label='Arch support',definition='Reported support beneath the arch of the foot.'),
    ]
    records += [dict(id='loop-demand-insole',role='demand',source='support_chat',category=model['category'],
                     date=model['window_end'],count=7,text='Do you have a removable insole?'),
                dict(id='loop-demand-arch',role='demand',source='site_search',category=model['category'],
                     date=model['window_end'],count=5,text='Shoes with arch support'),
                dict(id='loop-demand-unresolved',role='demand',source='feedback_form',category=model['category'],
                     date=model['window_end'],text='Something comfortable for my unusual situation.')]
    if with_new_source:
        records += [dict(id='new-pim-insole',role='catalog',source='new_supplier_feed',category=model['category'],
                         product_id='Pace 01',text='Removable insole: yes')]
    # A real multimodal adapter would have to inspect the asset. The baseline must abstain.
    records += [dict(id='loop-image',role='catalog',source='product_image',category=model['category'],
                     product_id='Cloud 05',asset_type='image',text='Product image: arch support is not verified.',asset_uri='synthetic://shoe-image')]
    return deepcopy(model),deepcopy(records)

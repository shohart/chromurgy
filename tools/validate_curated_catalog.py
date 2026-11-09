#!/usr/bin/env python3
"""Offline contract/spec validation, not a claim that the render engine is implemented."""
from pathlib import Path
import json
import sys
import yaml
from jsonschema import validate
ROOT=Path(__file__).resolve().parents[1]
def read(p): return (ROOT/p).read_text(encoding='utf-8')
cat=yaml.safe_load(read('contracts/v0.7/curated-combos-v07.yaml'))
schema=json.loads(read('contracts/v0.7/curated-combos-v07.schema.json'))
validate(instance=cat,schema=schema)
recipe_schema=json.loads(read('contracts/v0.7/render-recipe-v2.schema.json'))
prev=yaml.safe_load(read('contracts/v0.7/camera-presets.yaml'))
opt=yaml.safe_load(read('contracts/v0.7/optical-effects-catalog.yaml'))
existing={a['id'] for a in prev['composites']}
known_ops={a['id']:a for a in opt['effects']}
known_looks={a['id'] for a in prev['camera_looks']}
ref_ids=set(cat['evidence_sources'])
seen=set()
for p in cat['presets']:
    assert p['id'] not in seen and p['id'] not in existing, p['id']
    seen.add(p['id'])
    assert p['camera_look']['id'] in known_looks
    assert p['film']['id'] in cat['film_resolution_aliases']
    assert set(p['evidence_refs']) <= ref_ids
    for op in p['optical']['stack']:
        assert op['id'] in known_ops, (p['id'],op['id'])
        assert p['wave_required'] >= known_ops[op['id']].get('wave',1), (p['id'],op['id'])
    # Recipe v2 uses a concrete job seed: sample only, not a real per-source seed.
    full={k:p[k] for k in ['camera_look','film','optical','render']}
    full.update(schema_version=2,preset_id=p['id'],seed=123456)
    validate(instance=full,schema=recipe_schema)
print(f'PASS: {len(seen)} unique curated combos; all operators/looks/refs/wave dependencies resolved; v2 recipe shape valid.')
print('NOT TESTED: actual upstream film-ID resolution, raw rendering, visual quality, PhotoPrism or Web Darkroom runtime.')

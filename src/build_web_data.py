#!/usr/bin/env python3
"""Emit trimmed per-class board data for the browser app.

The full class files carry skills, aspects, uniques and every affix, which the
board viewer does not need. This keeps only boards, the nodes they reference,
glyphs and thresholds, so each class loads fast in a browser.
"""
import json, os, glob

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'data')
OUT = os.path.join(HERE, '..', 'docs', 'data')
os.makedirs(OUT, exist_ok=True)

CLASSES = ['barbarian', 'druid', 'necromancer', 'rogue', 'sorcerer',
           'spiritborn', 'paladin', 'warlock']

index = []
for cls in CLASSES:
    p = os.path.join(SRC, f'{cls}.json')
    if not os.path.exists(p):
        continue
    d = json.load(open(p))
    used = {g['node'] for b in d['boards'] for g in b['grid']}
    slim = {
        'class': d['class'],
        'gameVersion': d.get('gameVersion'),
        'scalars': d.get('scalars'),
        'boards': [{'key': b['key'], 'name': b['name'], 'width': b['width'],
                    'occupied': b['occupied'],
                    'grid': [{'i': g['i'], 'row': g['row'], 'col': g['col'],
                              'node': g['node']} for g in b['grid']]}
                   for b in d['boards']],
        'nodes': {k: {'name': v.get('name'), 'rarity': v.get('rarity'),
                      'tags': v.get('tags', []),
                      'attrs': [{'attribute': a.get('attribute'), 'value': a.get('value')}
                                for a in v.get('attrs', [])]}
                  for k, v in d['nodes'].items() if k in used},
        'glyphs': {k: {'name': v.get('name'), 'rarity': v.get('rarity'),
                       'affixes': [{'desc': a.get('desc'), 'base': a.get('base'),
                                    'perLevel': a.get('perLevel')}
                                   for a in v.get('affixes', [])]}
                   for k, v in d.get('glyphs', {}).items()},
    }
    dest = os.path.join(OUT, f'{cls}.json')
    json.dump(slim, open(dest, 'w'), separators=(',', ':'))
    kb = os.path.getsize(dest) / 1024
    index.append({'class': d['class'], 'file': f'{cls}.json', 'kb': round(kb),
                  'boards': len(slim['boards']), 'glyphs': len(slim['glyphs'])})
    print(f"{d['class']:<14}{len(slim['boards']):>3} boards  "
          f"{len(slim['nodes']):>4} nodes  {len(slim['glyphs']):>3} glyphs  {kb:>7.0f} KB")

json.dump(index, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
print(f"\ntotal {sum(x['kb'] for x in index)} KB across {len(index)} classes -> docs/data/")

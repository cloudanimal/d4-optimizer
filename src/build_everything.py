#!/usr/bin/env python3
"""Complete Diablo IV optimization corpus: everything needed to evaluate any
build for any class.

Per class: paragon boards + resolved nodes + glyphs + thresholds + skills +
skill tree + class-legal items and affixes.
Global: aspects, uniques, mythics, gems, runes, item sets, tempering, seasonal
powers, attribute and power reference tables.

Values resolved via Maxroll's formula table; board geometry verified identical
to the Blizzard dump matching the live client (3.1.3.73224).
"""
import json, os, collections, re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'd4corpus')
os.makedirs(OUT, exist_ok=True)
mx = json.load(open(os.path.join(HERE, 'raw/maxroll_data.json')))
W = 21
RARITY = {0: 'normal', 1: 'magic', 2: 'magic', 3: 'rare', 4: 'legendary'}
GLYPH_RARITY = {0: 'common', 1: 'rare', 2: 'legendary', 3: 'unique'}
MAGIC = {0: 'common', 1: 'magic', 2: 'rare', 3: 'unique', 4: 'mythic'}
TREE_ALIAS = {'Paladin': 'Paladin_NEW'}
TAG = re.compile(r'\{[^}]*\}')

formulas = {k: v[0]['formula'] for k, v in mx['attributeFormulas'].items() if v}
attrs_tbl = mx.get('attributes') or {}


def clean(s):
    return TAG.sub('', s or '').replace('\r\n', ' ').strip() or None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def attr_name(aid):
    e = attrs_tbl.get(str(aid)) if isinstance(attrs_tbl, dict) else None
    return e.get('name') if isinstance(e, dict) else (e if isinstance(e, str) else None)


def legal(entry, ci):
    cf = entry.get('classFilter')
    return True if not cf else (len(cf) > ci and bool(cf[ci]))


# ---------- shared resolution ----------
nodes = {k: {'name': n.get('name'), 'rarity': RARITY.get(n.get('rarity'), 'unknown'),
             'attrs': [{'attribute': attr_name(a.get('id')), 'attr_id': a.get('id'),
                        'formula': a.get('formula'),
                        'value': num(formulas.get(a.get('formula')))}
                       for a in n.get('attributes', [])],
             'tags': n.get('tags', []), 'thresholds': n.get('thresholds', [])}
         for k, n in mx['paragonNodes'].items()}

glyphs = {}
for k, g in mx['paragonGlyphs'].items():
    aff = []
    for an in g.get('affixes', []):
        a = mx['paragonGlyphAffixes'].get(an)
        if a:
            aff.append({'key': an, 'desc': clean(a.get('desc')), 'base': a.get('base'),
                        'perLevel': a.get('perLevel'), 'displayFactor': a.get('displayFactor'),
                        'operation': a.get('operation'), 'requiredRank': a.get('requiredRank'),
                        'affectedRarity': RARITY.get(a.get('affectedRarity')),
                        'affectedAttributes': a.get('affectedAttributes', []),
                        'formula': a.get('formula'), 'tags': a.get('tags', [])})
    glyphs[k] = {'name': g.get('name'), 'rarity': GLYPH_RARITY.get(g.get('rarity')),
                 'classFilter': g.get('classFilter', []), 'affixes': aff}


def resolve_affix(k, v):
    return {'key': k, 'name': v.get('name'), 'desc': clean(v.get('desc')),
            'affixType': v.get('affixType'), 'category': v.get('category'),
            'tags': v.get('tags', []), 'itemLabels': v.get('itemLabels', []),
            'maximumRank': v.get('maximumRank'), 'classFilter': v.get('classFilter', []),
            'attributes': [{'attribute': attr_name(a.get('id')), 'attr_id': a.get('id'),
                            'formula': a.get('formula'),
                            'value': num(formulas.get(a.get('formula')))}
                           for a in v.get('attributes', [])]}


def resolve_item(k, v):
    return {'key': k, 'name': v.get('name'), 'type': v.get('type'),
            'quality': MAGIC.get(v.get('magicType'), v.get('magicType')),
            'classFilter': v.get('classFilter', []), 'implicits': v.get('implicits', []),
            'desc': clean(v.get('desc')) if v.get('desc') else None}


items, affixes = mx['items'], mx['affixes']
aspects = {k: resolve_affix(k, v) for k, v in affixes.items() if v.get('affixType') == 1}
uniques = {k: resolve_item(k, v) for k, v in items.items() if v.get('magicType') == 3}
mythics = {k: resolve_item(k, v) for k, v in items.items() if v.get('magicType') == 4}
gems = {k: resolve_item(k, v) for k, v in items.items() if v.get('type') == 'Gem'}
runes = {k: resolve_item(k, v) for k, v in items.items()
         if str(v.get('type', '')).endswith('Rune') or v.get('type') == 'Rune'}


def board_payload(key):
    b = mx['paragonBoards'][key]
    grid = [{'i': i, 'row': i // W, 'col': i % W, 'node': c}
            for i, c in enumerate(b['nodes']) if c]
    idx = {(g['row'], g['col']): g['i'] for g in grid}
    adj = {g['i']: [j for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if (j := idx.get((g['row'] + dr, g['col'] + dc))) is not None]
           for g in grid}
    return {'key': key, 'name': b.get('name'), 'width': W, 'occupied': len(grid),
            'edges': sum(len(v) for v in adj.values()) // 2, 'grid': grid, 'adj': adj}


index = []
hdr = f"{'class':<12} {'brds':>4} {'glyph':>5} {'skill':>5} {'tree':>4} {'aspect':>6} {'uniq':>5} {'affix':>5} {'KB':>5}"
print(hdr); print("-" * len(hdr))
for ci, c in sorted(mx['classes'].items(), key=lambda kv: int(kv[0])):
    cname = c.get('nameMale') or f'class{ci}'
    i = int(ci)
    boards = [board_payload(k) for k in c.get('paragonBoards', []) if k in mx['paragonBoards']]
    skill_keys = set(c.get('skills') or [])
    doc = {
        'class': cname, 'classIndex': i, 'gameVersion': mx.get('version'),
        'clientVersion': '3.1.3.73224',
        'scalars': {'MagicOffensive': 0.025, 'MagicDefensive': 0.02,
                    'RareMinorOffensive': 0.05, 'RareMinorDefensive': 0.04,
                    'RareMajorOffensive': 0.05, 'RareMajorDefensive': 0.04},
        'damageAttribute': c.get('damageAttribute'), 'damageScalar': c.get('damageScalar'),
        'primaryResource': c.get('primaryResource'),
        'boards': boards,
        'nodes': {g['node']: nodes[g['node']] for b in boards for g in b['grid']},
        'glyphs': {k: v for k, v in glyphs.items() if legal(v, i)},
        'thresholds': {k: v for k, v in mx['paragonThresholds'].items() if legal(v, i)},
        # payloads carry the actual damage formulas, e.g.
        #   "1.65*Table(34,sLevel)/(1/(0.4333/Attacks_Per_Second_Total))"
        # which is the coefficient and the power-table link a damage model needs.
        # cost and mods matter too: resource cost gates rotation, mods are the
        # skill upgrades that change what a skill actually does.
        'skills': {k: {'name': v.get('name'), 'desc': clean(v.get('desc')),
                       'type': v.get('type'), 'category': v.get('category'),
                       'damageType': v.get('damageType'), 'tags': v.get('tags', []),
                       'primaryTag': v.get('primaryTag'), 'rankup': clean(v.get('rankup')),
                       'payloads': v.get('payloads', []), 'cost': v.get('cost', []),
                       'mods': [{'name': m.get('name'), 'desc': clean(m.get('desc'))}
                                for m in (v.get('mods') or []) if isinstance(m, dict)],
                       'combatEffectChance': v.get('combatEffectChance')}
                   for k, v in mx['skills'].items()
                   if k in skill_keys or k.startswith(cname + '_')},
        'skillTree': mx['skillTrees'].get(TREE_ALIAS.get(cname, cname)),
        'aspects': {k: v for k, v in aspects.items() if legal(v, i)},
        'uniques': {k: v for k, v in uniques.items() if legal(v, i)},
        'mythics': {k: v for k, v in mythics.items() if legal(v, i)},
        'affixes': {k: resolve_affix(k, v) for k, v in affixes.items()
                    if v.get('affixType') != 1 and legal(v, i)},
    }
    fn = os.path.join(OUT, f"{cname.lower()}.json")
    json.dump(doc, open(fn, 'w'), separators=(',', ':'))
    kb = round(os.path.getsize(fn) / 1024)
    tn = len(doc['skillTree'].get('nodes', [])) if doc['skillTree'] else 0
    index.append({'class': cname, 'file': os.path.basename(fn), 'kb': kb,
                  'boards': len(boards), 'glyphs': len(doc['glyphs']),
                  'skills': len(doc['skills']), 'treeNodes': tn,
                  'aspects': len(doc['aspects']), 'uniques': len(doc['uniques']),
                  'mythics': len(doc['mythics']), 'affixes': len(doc['affixes'])})
    print(f"{cname:<12} {len(boards):>4} {len(doc['glyphs']):>5} {len(doc['skills']):>5} "
          f"{tn:>4} {len(doc['aspects']):>6} {len(doc['uniques']):>5} {len(doc['affixes']):>5} {kb:>5}")

shared = {
    'gems': gems, 'runes': runes, 'mythics': mythics, 'uniques': uniques,
    'aspects': aspects, 'itemSets': mx['itemSets'], 'itemTypes': mx['itemTypes'],
    'temperingRecipes': mx['temperingRecipes'], 'temperingGroups': mx['temperingGroups'],
    'seasonalPowers': mx['stones'], 'mercenaries': mx['mercenaries'],
    'warPlans': mx['warPlans'], 'vampiricPowers': mx['vampiricPowers'],
}
for k, v in shared.items():
    json.dump(v, open(os.path.join(OUT, f'{k}.json'), 'w'), separators=(',', ':'))
json.dump({'attributes': attrs_tbl, 'attributeDescriptions': mx['attributeDescriptions'],
           'attributeFormulas': formulas, 'powerTables': mx['powerTables'],
           'levelScaling': mx['levelScaling'], 'worldTiers': mx['worldTiers'],
           'skillTags': mx['skillTags'], 'skillCategories': mx['skillCategories'],
           'paragonBudget': mx['paragonBudget'], 'glyphsAll': glyphs},
          open(os.path.join(OUT, 'reference.json'), 'w'), separators=(',', ':'))
json.dump({'source': 'maxroll d4-tools data.min.json, geometry cross-verified vs DiabloTools/d4data',
           'gameVersion': mx.get('version'), 'clientVersion': '3.1.3.73224',
           'classes': index,
           'totals': {k: len(v) for k, v in shared.items()}},
          open(os.path.join(OUT, 'index.json'), 'w'), indent=1)

print("-" * len(hdr))
print("\nshared reference files:")
for k, v in shared.items():
    print(f"   {k:<18} {len(v):>6}")
tot = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT)) / 1024 / 1024
print(f"\ntotal corpus: {tot:.1f} MB in {len(os.listdir(OUT))} files at {OUT}")

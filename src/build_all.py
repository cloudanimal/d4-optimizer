#!/usr/bin/env python3
"""Build the complete paragon dataset: every board, every class.

Numeric values resolved via Maxroll's formula table (which supplies the six
ParagonPowerBudgetMultiplier scalars the Blizzard dump leaves symbolic).
Emits one file per class plus a combined index.
"""
import json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'paragon')
os.makedirs(OUT, exist_ok=True)
mx = json.load(open(os.path.join(HERE, 'raw/maxroll_data.json')))
W = 21
RARITY = {0: 'normal', 1: 'magic', 2: 'magic', 3: 'rare', 4: 'legendary'}

formulas = {k: v[0]['formula'] for k, v in mx['attributeFormulas'].items() if v}
attrs_tbl = mx.get('attributes') or {}
classes = mx['classes']
nodes_src = mx['paragonNodes']
boards_src = mx['paragonBoards']
glyphs_src = mx['paragonGlyphs']
gaffix_src = mx['paragonGlyphAffixes']
thresh_src = mx['paragonThresholds']


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def attr_name(aid):
    e = attrs_tbl.get(str(aid)) if isinstance(attrs_tbl, dict) else None
    if isinstance(e, dict):
        return e.get('name')
    return e if isinstance(e, str) else None


# ---- resolve every node once ----
nodes, unresolved = {}, []
for key, n in nodes_src.items():
    out_attrs = []
    for a in n.get('attributes', []):
        f = a.get('formula')
        v = num(formulas.get(f))
        if v is None:
            unresolved.append(f)
        out_attrs.append({'attribute': attr_name(a.get('id')), 'attr_id': a.get('id'),
                          'formula': f, 'value': v})
    nodes[key] = {'name': n.get('name'), 'rarity': RARITY.get(n.get('rarity'), 'unknown'),
                  'attrs': out_attrs, 'tags': n.get('tags', []),
                  'thresholds': n.get('thresholds', [])}

# ---- glyphs, with resolved scaling ----
glyphs = {}
for key, g in glyphs_src.items():
    aff = []
    for an in g.get('affixes', []):
        a = gaffix_src.get(an)
        if not a:
            continue
        aff.append({'key': an, 'desc': a.get('desc'), 'base': a.get('base'),
                    'perLevel': a.get('perLevel'), 'displayFactor': a.get('displayFactor'),
                    'operation': a.get('operation'), 'affectedRarity': a.get('affectedRarity'),
                    'requiredRank': a.get('requiredRank'), 'tags': a.get('tags', [])})
    glyphs[key] = {'name': g.get('name'), 'rarity': g.get('rarity'),
                   'classFilter': g.get('classFilter', []), 'affixes': aff}


def board_payload(key):
    b = boards_src[key]
    cells = b['nodes']
    grid, occupied = [], 0
    for i, c in enumerate(cells):
        if c:
            grid.append({'i': i, 'row': i // W, 'col': i % W, 'node': c})
            occupied += 1
    idx = {(g['row'], g['col']): g['i'] for g in grid}
    adj = {}
    for g in grid:
        nb = []
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            j = idx.get((g['row'] + dr, g['col'] + dc))
            if j is not None:
                nb.append(j)
        adj[g['i']] = nb
    return {'key': key, 'name': b.get('name'), 'width': W, 'occupied': occupied,
            'edges': sum(len(v) for v in adj.values()) // 2, 'grid': grid, 'adj': adj}


index, grand = [], collections.Counter()
print(f"{'class':<12} {'boards':>6} {'cells':>6} {'edges':>6} {'lgnd':>5} {'rare':>5} {'magic':>6} {'sockets':>8} {'glyphs':>7}")
print("-" * 74)
for ci, c in sorted(classes.items(), key=lambda kv: int(kv[0])):
    cname = c.get('nameMale') or c.get('nameFemale') or f'class{ci}'
    bkeys = c.get('paragonBoards', [])
    payload = [board_payload(k) for k in bkeys if k in boards_src]
    stat = collections.Counter()
    for b in payload:
        for g in b['grid']:
            n = nodes[g['node']]
            stat[n['rarity']] += 1
            if 'Socket' in g['node']:
                stat['socket'] += 1
        stat['cells'] += b['occupied']
        stat['edges'] += b['edges']
    ci_int = int(ci)
    cglyphs = {k: v for k, v in glyphs.items()
               if len(v['classFilter']) > ci_int and v['classFilter'][ci_int]}
    cthresh = {k: v for k, v in thresh_src.items()
               if not v.get('classFilter') or (len(v['classFilter']) > ci_int and v['classFilter'][ci_int])}
    doc = {'class': cname, 'classIndex': ci_int,
           'scalars': {'MagicOffensive': 0.025, 'MagicDefensive': 0.02,
                       'RareMinorOffensive': 0.05, 'RareMinorDefensive': 0.04,
                       'RareMajorOffensive': 0.05, 'RareMajorDefensive': 0.04},
           'boards': payload, 'glyphs': cglyphs, 'thresholds': cthresh,
           'nodes': {g['node']: nodes[g['node']] for b in payload for g in b['grid']}}
    fn = os.path.join(OUT, f"{cname.lower()}.json")
    json.dump(doc, open(fn, 'w'), separators=(',', ':'))
    grand.update(stat)
    index.append({'class': cname, 'index': ci_int, 'boards': len(payload),
                  'file': os.path.basename(fn), 'kb': round(os.path.getsize(fn) / 1024)})
    print(f"{cname:<12} {len(payload):>6} {stat['cells']:>6} {stat['edges']:>6} "
          f"{stat['legendary']:>5} {stat['rare']:>5} {stat['magic']:>6} {stat['socket']:>8} {len(cglyphs):>7}")

json.dump({'source': 'd4data geometry + maxroll resolved formulas',
           'gameVersion': mx.get('version'), 'classes': index,
           'boardsTotal': len(boards_src), 'nodesTotal': len(nodes),
           'glyphsTotal': len(glyphs)},
          open(os.path.join(OUT, 'index.json'), 'w'), indent=1)

print("-" * 74)
print(f"{'TOTAL':<12} {len(boards_src):>6} {grand['cells']:>6} {grand['edges']:>6} "
      f"{grand['legendary']:>5} {grand['rare']:>5} {grand['magic']:>6} {grand['socket']:>8} {len(glyphs):>7}")
print(f"\nnode definitions: {len(nodes)}   glyph affixes: {len(gaffix_src)}   thresholds: {len(thresh_src)}")
print(f"unresolved attribute formulas: {len(unresolved)} ({len(set(unresolved))} distinct)")
print(f"game data version: {mx.get('version')}")
print(f"written to {OUT}/  ({sum(x['kb'] for x in index)} KB across {len(index)} class files)")

#!/usr/bin/env python3
"""Resolve DiabloTools/d4data paragon files into one normalized dataset.

Board grid -> ParagonNode -> AttributeFormulas, flattened to something a solver
can consume: per board, a 21x21 grid of typed nodes with concrete stat values.
"""
import json, glob, os, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, 'raw')
W = 21

RARITY = {0: 'normal', 1: 'magic', 2: 'magic', 3: 'rare', 4: 'legendary'}


def load(p):
    with open(p) as f:
        return json.load(f)


# ---- formula table: name -> numeric value (or symbolic string if unresolved) ----
def load_formulas():
    d = load(os.path.join(HERE, 'AttributeFormulas.json'))
    out = {}
    for e in d['ptData'][0]['tEntries']:
        name = e['tHeader']['szName']
        rngs = e.get('arRanges') or []
        if not rngs:
            continue
        v = rngs[0]['tFormula']['value']
        try:
            out[name] = float(v)
        except ValueError:
            out[name] = v  # symbolic, needs calibration
    return out


FORMULAS = load_formulas()


def resolve_value(gbid_name):
    if gbid_name is None:
        return None, 'none'
    v = FORMULAS.get(gbid_name)
    if v is None:
        return None, 'missing'
    if isinstance(v, float):
        return v, 'exact'
    return v, 'symbolic'


# ---- nodes ----
def load_nodes():
    nodes = {}
    for f in glob.glob(os.path.join(RAW, 'nodes', '*.json')):
        name = os.path.basename(f)[:-5]
        d = load(f)
        attrs = []
        for a in d.get('ptAttributes') or []:
            gb = a.get('gbidFormula') or {}
            val, status = resolve_value(gb.get('name'))
            attrs.append({
                'attribute': a.get('__eAttribute_name__'),
                'formula': gb.get('name'),
                'value': val,
                'status': status,
            })
        power = d.get('snoPassivePower')
        nodes[name] = {
            'rarity': RARITY.get(d.get('eRarityOverride'), 'unknown'),
            'attrs': attrs,
            'socket': bool(d.get('bHasSocket')),
            'gate': bool(d.get('bIsGate')),
            'power': power.get('name') if power else None,
            'tags': [t.get('name') for t in (d.get('arSkillTags') or [])],
        }
    return nodes


NODES = load_nodes()


# ---- boards ----
def build_board(path):
    d = load(path)
    cells = d['arEntries']
    assert d['nWidth'] == W and len(cells) == W * W
    grid, occupied = [], 0
    for i, c in enumerate(cells):
        if not c:
            grid.append(None)
            continue
        occupied += 1
        grid.append({'row': i // W, 'col': i % W, 'node': c['name']})
    return {
        'name': os.path.basename(path).replace('.json', ''),
        'sno': d['__snoID__'],
        'width': W,
        'occupied': occupied,
        'grid': grid,
    }


def adjacency(board):
    """4-neighbour adjacency over occupied cells: what the solver walks."""
    idx = {(c['row'], c['col']): n for n, c in enumerate(board['grid']) if c}
    adj = collections.defaultdict(list)
    for (r, c), n in idx.items():
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            m = idx.get((r + dr, c + dc))
            if m is not None:
                adj[n].append(m)
    return adj


def main():
    boards = [build_board(p) for p in sorted(glob.glob(os.path.join(RAW, 'boards', '*.json')))]
    stats = collections.Counter()
    for b in boards:
        adj = adjacency(b)
        b['edges'] = sum(len(v) for v in adj.values()) // 2
        for cell in b['grid']:
            if not cell:
                continue
            n = NODES[cell['node']]
            stats[n['rarity']] += 1
            if n['socket']:
                stats['socket'] += 1
            if n['gate']:
                stats['gate'] += 1
            for a in n['attrs']:
                stats['attr_' + a['status']] += 1

    out = {'class': 'Barbarian', 'buildVersion': '3.1.3.73224',
           'nodes': NODES, 'boards': boards}
    dest = os.path.join(HERE, 'barbarian_paragon.json')
    with open(dest, 'w') as f:
        json.dump(out, f, separators=(',', ':'))

    print(f'boards: {len(boards)}')
    for b in boards:
        print(f"  {b['name']:22s} cells={b['occupied']:3d} edges={b['edges']:3d}")
    print(f'\ndistinct node types: {len(NODES)}')
    print('cell rarity/flags:', dict(stats))
    print(f'\nwrote {dest} ({os.path.getsize(dest)/1024:.0f} KB)')

    unresolved = sorted({a['formula'] for n in NODES.values() for a in n['attrs']
                         if a['status'] == 'symbolic'})
    print(f'\nunresolved formulas: {len(unresolved)}')
    for u in unresolved[:10]:
        print('  ', u, '=', FORMULAS.get(u))


if __name__ == '__main__':
    main()

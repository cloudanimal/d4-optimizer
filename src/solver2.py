#!/usr/bin/env python3
"""Paragon solver with the bucket damage model as its objective.

Structurally different from a naive per-board score: damage buckets are global,
so a board contributes a bucket VECTOR rather than a standalone number, and the
final damage is computed once from the summed vectors. That matters because
crit damage stacking into an already-huge pool is worth far less than the same
number landing in an empty bucket.

Per (board, rotation, entry gate, glyph) we grow greedily from the entry,
choosing at each step the reachable node with the best marginal damage against
the running total, and record the bucket vector at every point count. Boards
are then combined by searching board subsets and glyph assignments, splitting
the budget by marginal damage.
"""
import json, os, sys, collections, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import damage_model as DM

DATA = os.path.join(HERE, '..', 'data')
C = json.load(open(os.path.join(DATA, 'barbarian.json')))
W = 21
BUDGET = int(os.environ.get('BUDGET', 325))
NBOARDS = int(os.environ.get('NBOARDS', 5))
CAP = int(os.environ.get('CAP', 110))

GLYPHS = list(DM.GLYPHS)
STAT_ATTR = {'Strength': 'Strength_Core', 'Dexterity': 'Dexterity_Core',
             'Willpower': 'Willpower_Core', 'Intelligence': 'Intelligence_Core'}
nodes = C['nodes']


def rotate(rc, rot):
    r, c = rc
    for _ in range(rot):
        r, c = c, W - 1 - r
    return r, c


def geometry(b, rot):
    cells, gates, socket = {}, [], None
    for g in b['grid']:
        rc = rotate((g['row'], g['col']), rot)
        cells[rc] = g['node']
        if 'Gate' in g['node']:
            gates.append(rc)
        if 'Socket' in g['node']:
            socket = rc
    adj = collections.defaultdict(list)
    for (r, c) in cells:
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (r + dr, c + dc) in cells:
                adj[(r, c)].append((r + dr, c + dc))
    return cells, gates, socket, adj


def node_buckets(key, boost=0.0):
    """Bucket contribution of one node, as a dict."""
    acc = collections.defaultdict(float)
    for a in nodes[key]['attrs']:
        v, name = a.get('value'), a.get('attribute') or ''
        if v is None:
            continue
        b = DM.ATTR_BUCKET.get(name)
        if b:
            acc[b] += v * 100.0 * (1 + boost)
    if nodes[key]['rarity'] == 'legendary':
        leg = DM.LEGEND.get(key)
        if leg:
            conds = leg.get('conditions') or ['none']
            up = min(DM.UPTIME.get(c, 0.5) for c in conds)
            for m in leg.get('mult', []):
                acc['separate_multiplier'] += m * up
            for a in leg.get('add', []):
                acc['additive_damage'] += a * up
    return acc


def stat_of(key, stat):
    if not stat:
        return 0.0
    want = STAT_ATTR[stat]
    return sum(a['value'] or 0 for a in nodes[key]['attrs'] if a['attribute'] == want)


def build_curve(b, rot, entry, glyph, cap):
    """Return list of bucket dicts, index = points spent on this board."""
    cells, gates, socket, adj = geometry(b, rot)
    if entry not in cells:
        return None
    g = DM.GLYPHS.get(glyph) or {}
    stat, per5 = g.get('stat'), g.get('per5') or 0.0
    gbucket = g.get('bucket')
    up = DM.UPTIME.get(g.get('condition') or 'none', 1.0)
    nodeboost = (per5 / 100.0) if gbucket == 'node_boost' else 0.0

    diamond = set()
    if socket:
        sr, sc = socket
        diamond = {rc for rc in cells if abs(rc[0] - sr) + abs(rc[1] - sc) <= 5}

    def contrib(rc):
        boost = nodeboost if (rc in diamond and nodes[cells[rc]]['rarity'] == 'magic') else 0.0
        return node_buckets(cells[rc], boost)

    owned = {entry}
    acc = collections.defaultdict(float)
    for k, v in contrib(entry).items():
        acc[k] += v
    stat_in = stat_of(cells[entry], stat) if entry in diamond else 0.0

    def with_glyph(acc, stat_in):
        out = collections.defaultdict(float, acc)
        if gbucket and gbucket != 'node_boost' and per5:
            out[gbucket] += (stat_in // 5) * per5 * up
        if g.get('legendary_mult'):
            out['separate_multiplier'] += g['legendary_mult'] * up
        return out

    def score(acc, stat_in):
        tot = dict(DM.BASELINE)
        for k, v in with_glyph(acc, stat_in).items():
            tot[k] = tot.get(k, 0.0) + v
        return DM.damage(tot)

    curve = [None] * (cap + 1)
    curve[1] = (dict(with_glyph(acc, stat_in)), score(acc, stat_in))
    frontier = set(adj[entry])
    cur = curve[1][1]
    for k in range(2, cap + 1):
        best, bestrc, bestacc, beststat = None, None, None, None
        for rc in frontier:
            a2 = collections.defaultdict(float, acc)
            for kk, vv in contrib(rc).items():
                a2[kk] += vv
            s2 = stat_in + (stat_of(cells[rc], stat) if rc in diamond else 0.0)
            sc = score(a2, s2)
            if best is None or sc > best:
                best, bestrc, bestacc, beststat = sc, rc, a2, s2
        if bestrc is None:
            curve[k] = curve[k - 1]
            continue
        owned.add(bestrc)
        acc, stat_in, cur = bestacc, beststat, best
        curve[k] = (dict(with_glyph(acc, stat_in)), cur)
        frontier.discard(bestrc)
        frontier |= {x for x in adj[bestrc] if x not in owned}
    for k in range(cap + 1):
        if curve[k] is None:
            curve[k] = curve[k - 1] if k else ({}, DM.damage(DM.BASELINE))
    return curve


def total_damage(sel, curves, alloc):
    tot = dict(DM.BASELINE)
    for board, glyph in sel:
        vec = curves[board][glyph][alloc[board]][0]
        for k, v in vec.items():
            tot[k] = tot.get(k, 0.0) + v
    return DM.damage(tot)


def split(sel, curves, budget, cap):
    alloc = {b: 1 for b, _ in sel}
    left = budget - len(alloc)
    while left > 0:
        best, bestb = None, None
        for b, _ in sel:
            if alloc[b] + 1 > cap:
                continue
            alloc[b] += 1
            d = total_damage(sel, curves, alloc)
            alloc[b] -= 1
            if best is None or d > best:
                best, bestb = d, b
        if bestb is None:
            break
        alloc[bestb] += 1
        left -= 1
    return total_damage(sel, curves, alloc), alloc


def main():
    print(f"budget {BUDGET}, {NBOARDS} boards, cap {CAP}/board")
    print(f"baseline relative damage {DM.damage(DM.BASELINE):,.1f}\n")
    curves = collections.defaultdict(dict)
    for b in C['boards']:
        for gl in GLYPHS:
            best = None
            for rot in range(4):
                cells, gates, socket, adj = geometry(b, rot)
                for entry in (gates or [min(cells)]):
                    cv = build_curve(b, rot, entry, gl, CAP)
                    if cv and (best is None or cv[CAP][1] > best[CAP][1]):
                        best = cv
                        meta = (rot, entry)
            curves[b['name']][gl] = best
            curves[b['name']].setdefault('_meta', {})[gl] = meta

    base = DM.damage(DM.BASELINE)
    print(f"{'board':<20}{'best glyph':>10}{'x at 65 pts':>13}")
    print('-' * 44)
    for name in sorted(curves, key=lambda n: -max(curves[n][g][65][1] for g in GLYPHS)):
        g = max(GLYPHS, key=lambda g: curves[name][g][65][1])
        print(f"{name:<20}{g:>10}{curves[name][g][65][1]/base:>12.3f}x")

    others = [n for n in curves if n != 'Start']
    best = None
    for combo in itertools.combinations(others, NBOARDS - 1):
        boards = ('Start',) + combo
        for perm in itertools.permutations(GLYPHS, len(boards)):
            sel = list(zip(boards, perm))
            d, alloc = split(sel, curves, BUDGET, CAP)
            if best is None or d > best[0]:
                best = (d, sel, alloc)
    d, sel, alloc = best
    print(f"\noptimal build: {d/base:.3f}x baseline")
    for b, g in sorted(sel, key=lambda t: -alloc[t[0]]):
        rot, entry = curves[b]['_meta'][g]
        print(f"   {b:<20}{alloc[b]:>4} pts  rot={rot*90:<4} glyph={g}")


if __name__ == '__main__':
    main()

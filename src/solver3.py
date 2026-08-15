#!/usr/bin/env python3
"""Paragon solver with the board attachment chain modelled.

What changed from solver2: boards are not free slots. A board is entered at one
gate, and to attach the NEXT board you must have purchased a connected path to
a second gate. That path costs points and constrains which nodes you can reach
cheaply, which is exactly the trade the previous version was getting for free
(it happily assigned 1 point to a board it could never have reached).

So each board is evaluated in two modes:
  terminal   - last board in the chain, only needs to grow from its entry
  through    - must also own a path to an exit gate, so the exit path is
               forced first and the remaining points grow from there

The solver then chooses the chain length, which boards, their rotations, entry
and exit gates, and the glyph assignment, under one shared point budget.
"""
import json, os, sys, collections, itertools, heapq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import damage_model as DM

DATA = os.path.join(HERE, '..', 'data')
C = json.load(open(os.path.join(DATA, 'barbarian.json')))
W = 21
BUDGET = int(os.environ.get('BUDGET', 325))
MAXB = int(os.environ.get('NBOARDS', 5))
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
    cells, gates, socket, start = {}, [], None, None
    for g in b['grid']:
        rc = rotate((g['row'], g['col']), rot)
        cells[rc] = g['node']
        if 'Gate' in g['node']:
            gates.append(rc)
        if 'Socket' in g['node']:
            socket = rc
        if g['node'].startswith('StartNode'):
            start = rc
    adj = collections.defaultdict(list)
    for (r, c) in cells:
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (r + dr, c + dc) in cells:
                adj[(r, c)].append((r + dr, c + dc))
    return cells, gates, socket, adj, start


def shortest_path(adj, src, dst):
    prev, seen = {src: None}, {src}
    q = collections.deque([src])
    while q:
        u = q.popleft()
        if u == dst:
            break
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                prev[v] = u
                q.append(v)
    if dst not in prev:
        return None
    path, cur = [], dst
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    return path[::-1]


def node_buckets(key, boost=0.0):
    acc = collections.defaultdict(float)
    for a in nodes[key]['attrs']:
        v, name = a.get('value'), a.get('attribute') or ''
        if v is None:
            continue
        bk = DM.ATTR_BUCKET.get(name)
        if bk:
            acc[bk] += v * 100.0 * (1 + boost)
    if nodes[key]['rarity'] == 'legendary':
        leg = DM.LEGEND.get(key)
        if leg:
            up = min(DM.UPTIME.get(c, 0.5) for c in (leg.get('conditions') or ['none']))
            for m in leg.get('mult', []):
                acc['separate_multiplier'] += m * up
            for a in leg.get('add', []):
                acc['additive_damage'] += a * up
    return acc


def stat_of(key, stat):
    if not stat:
        return 0.0
    return sum(a['value'] or 0 for a in nodes[key]['attrs']
               if a['attribute'] == STAT_ATTR[stat])


def curve(b, rot, entry, glyph, cap, exit_gate=None):
    """Bucket-vector curve. If exit_gate is set, its path is bought first."""
    cells, gates, socket, adj, start = geometry(b, rot)
    if entry not in cells:
        return None
    g = DM.GLYPHS.get(glyph) or {}
    stat, per5 = g.get('stat'), g.get('per5') or 0.0
    gb = g.get('bucket')
    up = DM.UPTIME.get(g.get('condition') or 'none', 1.0)
    nodeboost = (per5 / 100.0) if gb == 'node_boost' else 0.0

    diamond = set()
    if socket:
        sr, sc = socket
        diamond = {rc for rc in cells if abs(rc[0] - sr) + abs(rc[1] - sc) <= 5}

    def contrib(rc):
        boost = nodeboost if (rc in diamond and nodes[cells[rc]]['rarity'] == 'magic') else 0.0
        return node_buckets(cells[rc], boost)

    owned, acc, stat_in = set(), collections.defaultdict(float), 0.0

    def take(rc):
        nonlocal stat_in
        owned.add(rc)
        for k, v in contrib(rc).items():
            acc[k] += v
        if rc in diamond:
            stat_in += stat_of(cells[rc], stat)

    seed = [entry]
    if exit_gate is not None:
        p = shortest_path(adj, entry, exit_gate)
        if p is None:
            return None
        seed = p
    for rc in seed:
        take(rc)
    forced = len(owned)
    if forced > cap:
        return None

    def vec(acc, stat_in):
        out = collections.defaultdict(float, acc)
        if gb and gb != 'node_boost' and per5:
            out[gb] += (stat_in // 5) * per5 * up
        if g.get('legendary_mult'):
            out['separate_multiplier'] += g['legendary_mult'] * up
        return dict(out)

    def score(v):
        tot = dict(DM.BASELINE)
        for k, x in v.items():
            tot[k] = tot.get(k, 0.0) + x
        return DM.damage(tot)

    out = [None] * (cap + 1)
    v = vec(acc, stat_in)
    out[forced] = (v, score(v), forced)
    frontier = {x for rc in owned for x in adj[rc] if x not in owned}
    for k in range(forced + 1, cap + 1):
        best = None
        for rc in frontier:
            a2 = collections.defaultdict(float, acc)
            for kk, vv in contrib(rc).items():
                a2[kk] += vv
            s2 = stat_in + (stat_of(cells[rc], stat) if rc in diamond else 0.0)
            vv2 = vec(a2, s2)
            sc = score(vv2)
            if best is None or sc > best[0]:
                best = (sc, rc, a2, s2, vv2)
        if best is None:
            out[k] = out[k - 1]
            continue
        sc, rc, acc, stat_in, vv2 = best
        acc = collections.defaultdict(float, acc)
        owned.add(rc)
        out[k] = (vv2, sc, forced)
        frontier.discard(rc)
        frontier |= {x for x in adj[rc] if x not in owned}
    for k in range(cap + 1):
        if out[k] is None:
            out[k] = out[k - 1] if k and out[k - 1] else ({}, DM.damage(DM.BASELINE), forced)
    return out


def best_curves(cap):
    """curves[board][glyph][mode] -> (curve, rot, entry, exit)."""
    res = collections.defaultdict(lambda: collections.defaultdict(dict))
    for b in C['boards']:
        for gl in GLYPHS:
            for mode in ('terminal', 'through'):
                best = None
                for rot in range(4):
                    cells, gates, socket, adj, start = geometry(b, rot)
                    ents = [start] if start else (gates or [min(cells)])
                    for entry in ents:
                        exits = ([None] if mode == 'terminal'
                                 else [x for x in gates if x != entry])
                        for ex in exits:
                            cv = curve(b, rot, entry, gl, cap, ex)
                            if cv and (best is None or cv[cap][1] > best[0][cap][1]):
                                best = (cv, rot, entry, ex)
                res[b['name']][gl][mode] = best
    return res


def evaluate(chain, curves, budget, cap):
    """chain = [(board, glyph)], first is Start. Returns (damage, alloc)."""
    modes = ['through'] * (len(chain) - 1) + ['terminal']
    mins = []
    for (b, g), m in zip(chain, modes):
        e = curves[b][g][m]
        if not e:
            return None
        mins.append(e[0][cap][2])   # forced path cost
    if sum(mins) > budget:
        return None
    alloc = {b: mn for (b, _), mn in zip(chain, mins)}
    left = budget - sum(mins)

    def tot(alloc):
        acc = dict(DM.BASELINE)
        for (b, g), m in zip(chain, modes):
            for k, v in curves[b][g][m][0][alloc[b]][0].items():
                acc[k] = acc.get(k, 0.0) + v
        return DM.damage(acc)

    while left > 0:
        best, bb = None, None
        for (b, g), m in zip(chain, modes):
            if alloc[b] + 1 > cap:
                continue
            alloc[b] += 1
            d = tot(alloc)
            alloc[b] -= 1
            if best is None or d > best:
                best, bb = d, b
        if bb is None:
            break
        alloc[bb] += 1
        left -= 1
    return tot(alloc), alloc, modes


def main():
    base = DM.damage(DM.BASELINE)
    print(f"budget {BUDGET}, up to {MAXB} boards, cap {CAP}/board")
    print(f"baseline relative damage {base:,.1f}\n")
    curves = best_curves(CAP)

    print("forced path cost to cross a board (entry gate -> exit gate):")
    for name in sorted(curves):
        e = curves[name][GLYPHS[0]]['through']
        t = curves[name][GLYPHS[0]]['terminal']
        print(f"   {name:<20} through={e[0][CAP][2] if e else '-':>3}  terminal={t[0][CAP][2] if t else '-':>3}")

    others = [n for n in curves if n != 'Start']
    best = None
    for nb in range(2, MAXB + 1):
        for combo in itertools.permutations(others, nb - 1):
            boards = ('Start',) + combo
            for perm in itertools.permutations(GLYPHS, nb):
                r = evaluate(list(zip(boards, perm)), curves, BUDGET, CAP)
                if r and (best is None or r[0] > best[0]):
                    best = (r[0], list(zip(boards, perm)), r[1], r[2])
    if not best:
        print("\nno legal chain found")
        return
    d, chain, alloc, modes = best
    print(f"\noptimal chain: {d/base:.3f}x baseline, {len(chain)} boards")
    for (b, g), m in zip(chain, modes):
        e = curves[b][g][m]
        print(f"   {b:<20}{alloc[b]:>4} pts  rot={e[1]*90:<4} glyph={g:<8} ({m}, path cost {e[0][CAP][2]})")
    print(f"   total {sum(alloc.values())} / {BUDGET}")


if __name__ == '__main__':
    main()

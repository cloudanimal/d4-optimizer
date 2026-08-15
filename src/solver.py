#!/usr/bin/env python3
"""Paragon solver, objective rebuilt around the measured glyph rule.

Model, with every constant taken from verified data:
  * Node values: exact, from the corpus (Blizzard geometry + resolved formulas).
  * Glyph bonus: for every 5 of the glyph's stat PURCHASED INSIDE a Manhattan-5
    diamond around its socket, the glyph grants its coefficient. Coefficient is
    base + perLevel * (level - 2) for "per 5 stat" affixes, and
    (base + perLevel * (level - 1)) / 10 for "bonus to nodes" affixes, both
    verified against Joe's client.
  * Each node costs 1 paragon point. Purchases must stay connected to the
    board's entry gate.

Search: per (board, rotation, entry gate, glyph) grow greedily from the entry,
each step taking the reachable node with the best marginal value per point,
which yields the full value curve in one pass. Boards are then combined with a
knapsack against the point budget, with the Start board forced.

Stated simplifications, so they are not mistaken for facts:
  - The diamond is assumed to stay within its own board.
  - The chain constraint (buying an exit gate to attach the next board) is
    charged as a flat cost rather than routed exactly.
"""
import json, os, collections, itertools
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
C = json.load(open(os.path.join(HERE, 'd4/d4corpus/barbarian.json')))
W = 21
BUDGET = int(os.environ.get('BUDGET', 325))
NBOARDS = int(os.environ.get('NBOARDS', 5))

# ---- Joe's glyphs, levels read from his client ----
GLYPH_LEVELS = {'Imbiber': 127, 'Wrath': 131, 'Exploit': 130, 'Marshal': 130, 'Twister': 150}

STAT_ATTR = {'Strength': 'Strength_Core', 'Dexterity': 'Dexterity_Core',
             'Willpower': 'Willpower_Core', 'Intelligence': 'Intelligence_Core'}

# Whirlwind weights: value of one point of each attribute, tunable.
WEIGHTS = {
    'Strength_Core': 0.55, 'Willpower_Core': 0.25, 'Dexterity_Core': 0.12,
    'Intelligence_Core': 0.05,
    'Vulnerable_Health_Damage_Bonus': 1.00, 'Crit_Damage_Percent': 0.90,
    'Crit_Percent_Bonus': 3.00, 'Attack_Speed_Percent_Bonus': 2.20,
    'Damage_Percent_All_From_Skills': 0.85, 'Damage_Type_Percent_Bonus': 0.80,
    'Damage_Percent_Bonus_When_Fortified': 0.70,
    'Damage_Percent_Bonus_While_Affected_By_Power': 0.70,
    'Damage_Bonus_At_High_Health': 0.55, 'Damage_Percent_Bonus_Vs_Elites': 0.45,
    'Damage_Bonus_To_Near': 0.40, 'DOT_DPS_Bonus_Percent': 0.20,
    'Damage_Percent_Bonus_Against_Dot_Type': 0.20,
    'Overpower_Damage_Bonus_Per_Stack': 0.15, 'Power_Damage_Percent_Bonus': 0.60,
}
DEFENSIVE = ('Armor', 'Resist', 'Dodge', 'Hitpoints', 'CC_', 'Healing', 'Fortified_Health')
DEF_W = 0.05
LEGENDARY_W = 8.0     # placeholder until the 9 legendary node effects are modelled

nodes = C['nodes']
glyphs = {v['name']: v for v in C['glyphs'].values() if v.get('name')}


def glyph_coeff(name):
    """Return (stat, per5_coeff, node_bonus_frac, boosted_rarity)."""
    g = glyphs.get(name)
    if not g:
        return None
    L = GLYPH_LEVELS.get(name, 100)
    stat, per5, nodeb, rar = None, 0.0, 0.0, None
    for a in g['affixes']:
        d = (a.get('desc') or '')
        if a.get('base') is None:
            continue
        if 'purchased within range' in d:
            for s in STAT_ATTR:
                if s in d:
                    stat = s
            per5 = a['base'] + a['perLevel'] * (L - 2)
        elif 'bonus to all' in d:
            nodeb = (a['base'] + a['perLevel'] * (L - 1)) / 10.0 / 100.0
            rar = a.get('affectedRarity')
            for s in STAT_ATTR:
                if s in d:
                    stat = s
    return stat, per5, nodeb, rar


def node_value(key):
    n = nodes[key]
    v = 0.0
    for a in n['attrs']:
        val, attr = a['value'], a['attribute'] or ''
        if val is None:
            continue
        if attr in WEIGHTS:
            v += val * WEIGHTS[attr]
        elif any(h in attr for h in DEFENSIVE):
            v += val * DEF_W
        else:
            v += val * 0.25
    if n['rarity'] == 'legendary':
        v += LEGENDARY_W
    return v


def node_stat(key, stat):
    if not stat:
        return 0.0
    want = STAT_ATTR[stat]
    return sum(a['value'] or 0 for a in nodes[key]['attrs'] if a['attribute'] == want)


def rotate(rc, rot):
    r, c = rc
    for _ in range(rot):
        r, c = c, W - 1 - r
    return r, c


def board_geometry(b, rot):
    cells, gates, socket = {}, [], None
    for g in b['grid']:
        rc = rotate((g['row'], g['col']), rot)
        cells[rc] = g['node']
        if 'Gate' in g['node']:
            gates.append(rc)
        if 'Socket' in g['node']:
            socket = rc
    adj = collections.defaultdict(list)
    for rc in cells:
        r, c = rc
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (r + dr, c + dc) in cells:
                adj[rc].append((r + dr, c + dc))
    return cells, gates, socket, adj


def curve_for(b, rot, entry, glyph, cap):
    """Greedy connected growth from `entry`; returns value curve v[0..cap]."""
    cells, gates, socket, adj = board_geometry(b, rot)
    if entry not in cells:
        return None
    gi = glyph_coeff(glyph) if glyph else None
    stat, per5, nodeb, rar = gi if gi else (None, 0, 0, None)
    diamond = set()
    if socket:
        sr, sc = socket
        diamond = {rc for rc in cells if abs(rc[0] - sr) + abs(rc[1] - sc) <= 5}

    base_v = {rc: node_value(k) for rc, k in cells.items()}
    stat_v = {rc: node_stat(k, stat) for rc, k in cells.items()}
    boost = {rc: (nodeb if (rar and nodes[k]['rarity'] == rar and rc in diamond) else 0.0)
             for rc, k in cells.items()}

    owned = {entry}
    stat_in = stat_v[entry] if entry in diamond else 0.0

    def total(owned, stat_in):
        v = sum(base_v[rc] * (1 + boost[rc]) for rc in owned)
        v += (stat_in // 5) * per5
        return v

    cur = total(owned, stat_in)
    curve = [0.0] * (cap + 1)
    curve[1] = cur
    frontier = set(adj[entry])
    for k in range(2, cap + 1):
        best, bestrc = None, None
        for rc in frontier:
            s2 = stat_in + (stat_v[rc] if rc in diamond else 0.0)
            gain = total(owned | {rc}, s2) - cur
            if best is None or gain > best:
                best, bestrc = gain, rc
        if bestrc is None:
            curve[k] = curve[k - 1]
            continue
        owned.add(bestrc)
        stat_in += stat_v[bestrc] if bestrc in diamond else 0.0
        cur = total(owned, stat_in)
        curve[k] = cur
        frontier.discard(bestrc)
        frontier |= {x for x in adj[bestrc] if x not in owned}
    return curve


def best_board_curves(cap):
    """curves[board][glyph] = best curve over rotations and entry gates.

    Kept per glyph, because each glyph can only be socketed once across the
    whole build, so the board-to-glyph assignment has to be chosen globally.
    """
    out = collections.defaultdict(dict)
    for b in C['boards']:
        for gl in list(GLYPH_LEVELS) + [None]:
            best = None
            for rot in range(4):
                cells, gates, socket, adj = board_geometry(b, rot)
                for entry in (gates or [min(cells)]):
                    cv = curve_for(b, rot, entry, gl, cap)
                    if cv is None:
                        continue
                    if best is None or cv[cap] > best[0][cap]:
                        best = (cv, rot, entry, gl)
            out[b['name']][gl] = best
    return out


def split_budget(sel, curves, cap, budget):
    """Greedy marginal-value split of the budget across chosen (board, glyph)."""
    alloc = {n: 1 for n, _ in sel}
    gl = dict(sel)
    left = budget - len(alloc)
    while left > 0:
        best = None
        for n in alloc:
            cv = curves[n][gl[n]][0]
            k = alloc[n]
            if k + 1 <= cap:
                g = cv[k + 1] - cv[k]
                if best is None or g > best[0]:
                    best = (g, n)
        if best is None or best[0] <= 0:
            break
        alloc[best[1]] += 1
        left -= 1
    total = sum(curves[n][gl[n]][0][alloc[n]] for n in alloc)
    return total, alloc


def main():
    cap = min(120, BUDGET)
    print(f"budget {BUDGET} points, {NBOARDS} boards, per-board cap {cap}\n")
    curves = best_board_curves(cap)
    GL = list(GLYPH_LEVELS)
    print(f"{'board':<22}{'best glyph':>11}{'rot':>5}{'v@40':>9}{'v@70':>9}{'v@cap':>9}")
    print('-' * 66)
    rank = []
    for name, per in curves.items():
        g, ent = max(((g, e) for g, e in per.items() if e), key=lambda t: t[1][0][cap])
        rank.append((ent[0][cap], name, g, ent))
    for v, name, g, (cv, rot, entry, _) in sorted(rank, reverse=True):
        print(f"{name:<22}{str(g):>11}{rot*90:>5}{cv[40]:>9.1f}{cv[70]:>9.1f}{cv[cap]:>9.1f}")

    # choose boards AND the glyph assignment together; each glyph used once
    others = [n for n in curves if n != 'Start']
    best = None
    for combo in itertools.combinations(others, NBOARDS - 1):
        boards = ('Start',) + combo
        for perm in itertools.permutations(GL, len(boards)):
            sel = list(zip(boards, perm))
            tot, alloc = split_budget(sel, curves, cap, BUDGET)
            if best is None or tot > best[0]:
                best = (tot, alloc, dict(sel))
    tot, alloc, gl = best
    print(f"\nbest {NBOARDS}-board build, total value {tot:.1f}")
    for n, k in sorted(alloc.items(), key=lambda kv: -kv[1]):
        cv, rot, entry, _ = curves[n][gl[n]]
        print(f"   {n:<22} {k:>3} pts  rot={rot*90:<4} glyph={gl[n]:<9} value={cv[k]:7.1f}")

    # what Joe currently runs, scored the same way for comparison
    joes = {'Start': 'Imbiber', 'Warbringer': 'Wrath', 'Blood Rage': 'Twister',
            'Carnage': 'Marshal', 'Flawless Technique': 'Exploit'}
    jt, jalloc = split_budget(list(joes.items()), curves, cap, BUDGET)
    print(f"\nJoe's current board+glyph set, same objective: {jt:.1f}")
    for n, k in sorted(jalloc.items(), key=lambda kv: -kv[1]):
        cv, rot, entry, _ = curves[n][joes[n]]
        print(f"   {n:<22} {k:>3} pts  rot={rot*90:<4} glyph={joes[n]:<9} value={cv[k]:7.1f}")
    print(f"\ndelta: {tot - jt:+.1f}  ({(tot/jt-1)*100:+.1f}%)")


if __name__ == '__main__':
    main()

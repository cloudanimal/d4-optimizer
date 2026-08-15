#!/usr/bin/env python3
"""Paragon allocation solver.

Per board: grow a connected region from the entry node, buying the node (or the
cheapest path to it) with the best value-per-point. That yields a full value
curve v[k] for k = 0..cap in one pass, since growth is incremental.

Across boards: knapsack the curves against the total paragon budget. This is the
same shape as spopti's mergeTrees step, and it is exact given the per-board curves.
"""
import json, heapq, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, 'barbarian_paragon.json')))
W = 21

# ---- objective: Whirlwind stat weights -------------------------------------
# Marginal value of one point of each attribute. Defaults reflect a crit/vuln
# driven Whirlwind profile; these are the knob the user tunes, and they are what
# a full damage model would eventually replace.
WEIGHTS = {
    'Strength_Core': 0.55, 'Strength_Total': 0.55,
    'Willpower_Core': 0.25, 'Willpower_Total': 0.25,
    'Dexterity_Core': 0.10, 'Intelligence_Core': 0.05,
    'Vulnerable_Health_Damage_Bonus': 1.00,
    'Critical_Hit_Damage_Bonus': 0.90,
    'Critical_Hit_Chance_Bonus': 3.00,
    'Attack_Speed_Bonus': 2.20,
    'Damage_Percent_All_From_Skills': 0.80,
    'Damage_Bonus_Physical': 0.75,
    'Damage_Bonus_Bleed': 0.60,
    'Overpower_Damage_Bonus': 0.20,
}
# Rarity fallbacks, so unweighted offensive nodes still register something.
DEFAULT_OFFENSIVE = 0.30
DEFENSIVE_HINTS = ('Armor', 'Resistance', 'Dodge', 'Life', 'Damage_Reduction',
                   'CCDuration', 'Thorns')
DEFENSIVE_WEIGHT = 0.08
LEGENDARY_BONUS = 6.0   # legendary node passive, pending per-power modelling
SOCKET_BONUS = 12.0     # a socketed glyph, pending calibration

# Values still symbolic pending the six-scalar calibration. Placeholder of 1.0
# keeps them in the running without pretending to precision.
SYMBOLIC_ASSUMED = 1.0


def node_value(n):
    v = 0.0
    for a in n['attrs']:
        amt = a['value'] if a['status'] == 'exact' else SYMBOLIC_ASSUMED
        if not isinstance(amt, (int, float)):
            amt = SYMBOLIC_ASSUMED
        attr = a['attribute'] or ''
        if attr in WEIGHTS:
            v += amt * WEIGHTS[attr]
        elif any(h in attr for h in DEFENSIVE_HINTS):
            v += amt * DEFENSIVE_WEIGHT
        else:
            v += amt * DEFAULT_OFFENSIVE
    if n['power']:
        v += LEGENDARY_BONUS
    if n['socket']:
        v += SOCKET_BONUS
    return v


def node_stats(n):
    """Strength/Willpower contribution, for the glyph threshold check."""
    s = w = 0.0
    for a in n['attrs']:
        amt = a['value'] if isinstance(a['value'], (int, float)) else 0
        if (a['attribute'] or '').startswith('Strength'):
            s += amt
        elif (a['attribute'] or '').startswith('Willpower'):
            w += amt
    return s, w


# ---- board graph ------------------------------------------------------------
def board_graph(b):
    cells = {}
    for i, c in enumerate(b['grid']):
        if c:
            cells[(c['row'], c['col'])] = c['node']
    idx = {rc: i for i, rc in enumerate(sorted(cells))}
    names = [cells[rc] for rc in sorted(cells)]
    adj = collections.defaultdict(list)
    for rc, i in idx.items():
        r, c = rc
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            j = idx.get((r + dr, c + dc))
            if j is not None:
                adj[i].append(j)
    return names, adj, {v: k for k, v in idx.items()}


def entries(names, nodes):
    """Gates and start nodes are where a board can be entered."""
    return [i for i, nm in enumerate(names)
            if nodes[nm]['gate'] or nm.startswith('StartNode')]


def value_curve(b, nodes, cap):
    """Best value achievable with k points on this board, k = 0..cap.

    Greedy connected growth: repeatedly take the unbought node with the best
    value per point, where cost counts the connector nodes needed to reach it.
    """
    names, adj, _ = board_graph(b)
    best = [0.0] * (cap + 1)
    best_sel = [None] * (cap + 1)
    vals = [node_value(nodes[nm]) for nm in names]

    for entry in entries(names, nodes) or [0]:
        owned = {entry}
        total = vals[entry]
        curve = {1: (total, frozenset(owned))}
        while len(owned) < cap:
            # cheapest path from the owned region to every unowned node
            dist, prev = {i: 0 for i in owned}, {}
            pq = [(0, i) for i in owned]
            heapq.heapify(pq)
            seen = set()
            while pq:
                d, u = heapq.heappop(pq)
                if u in seen:
                    continue
                seen.add(u)
                for v2 in adj[u]:
                    if v2 in owned:
                        continue
                    nd = d + 1
                    if v2 not in dist or nd < dist[v2]:
                        dist[v2] = nd
                        prev[v2] = u
                        heapq.heappush(pq, (nd, v2))
            # pick the best ratio target, counting the whole connector path
            cand = None
            for t, d in dist.items():
                if t in owned or len(owned) + d > cap:
                    continue
                gain = vals[t]
                node, hops = t, 0
                while node in prev and prev[node] not in owned:
                    node = prev[node]
                    gain += vals[node]
                    hops += 1
                ratio = gain / d if d else 0
                if cand is None or ratio > cand[0]:
                    cand = (ratio, t, d, gain)
            if cand is None:
                break
            _, t, d, gain = cand
            node = t
            while node not in owned:
                owned.add(node)
                node = prev.get(node, node)
                if node in owned:
                    break
            total = sum(vals[i] for i in owned)
            curve[len(owned)] = (total, frozenset(owned))
        # fold this entry's curve into the board best
        run = 0.0
        runsel = None
        for k in range(cap + 1):
            if k in curve and curve[k][0] > run:
                run, runsel = curve[k]
            if run > best[k]:
                best[k], best_sel[k] = run, runsel
    # make monotone
    for k in range(1, cap + 1):
        if best[k] < best[k - 1]:
            best[k], best_sel[k] = best[k - 1], best_sel[k - 1]
    return best, best_sel, names


def knapsack(curves, budget, max_boards):
    """Split the budget across boards. dp[b][p] = best value."""
    n = len(curves)
    dp = [[0.0] * (budget + 1) for _ in range(max_boards + 1)]
    pick = [[None] * (budget + 1) for _ in range(max_boards + 1)]
    used = [[frozenset()] * (budget + 1) for _ in range(max_boards + 1)]
    for slot in range(1, max_boards + 1):
        for p in range(budget + 1):
            dp[slot][p] = dp[slot - 1][p]
            pick[slot][p] = pick[slot - 1][p]
            used[slot][p] = used[slot - 1][p]
            for bi in range(n):
                if bi in used[slot - 1][p]:
                    continue
                for k in range(1, min(p, len(curves[bi]) - 1) + 1):
                    prev = dp[slot - 1][p - k]
                    if bi in used[slot - 1][p - k]:
                        continue
                    v = prev + curves[bi][k]
                    if v > dp[slot][p]:
                        dp[slot][p] = v
                        pick[slot][p] = (bi, k, p - k)
                        used[slot][p] = used[slot - 1][p - k] | {bi}
    return dp, pick


def main(budget=225, max_boards=5, cap=90):
    nodes = DATA['nodes']
    boards = DATA['boards']
    curves, sels, allnames = [], [], []
    for b in boards:
        c, s, nm = value_curve(b, nodes, cap)
        curves.append(c)
        sels.append(s)
        allnames.append(nm)
        print(f"  {b['name']:20s} v@20={c[20]:7.1f}  v@45={c[45]:7.1f}  v@90={c[cap]:7.1f}")

    # The starting board is mandatory and always occupies the first slot, so
    # solve the rest against the remaining budget and pick the best split.
    start = next(i for i, b in enumerate(boards) if b['name'].endswith('_00'))
    rest = [c for i, c in enumerate(curves) if i != start]
    remap = [i for i in range(len(curves)) if i != start]
    dp, pick = knapsack(rest, budget, max_boards - 1)

    bestk, bestv = 0, -1
    for k in range(1, min(cap, budget) + 1):
        v = curves[start][k] + dp[max_boards - 1][budget - k]
        if v > bestv:
            bestv, bestk = v, k
    print(f"\nbest total value @ {budget} points, {max_boards} boards: {bestv:.1f}")
    print(f"(starting board forced: {boards[start]['name']} @ {bestk} pts)")

    slot, p, plan = max_boards - 1, budget - bestk, [(boards[start]['name'], bestk, start)]
    while slot > 0 and pick[slot][p]:
        bi, k, rem = pick[slot][p]
        plan.append((boards[remap[bi]]['name'], k, remap[bi]))
        slot, p = slot - 1, rem
    plan = plan[:1] + list(reversed(plan[1:]))
    plan.reverse()
    print('\nallocation:')
    tot_s = tot_w = 0
    for name, k, bi in reversed(plan):
        sel = sels[bi][k]
        s = w = 0
        rar = collections.Counter()
        for i in sel or ():
            n = nodes[allnames[bi][i]]
            ds, dw = node_stats(n)
            s, w = s + ds, w + dw
            rar[n['rarity']] += 1
            if n['socket']:
                rar['socket'] += 1
        tot_s += s
        tot_w += w
        print(f"  {name:20s} {k:3d} pts  value={curves[bi][k]:7.1f}  "
              f"Str+{s:.0f} Will+{w:.0f}  {dict(rar)}")
    print(f"\ntotals from paragon: Strength +{tot_s:.0f}, Willpower +{tot_w:.0f}")
    print("glyph thresholds need Str >= 700 + 455*slot, Will >= 190 + 70*slot")


if __name__ == '__main__':
    main()

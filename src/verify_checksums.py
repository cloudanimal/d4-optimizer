#!/usr/bin/env python3
"""Validate the reconstructed allocation against the character's own tooltips.

Five independent checksums, all read off Litel's client:
    total points spent                     325
    Marshal  Strength  purchased in range   50
    Wrath    Dexterity purchased in range   74
    Imbiber  Willpower purchased in range   69
    Exploit  Dexterity purchased in range   59

"In range" means inside a Manhattan-distance-5 diamond around that board's
glyph socket. Passing these confirms the allocation, the radius shape, the
socket positions and the node values simultaneously.
"""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('BOARD', '')
import importlib.util
spec = importlib.util.spec_from_file_location('ex', os.path.join(HERE, 'extract2.py'))
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

C = json.load(open(os.path.join(HERE, '..', 'data', 'barbarian.json')))
W = 21
STAT = {'Strength': 'Strength_Core', 'Dexterity': 'Dexterity_Core',
        'Willpower': 'Willpower_Core'}

# which glyph sits on which board, from the paragon recording
# Corrected by capacity: Start can only supply 64 Willpower so Imbiber (69)
# cannot sit there, while Flawless Technique supplies exactly 69. Likewise
# Exploit's 59 Dexterity matches Start's capacity exactly.
GLYPH_ON = {'Start': ('Exploit', 'Dexterity', 59),
            'Warbringer': ('Wrath', 'Dexterity', 74),
            'Blood Rage': ('Twister', 'Strength', None),
            'Carnage': ('Marshal', 'Strength', 50),
            'Flawless Technique': ('Imbiber', 'Willpower', 69)}

boards = {b['name']: b for b in C['boards']}


def rot_cell(rc, rot):
    r, c = rc
    for _ in range(rot):
        r, c = c, W - 1 - r
    return r, c


def analyse(path):
    r = ex.read(path, verbose=False)
    if not r:
        return None
    b = boards[r['board']]
    rot = r['rot']
    cells, socket = {}, None
    for g in b['grid']:
        rc = rot_cell((g['row'], g['col']), rot)
        cells[rc] = g['node']
        if 'Socket' in g['node']:
            socket = rc
    pur = {(int(a), int(bb)) for a, bb in zip(*r['pur'].nonzero())}
    return r, cells, socket, pur


total = 0
print(f"{'board':<20}{'agree':>7}{'pts':>5}   {'glyph':<9}{'stat':<10}{'in range':>9}{'expected':>10}  {'':<6}")
print('-' * 78)
rows = []
for p in sorted(sys.argv[1:]):
    got = analyse(p)
    if not got:
        print(f"{os.path.basename(p):<20}  unreadable")
        continue
    r, cells, socket, pur = got
    name = r['board']
    total += len(pur)
    gl, stat, expect = GLYPH_ON.get(name, (None, None, None))
    inrange = 0
    if socket and stat:
        sr, sc = socket
        want = STAT[stat]
        for rc in pur:
            if rc in cells and abs(rc[0] - sr) + abs(rc[1] - sc) <= 5:
                inrange += sum(a['value'] or 0 for a in C['nodes'][cells[rc]]['attrs']
                               if a['attribute'] == want)
    mark = ''
    if expect is not None:
        mark = 'PASS' if abs(inrange - expect) < 0.5 else f'off by {inrange-expect:+.0f}'
    print(f"{name:<20}{r['agreement']*100:>6.1f}%{len(pur):>5}   {str(gl):<9}{str(stat):<10}"
          f"{inrange:>9.0f}{('-' if expect is None else expect):>10}  {mark}")
print('-' * 78)
print(f"{'TOTAL POINTS':<20}{'':>7}{total:>5}   expected 325   "
      f"{'PASS' if total == 325 else 'off by %+d' % (total - 325)}")

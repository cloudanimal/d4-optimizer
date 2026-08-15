#!/usr/bin/env python3
"""Read every frame, then majority-vote each cell across all frames of the same
board+rotation. Per-frame threshold noise cancels; a cell purchased in most
frames is genuinely purchased.

Only frames whose occupancy matches a known board layout near-perfectly are
allowed to vote.
"""
import glob, json, os, sys, collections
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = ['consensus']
src = open(os.path.join(HERE, 'extract2.py')).read().replace(
    "if __name__ == '__main__':", "if False:")
exec(compile(src, 'extract2.py', 'exec'))

MIN_AGREE = float(os.environ.get('MIN_AGREE', 0.995))
pattern = sys.argv[1] if len(sys.argv) > 1 else 'scenes6/c_*.jpg'
pattern = os.environ.get('FRAMES', 'scenes6/c_*.jpg')

votes = collections.defaultdict(list)     # (board,rot) -> list of pur masks
occref = {}
seen = collections.Counter()

files = sorted(glob.glob(os.path.join(HERE, pattern)))
print(f"scanning {len(files)} frames (accepting agreement >= {MIN_AGREE*100:.1f}%)\n")
for p in files:
    try:
        r = read(p, verbose=False)
    except Exception:
        continue
    if not r:
        continue
    seen[(r['board'], r['rot'])] += 1
    if r['agreement'] >= MIN_AGREE:
        votes[(r['board'], r['rot'])].append(r['pur'])
        occref[(r['board'], r['rot'])] = r['occ']

print("frames seen per board (any agreement):")
for k, v in seen.most_common():
    acc = len(votes.get(k, []))
    print(f"   {k[0]:<22} rot={k[1]*90:<4} frames={v:<4} accepted={acc}")

out = {}
print("\nconsensus per board (cells purchased in > half of accepted frames):")
for (board, rot), masks in votes.items():
    if len(masks) < 3:
        print(f"   {board:<22} rot={rot*90:<4} SKIPPED, only {len(masks)} accepted frames")
        continue
    stack = np.stack(masks)
    frac = stack.mean(axis=0)
    pur = frac > 0.5
    unstable = int(((frac > 0.2) & (frac < 0.8)).sum())
    out[board] = {'rot': rot, 'frames': len(masks), 'purchased': int(pur.sum()),
                  'unstable_cells': unstable,
                  'cells': [[int(a), int(b)] for a, b in zip(*pur.nonzero())]}
    print(f"   {board:<22} rot={rot*90:<4} frames={len(masks):<3} "
          f"purchased={int(pur.sum()):3d}  ambiguous cells={unstable}")

json.dump(out, open(os.path.join(HERE, 'boards_consensus.json'), 'w'), indent=1)
tot = sum(v['purchased'] for v in out.values())
print(f"\nboards resolved: {len(out)}   total purchased nodes: {tot}")
print("checksum target: 325 points spent (note: node COST can exceed 1 per node)")

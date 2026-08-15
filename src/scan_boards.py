#!/usr/bin/env python3
"""Scan every frame of the board recording, keep only 100%-verified reads."""
import glob, json, sys, os
sys.argv = ['scan']
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'extract2.py')).read().replace(
    "if __name__ == '__main__':", "if False:")
exec(compile(src, 'extract2.py', 'exec'))

out = {}
for p in sorted(glob.glob(os.path.join(HERE, 'scenes5/b_*.jpg'))):
    try:
        r = read(p, verbose=False)
    except Exception as e:
        print(f"{os.path.basename(p)}  ERROR {e}", flush=True)
        continue
    if not r:
        print(f"{os.path.basename(p)}  no lattice fit", flush=True)
        continue
    print(f"{os.path.basename(p)}  {r['board']:<20} rot={r['rot']*90:<4} "
          f"agree={r['agreement']*100:5.1f}%  occ={int(r['occ'].sum()):3d} "
          f"pur={int(r['pur'].sum()):3d}", flush=True)
    if r['agreement'] > 0.999:
        prev = out.get(r['board'])
        if prev is None or int(r['pur'].sum()) > prev['purchased']:
            out[r['board']] = {
                'rot': int(r['rot']),
                'purchased': int(r['pur'].sum()),
                'occupied': int(r['occ'].sum()),
                'cells': [[int(a), int(b)] for a, b in zip(*r['pur'].nonzero())],
            }

json.dump(out, open(os.path.join(HERE, 'boards_read.json'), 'w'), indent=1)
print("\n=== boards verified at 100% occupancy agreement ===", flush=True)
for k, v in out.items():
    print(f"  {k:<22} rot={v['rot']*90:<4} occupied={v['occupied']:3d} purchased={v['purchased']:3d}")
print(f"\ntotal purchased across verified boards: {sum(v['purchased'] for v in out.values())}")
print("checksum target: 325 points spent")

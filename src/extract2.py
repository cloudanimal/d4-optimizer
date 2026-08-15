#!/usr/bin/env python3
"""Read a paragon board off a screenshot, with the board-match as the proof.

Pitch and phase are fit on the play area only. The 21x21 window is then slid
over the lattice and scored against all 10 known board layouts in all 4
rotations. A high-agreement match proves the alignment; a poor one means the
frame is unusable and we report that rather than guessing.
"""
import json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = json.load(open(os.path.join(HERE, '..', 'data', 'barbarian.json')))
W = 21
# play area as fractions of the frame, so it survives window resizes
PLAY_F = (0.10, 0.955, 0.240, 0.995)   # y0, y1, x0, x1

ONLY = os.environ.get('BOARD')      # optionally restrict to one known board
KNOWN = []
for b in DATA['boards']:
    if ONLY and b['name'] != ONLY:
        continue
    m = np.zeros((W, W), dtype=bool)
    for g in b['grid']:
        m[g['row'], g['col']] = True
    for rot in range(4):
        KNOWN.append((b['name'], rot, np.rot90(m, rot)))


def integral(x):
    return np.pad(x.astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))


def patch_means(ii, ys, xs, half):
    y0 = np.clip((ys - half).astype(int), 0, ii.shape[0] - 1)
    y1 = np.clip((ys + half).astype(int), 0, ii.shape[0] - 1)
    x0 = np.clip((xs - half).astype(int), 0, ii.shape[1] - 1)
    x1 = np.clip((xs + half).astype(int), 0, ii.shape[1] - 1)
    Y0, X0 = np.meshgrid(y0, x0, indexing='ij')
    Y1, X1 = np.meshgrid(y1, x1, indexing='ij')
    tot = ii[Y1, X1] - ii[Y0, X1] - ii[Y1, X0] + ii[Y0, X0]
    area = np.maximum((Y1 - Y0) * (X1 - X0), 1)
    return tot / area


def fit_pitch(profile, lo=50, hi=70):
    sig = profile - profile.mean()
    f = np.abs(np.fft.rfft(sig * np.hanning(len(sig)))) ** 2
    fr = np.fft.rfftfreq(len(sig))
    band = [(1 / x, p) for x, p in zip(fr[1:], f[1:]) if lo <= 1 / x <= hi]
    return max(band, key=lambda t: t[1])[0] if band else None


def read(path, verbose=True):
    a = np.asarray(Image.open(path).convert('RGB')).astype(float)
    Hf, Wf = a.shape[:2]
    if 0.80 <= Wf / Hf <= 1.35:
        # a board-only crop: the whole image is the 21x21 grid
        y0, y1, x0, x1 = 0, Hf, 0, Wf
    else:
        y0, y1 = int(PLAY_F[0] * Hf), int(PLAY_F[1] * Hf)
        x0, x1 = int(PLAY_F[2] * Wf), int(PLAY_F[3] * Wf)
    lum = a.mean(axis=2)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    ring = ((R > 95) & (R - G > 45) & (R - B > 45)).astype(float)

    # brightness-adaptive occupancy threshold: nodes sit well above the board
    reg = lum[y0:y1, x0:x1]
    thr = float(np.percentile(reg, 60) + 0.45 * (np.percentile(reg, 99) - np.percentile(reg, 60)))
    sub = reg > thr
    seed = fit_pitch(sub.sum(axis=0).astype(float), 40, 150) or 58.0
    ii_l, ii_r = integral(lum), integral(ring)

    # stack the 40 known masks once so each window scores in a single vector op
    KM = np.stack([km for _, _, km in KNOWN])

    # occupancy threshold is searched too: the board match decides which is right
    THRS = [float(np.percentile(reg, q)) for q in (25, 35, 45, 55, 65, 75, 85)] + [38.0, 45.0]

    def search(pitches, fys_of, fxs_of, best):
        for t in THRS:
            for pitch in pitches:
                half = pitch * 0.32
                for fy in fys_of(pitch):
                    for fx in fxs_of(pitch):
                        ys_all = np.arange(y0 + fy, y1, pitch)
                        xs_all = np.arange(x0 + fx, x1, pitch)
                        if len(ys_all) < W or len(xs_all) < W:
                            continue
                        L = patch_means(ii_l, ys_all, xs_all, half) > t
                        for r in range(len(ys_all) - W + 1):
                            for c in range(len(xs_all) - W + 1):
                                occ = L[r:r + W, c:c + W]
                                if occ.sum() < 40:
                                    continue
                                ags = (KM == occ).mean(axis=(1, 2))
                                i = int(ags.argmax())
                                if best is None or ags[i] > best[0]:
                                    name, rot, _ = KNOWN[i]
                                    best = (float(ags[i]), name, rot, fy, fx, pitch, t,
                                            ys_all[r:r + W].copy(), xs_all[c:c + W].copy())
        return best

    # the board match itself selects pitch, phase and threshold.
    # Seed from the FFT estimate and from the image dimensions, since a board
    # that fills its crop has pitch ~ width/21.
    cands = set()
    for base in (seed, (x1 - x0) / W, (y1 - y0) / W):
        for d in np.arange(-12, 12.01, 1.5):
            v = base + d
            if 38 <= v <= 160:
                cands.add(round(float(v), 2))
    best = search(sorted(cands),
                  lambda p: np.arange(0, p, 4.0), lambda p: np.arange(0, p, 4.0), None)
    if best:
        p0, fy0, fx0 = best[5], best[3], best[4]
        best = search(np.arange(p0 - 1.5, p0 + 1.51, 0.25),
                      lambda p: np.arange(max(0, fy0 - 4), fy0 + 4.01, 1.0),
                      lambda p: np.arange(max(0, fx0 - 4), fx0 + 4.01, 1.0), best)
    if not best:
        return None
    ag, name, rot, fy, fx, pitch, t, ys, xs = best
    half = pitch * 0.32
    Lm = patch_means(ii_l, ys, xs, half)
    Rm = patch_means(ii_r, ys, xs, half)
    occ = Lm > t
    pur = (Rm > 0.10) & occ
    if verbose:
        print(f"  pitch={pitch:.2f} thr={t:.0f}  match={name} rot={rot*90}  "
              f"agreement={ag*100:.1f}%  occupied={occ.sum()}  purchased={pur.sum()}")
    return dict(agreement=ag, board=name, rot=rot, occ=occ, pur=pur, pitch=pitch)


if __name__ == '__main__':
    for p in sys.argv[1:]:
        print(f"=== {os.path.basename(p)}")
        read(p)

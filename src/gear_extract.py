#!/usr/bin/env python3
"""Consolidate a character's equipped gear from OCR'd screen-recording frames.

Two ideas make this reliable rather than fuzzy:

  1. Item identity is resolved by matching the OCR'd name against the real item
     names in the corpus, so "TUSKHELM OF IORITZ", "TUSKHELM OF IORITZ" and
     "CTEPIC TUSKHELM OF IORITZ" all collapse onto one known item instead of
     being clustered against each other.

  2. Affix lines are accepted by consensus across frames. A line read
     identically in many frames is real; a line seen once is OCR noise.

Usage:  gear_extract.py <ocr_dump.txt>
"""
import json, os, re, sys, collections, difflib

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

inv = json.load(open(os.path.join(DATA, 'gear_inventory.json')))
TYPES = {t.upper() for t in inv['byType']} | {
    'CHARM', 'AMULET', 'RING', 'HELM', 'GLOVES', 'BOOTS', 'PANTS', 'CHEST ARMOR',
    'SHIELD', 'SWORD', 'AXE', 'MACE', 'DAGGER', 'POLEARM', 'STAFF', 'BOW',
    'INTEL', 'TROPHY', 'QUEST'}
NAMES = {}
for typ, lst in inv['byType'].items():
    for it in lst:
        n = (it.get('name') or '').strip()
        # only distinctly named gear: uniques, mythics and named legendaries
        # skip Blizzard placeholder / QA entries, they create false matches
        if re.search(r'^\(PH\)|^QA |placeholder|^test|^axe bad|^lewis', n, re.I):
            continue
        if len(n) > 6 and n.upper() not in TYPES and it.get('quality') in (
                'unique', 'mythic', 'rare', 'magic', 'common'):
            NAMES.setdefault(n.upper(), it)

NOISE = re.compile(r'[^A-Z ]')
STOP = re.compile(r'^(EQUIPPED|CHARACTER|ANCESTRAL|UNIQUE|LEGENDARY|MYTHIC|CLOSE|UNEQUIP)')


def normalise(s):
    return re.sub(r'\s+', ' ', NOISE.sub('', s.upper())).strip()


NORM = {normalise(k): v for k, v in NAMES.items()}
NORM_KEYS = list(NORM)


def resolve(raw, cutoff=0.72):
    """Map an OCR'd name onto a real item, or None."""
    n = normalise(raw)
    if not n or len(n) < 5:
        return None
    if n in NORM:
        return NORM[n]['name'], 1.0
    m = difflib.get_close_matches(n, NORM_KEYS, n=1, cutoff=cutoff)
    if not m:
        # try the longest token run, OCR often prefixes junk
        parts = n.split()
        for i in range(len(parts)):
            sub = ' '.join(parts[i:])
            if len(sub) < 6:
                break
            m = difflib.get_close_matches(sub, NORM_KEYS, n=1, cutoff=cutoff)
            if m:
                break
    if not m:
        return None
    return NORM[m[0]]['name'], difflib.SequenceMatcher(None, n, m[0]).ratio()


AFFIX = re.compile(r'^[•*+\-\s]*([+xX]?[\d,\.]+%?)\s+(.{4,58}?)\s*$')
SKIP = re.compile(r'item power|quality|sell value|durability|tempers|requires level|'
                  r'account bound|unequip|link|favorite|^\d[\d,\. ]*$', re.I)


def main(path):
    frames = open(path, errors='replace').read().split('=== ')
    per_item = collections.defaultdict(collections.Counter)
    frames_with = collections.Counter()
    ANC = re.compile(r'^Ancestral\s+(Mythic|Unique|Legendary|Set|Rare|Magic)', re.I)
    for fr in frames:
        lines = [l.strip() for l in fr.split('\n') if l.strip()]
        # the item name sits in caps directly above the "Ancestral <quality>" line
        anchor = next((i for i, l in enumerate(lines) if ANC.match(l)), None)
        if anchor is None:
            continue
        cand = [l for l in lines[max(0, anchor - 6):anchor]
                if l.upper() == l and len(l) > 3 and not STOP.match(l.upper())]
        if not cand:
            continue
        item, best = None, 0.0
        for joined in (' '.join(cand), cand[-1], ' '.join(cand[-2:])):
            r = resolve(joined)
            if r and r[1] > best:
                item, best = r[0], r[1]
        if not item:
            continue
        frames_with[item] += 1
        for l in lines[anchor:anchor + 22]:
            if SKIP.search(l):
                continue
            m = AFFIX.match(l)
            if m:
                txt = f"{m.group(1)} {m.group(2)}".strip()
                if 6 < len(txt) < 60:
                    per_item[item][txt] += 1

    out = {}
    print(f"{'item':<34}{'frames':>7}{'affixes':>9}")
    print('-' * 52)
    for item, c in sorted(per_item.items(), key=lambda kv: -frames_with[kv[0]]):
        n = frames_with[item]
        keep = [t for t, k in c.most_common() if k >= max(2, n * 0.35)]
        out[item] = keep
        print(f"{item[:32]:<34}{n:>7}{len(keep):>9}")
    dest = os.path.join(DATA, 'character_gear.json')
    json.dump(out, open(dest, 'w'), indent=1)
    print(f"\nresolved {len(out)} equipped items -> {dest}")
    print("\nfull affix lists:")
    for item, lines in out.items():
        print(f"\n  {item}")
        for l in lines:
            print(f"     {l}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'ocr_gear.txt')

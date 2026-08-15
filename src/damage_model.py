#!/usr/bin/env python3
"""Bucket-based damage model for Diablo IV.

Key idea that avoids needing complete gear data: a character's stats panel already
contains every gear, masterwork and tempering contribution rolled up. So we
seed the buckets from the panel and evaluate paragon choices as DELTAS on top.
Candidates are then ranked against a common baseline, which is what an
optimizer actually needs.

Bucket rules come from d4corpus/bucket_table.json, which was derived from
Blizzard's own attribute naming (Multiplicative_* versus plain), not guessed.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, '..', 'data')
BUCKETS = json.load(open(os.path.join(D, 'bucket_table.json')))
GLYPHS = json.load(open(os.path.join(D, 'glyph_model.json')))
LEGEND = json.load(open(os.path.join(D, 'legendary_nodes.json')))

ATTR_BUCKET = {a: b for b, lst in BUCKETS.items() for a in lst}

# Example baseline: a character's town stats panel (gear + current paragon,
# unconditional sources only). Replace with your own from the character sheet.
BASELINE = {
    'additive_damage': 0.0,      # panel does not expose a single additive total
    'crit_chance': 53.8,
    'crit_damage': 5110.2,
    'vulnerable': 421.1,
    'attack_speed': 20.0,
    'separate_multiplier': 0.0,
}

# How often each condition is actually live for a Whirlwind build. These are
# judgement calls, exposed here rather than buried, so they can be tuned.
UPTIME = {
    'none': 1.00, 'while_berserking': 0.90, 'while_fortified': 0.85,
    'vs_vulnerable': 0.80, 'while_healthy': 0.70, 'vs_elites': 0.25,
    'dust_devils_only': 0.00,   # set >0 only if the build generates Dust Devils
    'vs_bleeding': 0.60, 'on_overpower': 0.30, 'on_weapon_swap': 0.50,
    'on_weapon_repeat': 0.60, 'in_radius_only': 1.00, 'overpower': 0.30,
    'weapon_type_gated': 0.50, 'vs_dot_affected': 0.60, 'earthquakes_only': 0.00,
}


def blank():
    return dict(BASELINE)


def add_node(acc, node, boost=0.0):
    """Fold one purchased paragon node into the accumulator."""
    for a in node['attrs']:
        v, name = a.get('value'), a.get('attribute') or ''
        if v is None:
            continue
        b = ATTR_BUCKET.get(name)
        if not b:
            continue
        acc[b] = acc.get(b, 0.0) + v * 100.0 * (1 + boost)


def add_glyph(acc, glyph_name, stat_in_range):
    """Fold a socketed glyph's payout, scaled by stat purchased in its diamond."""
    g = GLYPHS.get(glyph_name)
    if not g or not g.get('per5'):
        return
    up = UPTIME.get(g.get('condition') or 'none', 1.0)
    if g['bucket'] == 'node_boost':
        return                      # handled as a per-node boost, not a bucket
    blocks = stat_in_range // 5
    acc[g['bucket']] = acc.get(g['bucket'], 0.0) + blocks * g['per5'] * up
    if g.get('legendary_mult'):
        acc['separate_multiplier'] = acc.get('separate_multiplier', 0.0) + \
            g['legendary_mult'] * up


def add_legendary(acc, node_key):
    leg = LEGEND.get(node_key)
    if not leg:
        return
    conds = leg.get('conditions') or ['none']
    up = min(UPTIME.get(c, 0.5) for c in conds)
    for m in leg.get('mult', []):
        acc['separate_multiplier'] = acc.get('separate_multiplier', 0.0) + m * up
    for a in leg.get('add', []):
        acc['additive_damage'] = acc.get('additive_damage', 0.0) + a * up


def damage(acc):
    """Combine buckets into one relative damage figure."""
    additive = 1 + acc.get('additive_damage', 0) / 100
    cc = min(acc.get('crit_chance', 0), 100) / 100
    cd = acc.get('crit_damage', 0) / 100
    crit = 1 + cc * cd
    vuln = 1 + (acc.get('vulnerable', 0) / 100) * UPTIME['vs_vulnerable']
    aspd = 1 + acc.get('attack_speed', 0) / 100
    mult = 1 + acc.get('separate_multiplier', 0) / 100
    return additive * crit * vuln * aspd * mult


if __name__ == '__main__':
    b = blank()
    print("baseline buckets:", {k: round(v, 1) for k, v in b.items()})
    print(f"baseline relative damage: {damage(b):,.1f}")
    for gname in GLYPHS:
        acc = blank()
        add_glyph(acc, gname, 74)
        print(f"  +{gname:<9} at 74 stat in range -> {damage(acc)/damage(b):.4f}x")

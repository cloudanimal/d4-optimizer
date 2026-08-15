// Standalone re-implementation of the spopti optimizer, to validate the reverse engineering.
// Loads the site's data files + the original Optimize class, but replaces all DOM plumbing.
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const JS = path.join(__dirname, 'javascripts');

const ctx = vm.createContext({ console, Math, Number, Object, Array, JSON });
for (const f of ['skills', 'reductions', 'spells', 'mana']) {
  const src = fs.readFileSync(path.join(JS, f + '.js'), 'utf8')
    .replace(/^\s*(const|let|var)\s+(\w+)\s*=/gm, 'globalThis.$2 =');
  vm.runInContext(src, ctx);
}
const { skillInfo, reductions, spellInfo, spell_reductions, clone } = ctx;

// --- config (what the page's input fields would supply) ---
const cfg = {
  typeDamage: 'Clan Ship',
  typeGold: 'Fairy',
  goldWeight: 0.7,
  FB: 0, FF: 0, tFA: false,           // multicast / dark angel sets
  mythics: {},                        // e.g. {BranchRed: 1.01}
  CP: 1, sClone: 35, TimeToKill: 8, CC: false,
  MaxStage: 0,
  SP: 1000,
  currLevels: Object.keys(skillInfo).map(() => 0),
  selected: Object.fromEntries(Object.keys(skillInfo).map(id => [id, true])),
};

// --- cumulative SP cost table ---
const cumSP = {};
for (const [id, s] of Object.entries(skillInfo)) {
  let t = 0; cumSP[id] = [0];
  for (let l = 1; l <= s.MaxLevel; l++) { t += parseFloat(s['Co' + (l - 1)] || 0); cumSP[id].push(t); }
}
const MAX_SKILL_LEVEL = Math.max(...Object.values(skillInfo).map(s => s.MaxLevel));
const MID = MAX_SKILL_LEVEL, SIZE = MID * 2 + 1;

function spellDamage(spells, extra) {
  let dmg = 1;
  const base = cfg.tFA ? 34 : 29;
  for (const k of spells) {
    const a = spellInfo[k]['A' + (base + extra)];
    const r = spell_reductions[k][cfg.typeDamage] + spell_reductions[k][cfg.typeGold] * cfg.goldWeight;
    dmg *= a ** r;
  }
  return dmg;
}
function lightningStrike(cA, nA, cB, nB) {
  const CC = cfg.CC ? 1.5 * 1.005 ** ((cfg.CP - 1) ** 0.8) : 1;
  const attempts = Math.floor(0.022 * clone[cfg.sClone] * CC * cfg.TimeToKill);
  let LN = 1, LC = 1, pC = 1, pN = 1;
  for (let i = 0; i < attempts; i++) { LC *= 1 - cA * pC; LN *= 1 - nA * pN; pC *= cB; pN *= nB; }
  return [1 / LN, 1 / LC];
}

// --- the payoff model: per-SP multiplicative gain of raising a skill ---
function calcEff(id, cA, nA, cB, nB, cC, nC, cost, reduction) {
  const mc = cfg.FB + cfg.FF;
  const rf = reduction / cost;
  let next, curr, r2, sp;
  switch (id) {
    case 'BurstDamageMultiCastSkill': case 'TapBoostMultiCastSkill': case 'DualPetMultiCast':
    case 'HelperBoostMultiCastSkill': case 'ClanShipVoltageMultiCastSkill': case 'ShadowCloneMultiCastSkill':
    case 'GuidedBlade': case 'StreamOfBladesMultiCastSkill':
      next = ((10 * nA) ** (nB + mc)) ** rf;
      curr = ((10 * (cA ?? 1)) ** (!cB ? 0 : cB + mc)) ** rf; break;
    case 'TwilightGatheringMultiCastSkill':
      next = (((10 * nA) ** (nB + mc)) ** rf) * (nC ** rf);
      curr = (((10 * (cA ?? 1)) ** (!cB ? 0 : cB + mc)) ** rf) * ((cC || 1) ** rf); break;
    case 'TwilightBell': case 'SummonerAutoTap': case 'PhantomBlades': case 'AlchemistMastery': {
      const spells = { TwilightBell: ['BurstDamage', 'TwilightFairy'], SummonerAutoTap: ['DualPet', 'TapBoost'],
        PhantomBlades: ['CritBoost', 'StreamOfBlades'], AlchemistMastery: ['HandOfMidas', 'GoldenMissile'] }[id];
      next = (nA ** rf) * (spellDamage(spells, nB) ** (1 / cost));
      curr = ((cA || 1) ** rf) * (spellDamage(spells, cB) ** (1 / cost)); break;
    }
    case 'PetBonusBoost':
      r2 = Number(reductions['TapDmg'][cfg.typeDamage]);
      next = (nA ** rf) * (nB ** (r2 / cost)); curr = ((cA || 1) ** rf) * ((cB || 1) ** (r2 / cost)); break;
    case 'BossDmgQTE':
      next = (nA ** rf) * ((nB || 1) ** rf); curr = ((cA || 1) ** rf) * ((cB || 1) ** rf); break;
    case 'HelperBoost': next = (1 + nA) ** rf; curr = (1 + cA) ** rf; break;
    case 'HelperInspiredWeaken': case 'ClanShipVoltage': case 'CriticalHit':
      next = (nA * nB) ** rf; curr = ((cA || 1) * (cB || 1)) ** rf; break;
    case 'HelperDmgQTE': next = nA ** (5 * rf); curr = (cA || 1) ** (5 * rf); break;
    case 'LoadedDice': case 'QuickFortune':
      next = (nA ** rf) * (nB ** (cfg.goldWeight / cost));
      curr = ((cA || 1) ** rf) * ((cB || 1) ** (cfg.goldWeight / cost)); break;
    case 'CloneDmg': next = (nA * (4 + nB)) ** rf; curr = ((cA || 1) * (4 + cB)) ** rf; break;
    case 'CritSkillBoost': { const LS = lightningStrike(cA, nA, cB, nB); next = LS[0] ** rf; curr = LS[1] ** rf; break; }
    case 'TerrifyingPact': next = (nA ** rf) * (nB ** (1 / cost)); curr = ((cA || 1) ** rf) * ((cB || 1) ** (1 / cost)); break;
    case 'PoisonedBlade': next = (1 + nA * 10) ** rf; curr = (1 + cA * 10) ** rf; break;
    case 'HandOfMidasMultiCastSkillBoost': {
      const g2 = cfg.typeGold !== 'Chesterson' ? 1 : 0;
      const A = [1, 100, 10000, 1e6, 1e8, 1e9], B = [1, 10, 100, 1000, 10000, 50000];
      next = ((A[nB + mc] * nA ** (nB + mc)) ** rf) * (B[nB + mc] ** (g2 * cfg.goldWeight / cost));
      curr = ((A[!cB ? 0 : cB + mc] * ((cA ?? 1) ** (!cB ? 0 : cB + mc))) ** rf) * (B[!cB ? 0 : cB + mc] ** (g2 * cfg.goldWeight / cost)); break;
    }
    case 'KratosSummon': next = (nA ** nB) ** rf; curr = (cA ** cB || 1) ** rf; break;
    default: next = nA ** rf; curr = (cA || 1) ** rf;
  }
  return next / curr;
}

// --- efficiency array: [0..MID-1] = per-SP gain per +N levels, [MID..] = cumulative SP cost ---
function effArray() {
  const out = [];
  for (const [id, s] of Object.entries(skillInfo)) {
    const myth = cfg.mythics[s.Branch] || 1;
    const arr = Array(SIZE).fill(1 * myth);
    const cl = cfg.currLevels[Object.keys(skillInfo).indexOf(id)];
    for (let i = cl; i <= s.MaxLevel; i++) arr[MID + i - cl] = cumSP[id][i];
    if (!cfg.selected[id] || (cfg.MaxStage && cfg.MaxStage < +s.S0)) { out.push(arr); continue; }
    for (let j = cl; j < s.MaxLevel; j++) {
      const k = j - cl;
      const cost = arr[MID + 1 + k] - arr[MID];
      const red = reductions[id][cfg.typeDamage] + reductions[id][cfg.typeGold] * cfg.goldWeight;
      arr[k] = calcEff(id, +s['A' + cl], +s['A' + (j + 1)], +s['B' + cl], +s['B' + (j + 1)],
        +s['C' + cl], +s['C' + (j + 1)], cost, red) * myth;
    }
    out.push(arr);
  }
  return out;
}

// --- reuse the site's own Optimize class verbatim, with a stubbed DOM ---
const spopti = fs.readFileSync(path.join(JS, 'spopti.js'), 'utf8');
const optSrc = spopti.slice(spopti.indexOf('class Optimize {'), spopti.indexOf('class PageHelper {'));
const octx = vm.createContext({ console, Math, Number, Object, Array, skillInfo, MID_POINT: MID,
  document: { querySelector: () => ({ getAttribute: () => 'false' }) } });
vm.runInContext(optSrc + '\nglobalThis.Optimize = Optimize;', octx);

const levels = octx.Optimize.optTree(effArray(), cfg.currLevels.map(() => []), cfg.SP);

const ids = Object.keys(skillInfo);
let used = 0, byBranch = {};
levels.forEach((l, i) => {
  const lv = l[0], s = skillInfo[ids[i]];
  if (!lv) return;
  used += cumSP[ids[i]][lv];
  (byBranch[s.Branch] = byBranch[s.Branch] || []).push(`${s.Name} ${lv}/${s.MaxLevel} (${cumSP[ids[i]][lv]}sp)`);
});
console.log(`config: ${cfg.typeDamage} / ${cfg.typeGold} gw=${cfg.goldWeight}, budget ${cfg.SP} SP`);
for (const b in byBranch) console.log(`\n${b}\n  ` + byBranch[b].join('\n  '));
console.log(`\nTOTAL SP USED: ${used} / ${cfg.SP}`);

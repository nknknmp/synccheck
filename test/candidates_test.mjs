// -*- coding: utf-8 -*-
/**
 * 全域探索の「候補を複数返す」ことと、候補の選び直しの検算
 *
 *     node test/candidates_test.mjs
 *
 * ■ 何を守りたいか
 *
 * 繰り返し音のある素材では、周期のぶんずれた位置にも高い山ができる。
 * 最良の1候補だけを検算していた頃、実技3のペアが約2秒ずれて確定した。
 * findOffsetFullRange が離れた山を候補として複数返し、
 * 呼び出し側（src/lineup.js）が候補ごとに verifyOverlap で検算して
 * 選び直せることが前提なので、その土台をここで確かめる。
 *
 * - 候補が複数返ること（間隔 1.5秒以上で別々の山）
 * - 候補がスコア順で、先頭が従来の offsetSec と一致すること
 * - 周期音を混ぜた合成音でも、正しい位置が候補に含まれ、
 *   検算の一致で選び直せること
 */

import { findOffsetFullRange, verifyOverlap } from '../src/sync.js';

let failed = 0;
const ok = (cond, label, extra = '') => {
  if (cond) console.log(`  ok   ${label}${extra ? ' ' + extra : ''}`);
  else { failed++; console.log(`  FAIL ${label}${extra ? ' ' + extra : ''}`); }
};

// 決定的な疑似乱数（毎回同じ素材にする）
let seed = 42;
const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

const RATE = 100, LEN = 300 * RATE, SHIFT = 607;   // b は a に対して 6.07秒
const a = new Float32Array(LEN), b = new Float32Array(LEN);
const burst = (env, at, amp, dec) => {
  for (let i = 0; i < dec && at + i < env.length; i++) {
    env[at + i] += amp * Math.exp(-i / (dec / 3));
  }
};
// 周期音: 2.0秒ごとの打音
for (let t = 0; t < LEN; t += 200) {
  burst(a, t, 1.6, 30);
  if (t + SHIFT < LEN) burst(b, t + SHIFT, 1.6, 30);
}
// 固有の音: まばらなイベント
for (let n = 0; n < 45; n++) {
  const t = 300 + Math.floor(rnd() * (LEN - SHIFT - 900));
  const amp = 0.7 + rnd() * 0.7, dec = 15 + Math.floor(rnd() * 30);
  burst(a, t, amp, dec);
  burst(b, t + SHIFT, amp, dec);
}
for (let i = 0; i < LEN; i++) { a[i] += rnd() * 0.05; b[i] += rnd() * 0.05; }

console.log('\n=== 候補が複数返ること ===');
const rough = findOffsetFullRange(a, b, RATE);
ok(Array.isArray(rough.candidates) && rough.candidates.length >= 2,
   `候補が2つ以上 (実際 ${rough.candidates?.length})`);
ok(Math.abs(rough.candidates[0].offsetSec - rough.offsetSec) < 1e-9,
   '先頭の候補が offsetSec と一致する');
const secs = rough.candidates.map((c) => c.offsetSec);
ok(secs.every((s, i) => secs.every((t, j) => i === j || Math.abs(s - t) >= 1.5)),
   '候補どうしが1.5秒以上離れている');
const scores = rough.candidates.map((c) => c.score);
ok(scores.every((s, i) => i === 0 || scores[i - 1] >= s),
   '候補がスコア順になっている');

console.log('\n=== 検算で選び直せること ===');
// 符号の向きは crossCorrelate の定義に従う（ここでは絶対値で見る）
ok(Math.abs(Math.abs(rough.offsetSec) - 6.07) < 0.05,
   `正しい位置が最良候補に出る (実際 ${rough.offsetSec.toFixed(2)})`);

const verified = [];
for (const c of rough.candidates) {
  const v = verifyOverlap(a, b, RATE, Math.round(c.offsetSec * RATE));
  if (v.confident) verified.push({ offsetSec: c.offsetSec + v.medianSec, v });
}
ok(verified.length >= 1, '検算を通る候補がある');
verified.sort((x, y) =>
  (y.v.agree / Math.max(1, y.v.windows) - x.v.agree / Math.max(1, x.v.windows))
  || (y.v.meanScore - x.v.meanScore));
ok(verified.length > 0 && Math.abs(Math.abs(verified[0].offsetSec) - 6.07) < 0.05,
   `選び直した答えが正しい位置 (実際 ${verified[0]?.offsetSec.toFixed(2)})`);

console.log('\n────────────────────────────');
console.log(failed === 0 ? ' すべて通った' : ` 失敗: ${failed}`);
process.exit(failed === 0 ? 0 : 1);

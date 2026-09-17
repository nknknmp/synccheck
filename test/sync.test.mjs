/*
 * 同期計算の検算
 *
 * 実素材が無くても確かめられることだけをやる。
 * 答えが分かっている合成波形を入れて、出てきた値が合うか見る。
 *
 *   node test/sync.test.mjs
 *
 * ここが通っても「実素材で正しい」ことにはならない。
 * 符号と多数決のふるまいを固定しておくためのもの。
 */

import { buildEnvelope, crossCorrelate, verifySync, findOffsetFullRange }
  from '../src/sync.js';
import { resolveRecordingTimes, buildTimeline, findOverlappingPairs, findOrphans }
  from '../src/timeline.js';

let pass = 0, fail = 0;

function ok(cond, label, extra = '') {
  if (cond) { pass++; console.log(`  ok   ${label}`); }
  else { fail++; console.log(`  FAIL ${label}  ${extra}`); }
}

function near(actual, expected, tol, label) {
  const d = Math.abs(actual - expected);
  ok(d <= tol, `${label}  (期待 ${expected} / 実際 ${actual.toFixed(3)})`,
     `差 ${d.toFixed(3)} > 許容 ${tol}`);
}

/**
 * セミナーっぽい音量の線を作る。
 * 一定のしゃべりの中に、たまに大きな音（笑い・拍手）が入る形。
 * 乱数は固定種で作る。毎回同じ結果にしないと検算にならない。
 */
function makeEnvelope(lenSec, envRate, seed = 1) {
  let s = seed;
  const rnd = () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
  const n = Math.floor(lenSec * envRate);
  const env = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / envRate;
    // しゃべりのゆらぎ
    let v = 0.25 + 0.08 * Math.sin(t * 1.7) + 0.05 * rnd();
    // ときどき入る大きな音。位置は素材固有の目印になる
    if (Math.floor(t) % 37 === 0 && t % 1 < 0.4) v += 0.6;
    if (Math.floor(t) % 53 === 0 && t % 1 < 0.3) v += 0.45;
    env[i] = v;
  }
  return env;
}

/** env を delaySec だけ遅らせた線を作る（頭に無音を足す） */
function delayEnvelope(env, envRate, delaySec) {
  const shift = Math.round(delaySec * envRate);
  const out = new Float32Array(env.length);
  for (let i = 0; i < out.length; i++) {
    const src = i - shift;
    out[i] = src >= 0 && src < env.length ? env[src] : 0.02;
  }
  return out;
}

const ENV_RATE = 100;

console.log('\n=== buildEnvelope ===');
{
  // 振幅 0.5 の一定音を 8kHz で作ると、RMS も 0.5 になるはず
  const sr = 8000;
  const pcm = new Float32Array(sr * 2).fill(0.5);
  const env = buildEnvelope(pcm, sr, ENV_RATE);
  ok(env.length === 200, `長さが 2秒×100Hz = 200 になる (実際 ${env.length})`);
  near(env[50], 0.5, 0.001, '一定音の RMS が振幅と一致する');
}

console.log('\n=== crossCorrelate の符号 ===');
{
  // b を +3.13秒 遅らせた。crossCorrelate は「b の遅れ」を返す定義なので +3.13。
  // 移植元で符号を間違えた箇所。ここが逆になったら気付けるようにしておく。
  const a = makeEnvelope(180, ENV_RATE, 7);
  const b = delayEnvelope(a, ENV_RATE, 3.13);
  const r = crossCorrelate(a, b, ENV_RATE, 15);
  near(r.offsetSec, 3.13, 0.02, 'b を遅らせたら正の値が返る');
}
{
  // 逆向き。b のほうが先に始まっている場合は負。
  const a = makeEnvelope(180, ENV_RATE, 11);
  const b = delayEnvelope(a, ENV_RATE, -2.5);
  const r = crossCorrelate(a, b, ENV_RATE, 15);
  near(r.offsetSec, -2.5, 0.02, 'b が先なら負の値が返る');
}
{
  // 測定点を変えても同じ答えになること。
  // 符号が逆だと、ここで答えが2倍の速さで動く（移植元の教訓）。
  const a = makeEnvelope(300, ENV_RATE, 13);
  const b = delayEnvelope(a, ENV_RATE, 4.0);
  const r1 = crossCorrelate(a.subarray(0, 100 * ENV_RATE),
                            b.subarray(0, 100 * ENV_RATE), ENV_RATE, 15);
  const r2 = crossCorrelate(a.subarray(120 * ENV_RATE, 220 * ENV_RATE),
                            b.subarray(120 * ENV_RATE, 220 * ENV_RATE), ENV_RATE, 15);
  near(r1.offsetSec, 4.0, 0.02, '前半で測っても 4.0');
  near(r2.offsetSec, 4.0, 0.02, '後半で測っても 4.0（測定点に依存しない）');
}

console.log('\n=== verifySync ===');
{
  const a = makeEnvelope(600, ENV_RATE, 17);
  const b = delayEnvelope(a, ENV_RATE, 1.75);
  const r = verifySync(a, b, ENV_RATE, 5, 15);
  near(r.offsetSec, 1.75, 0.05, '5窓の多数決で 1.75 が出る');
  ok(r.drift === false, 'ずれが一定なら drift=false');
  ok(r.lowConfidence === false, '合意できているので lowConfidence=false');
  ok(r.points.length === 5, `窓が5つ測れている (実際 ${r.points.length})`);
}
{
  // 短い素材は窓に割れないので、全体で1回測る（singleWindow）
  const a = makeEnvelope(40, ENV_RATE, 19);
  const b = delayEnvelope(a, ENV_RATE, 0.8);
  const r = verifySync(a, b, ENV_RATE, 5, 15);
  ok(r.singleWindow === true, '30秒に割れない素材は singleWindow で返る');
  near(r.offsetSec, 0.8, 0.05, '短くても値は出る');
}

console.log('\n=== findOffsetFullRange（撮影時刻が無いとき） ===');
{
  // 長い A の 250秒目から B が始まる。手がかり無しで見つけられるか。
  const full = makeEnvelope(600, ENV_RATE, 23);
  const at = 250;
  const b = full.subarray(at * ENV_RATE, (at + 120) * ENV_RATE);
  const r = findOffsetFullRange(full, b, ENV_RATE, 5);
  near(r.offsetSec, at, 1.0, '全域探索で 250秒目を見つける');
  ok(r.confident === true, `見つけたと判定する (margin ${r.margin.toFixed(3)})`);
}

console.log('\n=== resolveRecordingTimes ===');
{
  // 更新日時＝録画終了、埋め込み＝録画開始 が成り立つ素材は「確定」する
  const t0 = 1_700_000_000_000;
  const a = [{ name: 'A1.mp4', duration: 600, creationMs: t0, lastModified: t0 + 600_000 }];
  const b = [{ name: 'B1.mp4', duration: 600, creationMs: t0 + 3000, lastModified: t0 + 603_000 }];
  const r = resolveRecordingTimes(a, b);
  ok(r.groupA[0].startMs === t0, '確定した素材は埋め込みをそのまま開始にする');
  ok(r.groupB[0].startMs === t0 + 3000, 'B側も同様');
}
{
  // 埋め込みが無い素材。更新日時から「重なりが増えるほう」を選ぶ
  const t0 = 1_700_000_000_000;
  const a = [{ name: 'A1.mp4', duration: 600, lastModified: t0 + 600_000 }];
  const b = [{ name: 'B1.mp4', duration: 600, lastModified: t0 + 600_000 }];
  const r = resolveRecordingTimes(a, b);
  const overlap = Math.min(r.groupA[0].startMs + 600_000, r.groupB[0].startMs + 600_000)
                - Math.max(r.groupA[0].startMs, r.groupB[0].startMs);
  ok(overlap > 0, `埋め込み無しでも重なる置き方を選ぶ (重なり ${overlap / 1000}秒)`);
}

console.log('\n=== findOverlappingPairs（途中で切れて再開する構成） ===');
{
  // 2カメが同じ時間帯を3回に分けて録った形。
  // 各回でズレ方が違う、という状況を組ごとに測れるかの土台。
  const t0 = 1_700_000_000_000;
  const mk = (name, startMs, dur) =>
    ({ name, duration: dur, creationMs: startMs, lastModified: startMs + dur * 1000 });

  const A = [
    mk('A1.mp4', t0, 600),                    //   0〜600
    mk('A2.mp4', t0 + 610_000, 600),          // 610〜1210
    mk('A3.mp4', t0 + 1_230_000, 600),        //1230〜1830
  ];
  const B = [
    mk('B1.mp4', t0 + 2_000, 600),            //   2〜602
    mk('B2.mp4', t0 + 615_000, 600),          // 615〜1215
    mk('B3.mp4', t0 + 1_233_000, 600),        //1233〜1833
  ];

  const tl = buildTimeline(A, B);
  const pairs = findOverlappingPairs(tl);
  ok(pairs.length === 3, `3組が見つかる (実際 ${pairs.length})`);

  const names = pairs.map((p) => `${p.a.name}-${p.b.name}`).sort();
  ok(names.join(',') === 'A1.mp4-B1.mp4,A2.mp4-B2.mp4,A3.mp4-B3.mp4',
     `正しい組み合わせになる (${names.join(',')})`);

  const p1 = pairs.find((p) => p.a.name === 'A1.mp4');
  near(p1.overlapSec, 598, 1, '1組目の重なりは約598秒');
  near(p1.aOffsetSec, 2, 0.5, 'A1 の2秒目から重なる');
  near(p1.bOffsetSec, 0, 0.5, 'B1 は先頭から重なる');

  ok(findOrphans(tl, pairs).length === 0, '取り残されるファイルは無い');
}
{
  // 片方だけ切れた場合。B が1本で通し録りだと A2 も A3 も B1 と重なる。
  const t0 = 1_700_000_000_000;
  const mk = (name, startMs, dur) =>
    ({ name, duration: dur, creationMs: startMs, lastModified: startMs + dur * 1000 });

  const A = [mk('A1.mp4', t0, 600), mk('A2.mp4', t0 + 610_000, 600)];
  const B = [mk('B1.mp4', t0 + 1_000, 1300)];

  const pairs = findOverlappingPairs(buildTimeline(A, B));
  ok(pairs.length === 2, `通し録り1本には2組できる (実際 ${pairs.length})`);
  ok(pairs[0].overlapSec >= pairs[1].overlapSec, '重なりが長い組が先に来る');
}
{
  // 重なりが短すぎる組は測らない
  const t0 = 1_700_000_000_000;
  const mk = (name, startMs, dur) =>
    ({ name, duration: dur, creationMs: startMs, lastModified: startMs + dur * 1000 });
  const A = [mk('A1.mp4', t0, 600)];
  const B = [mk('B1.mp4', t0 + 595_000, 600)];   // 5秒しか重ならない
  const pairs = findOverlappingPairs(buildTimeline(A, B));
  ok(pairs.length === 0, `重なり5秒の組は捨てる (実際 ${pairs.length})`);
}

console.log(`\n────────────────────────────`);
console.log(` 通った: ${pass} / 失敗: ${fail}`);
console.log(`────────────────────────────\n`);
process.exit(fail === 0 ? 0 : 1);

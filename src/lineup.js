/**
 * 放り込んだ動画を、1本の共通タイムラインに並べる
 *
 * ■ このアプリの本題
 *
 * 欲しいのは「編集ソフトのタイムラインで、どのクリップをどこに置くか」。
 * いちばん早く始まった1本を 00:00:00:00 とし、残りをそこからの
 * 位置で出す。2本でも6本でも同じ形で並ぶ。
 *
 * ■ 1カメしかないシーンが混ざる
 *
 * すべてのクリップにペアがあるとは限らない。2カメで撮った場面もあれば、
 * 1カメだけの場面もある。**重ならないクリップがあるのは正常**なので、
 * それを異常として扱わない。
 *
 * ■ 位置の決め方（撮影時刻は当てにしない）
 *
 * 撮影時刻はファイルごとに意味が違う。実素材では
 * iPad(mov)=録画開始 / Android(mp4)=録画終了 を記録していた。
 * さらに秒単位までしか無く、端末の時計自体も数秒ずれる。
 * 編集に要る精度は1フレーム(0.033秒)なので、原理的に届かない。
 *
 * そこで **音で重なりを確かめてから位置を決める**。
 * 撮影時刻は「どのあたりを探すか」の当たりにだけ使う。
 *
 * ■ 重なっているかの判定（ここが肝）
 *
 * 相関スコアの大小では線を引けない。実素材で総当たりしたところ、
 * 重なっていない組でも 0.23 は出て、重なっている組が 0.33 のことも
 * あった。決め手は「その位置で窓ごとに測り直して、どの窓も同じ答えに
 * なるか」。sync.js の verifyOverlap がそれをやる。
 */

import { extractSyncPCM, SYNC_RATE, ENV_RATE } from './audio.js';
import { buildEnvelope, findOffsetFullRange, verifyOverlap } from './sync.js';

/**
 * 重なりを探すのに使う音声の長さ。
 *
 * ■ 全長を読む
 *
 * 途中で切ると、そこから先で重なっている組を見つけられない。
 * 実素材で k1.mov(847秒) と k2.mp4 の重なりは **418秒目から**
 * 始まっており、600秒で切ると照合はできても、切り詰めた側の
 * 波形が足りずに窓の検算が通らなかった（2026-09-19）。
 *
 * 音声だけ・8kHz モノラルなので、1時間でも 28MB ほど。
 * 映像は1フレームも読まない（-vn）ので、長さより本数が効く。
 */
const SCAN_LEN_SEC = Infinity;

/** これ未満しか重ならない組は測らない */
export const MIN_OVERLAP_SEC = 20;

/**
 * 撮影時刻から、各ファイルのだいたいの開始位置を秒で見積もる。
 *
 * ■ これは「当たり」であって答えではない
 *
 * 撮影時刻から位置を決めてはいけない。理由は3つあり、すべて実測済み:
 *
 *   1. **録画開始か終了かがファイルごとに違う**
 *      iPad(mov)  = 録画開始を記録（com.apple.quicktime.model=iPad）
 *      Android(mp4) = 録画終了を記録（com.android.version=13）
 *      実素材 916まとめ では差が 11分1秒 ＝ ほぼ動画の長さぶん出た。
 *
 *   2. **秒単位までしか記録されない**（ミリ秒は全部ゼロ）
 *
 *   3. **端末の時計自体が数秒ずれる**
 *
 *   端末で決め打って解釈しても、音で測った答えとの差は
 *   5.2秒（156フレーム）あった。編集に要る精度は1フレーム＝0.033秒
 *   なので、撮影時刻では原理的に届かない。
 *
 * ■ 出典（これを消さないこと）
 *
 * この判断は SemiCut で実ファイル4本を ffprobe して確定させたもの。
 * 送り方（USB / Quick Share / LocalSend）による更新日時の違いも含めて
 *
 *     C:\dev\toolbox\SemiCut\引継ぎノート.md
 *     「素材の実測値（もう一度 ffprobe しなくていいように）」
 *
 * に表がある。2026-09-19 に端末の判別方法を追記した。
 *
 * **SemiCut から移植したとき、コードだけ来て この説明が来なかったため、
 * 同じ調査を2回やる羽目になった。** 作り替えるときは必ず持っていくこと。
 *
 * ■ ここでやること
 *
 * 端末を決め打ちせず、撮影時刻をそのまま並べるだけ。
 * 実際の位置は lineUp() が音で決める（総当たり＋窓の検算）ので、
 * ここが多少ずれていても最終結果は合う。
 */
export function guessStarts(files) {
  const withTime = files.filter((f) => f.creationMs);
  if (withTime.length === 0) return files.map(() => 0);
  const base = Math.min(...withTime.map((f) => f.creationMs));
  return files.map((f) => (f.creationMs ? (f.creationMs - base) / 1000 : 0));
}

/**
 * 全ファイルを1本の軸に並べる。
 *
 * @param {Array} files  {name, file, duration, creationMs} の配列
 * @param {(p:object)=>void} onProgress
 * @returns {{items:Array, notes:Array}}
 */
export async function lineUp(files, onProgress = () => {}, maxLenSec = 180,
                             fps = 30) {
  // 隣接させる計算はフレーム単位で行う（下の「フレーム単位で隣接」参照）。
  // 秒のまま足すと、端数の丸めで1〜2フレームずれる。
  if (files.length === 0) return { items: [], notes: [] };

  const notes = [];
  const guess = guessStarts(files);

  // 撮影時刻の順に並べる（当たりとして使うだけ）
  const order = files
    .map((f, i) => ({ f, guessStart: guess[i], dur: f.duration || 0 }))
    .sort((x, y) => x.guessStart - y.guessStart);

  if (order.length === 1) {
    return {
      items: [{
        name: order[0].f.name, file: order[0].f.file,
        startSec: 0, duration: order[0].dur,
        measured: false, isBase: true, score: null, warn: null,
      }],
      notes: ['1本しかないので測っていません'],
    };
  }

  // ■ 1. 各ファイルの音を1回だけ読む
  //
  // 総当たりで測るので、毎回抜き直すと本数の2乗で時間がかかる。
  // 先に全部の波形を作っておく。
  const envs = [];
  for (let i = 0; i < order.length; i++) {
    const o = order[i];
    onProgress({ done: i, total: order.length * 2,
                 message: `${o.f.name} の音を読んでいます` });
    try {
      const len = Math.min(SCAN_LEN_SEC, o.dur);   // 実質は全長
      const pcm = await extractSyncPCM(o.f.file, 0, len);
      envs.push(pcm.length ? buildEnvelope(pcm, SYNC_RATE, ENV_RATE) : null);
    } catch (err) {
      envs.push(null);
      notes.push(`${o.f.name}: 音を読めませんでした（${err.message}）`);
    }
  }

  // ■ 2. 総当たりで「本当に重なっている組」を探す
  //
  // 撮影時刻を信じないので全部の組を見る。6本なら15組だが、
  // 波形はもう手元にあるので計算だけ。音を読み直すことはない。
  const links = [];
  let step = 0;
  const pairCount = order.length * (order.length - 1) / 2;
  for (let i = 0; i < order.length; i++) {
    for (let j = i + 1; j < order.length; j++) {
      step++;
      onProgress({ done: order.length + (step / pairCount) * order.length,
                   total: order.length * 2,
                   message: `${order[i].f.name} と ${order[j].f.name} を照合中` });
      const a = envs[i], b = envs[j];
      if (!a || !b) continue;

      // 全域から候補を探し、その位置で窓ごとに検算する
      const rough = findOffsetFullRange(a, b, ENV_RATE);
      const lagFrames = Math.round(rough.offsetSec * ENV_RATE);
      const v = verifyOverlap(a, b, ENV_RATE, lagFrames);
      if (!v.confident) continue;

      const offsetSec = rough.offsetSec + v.medianSec;
      const overlap = Math.min(order[i].dur, offsetSec + order[j].dur)
                    - Math.max(0, offsetSec);
      if (overlap < MIN_OVERLAP_SEC) continue;

      links.push({ i, j, offsetSec, overlap, score: v.meanScore,
                   windows: v.windows, agree: v.agree });
    }
  }

  // ■ 3. 確かな組から順につないで位置を決める
  //
  // 重なりが長い組ほど答えが安定するので、そこから確定させる。
  //
  // ■ 島がいくつもできる
  //
  // 1カメしかない場面が混ざるので、全部が1つにつながるとは限らない。
  // 実素材では「実技1のグループ」と「実技3のグループ」が別々の島に
  // なった。島ごとに起点を作り、あとで時間順に並べる。
  // （2026-09-19: ここで2つ目の島を捨てていて、実技3のペアが
  //   「重ならない」と出ていた）
  links.sort((x, y) => y.overlap - x.overlap);

  const pos = new Array(order.length).fill(null);
  const detail = new Array(order.length).fill(null);
  const island = new Array(order.length).fill(-1);   // どの島に属すか
  let islandCount = 0;

  for (const L of links) {
    const hasI = pos[L.i] != null, hasJ = pos[L.j] != null;

    if (!hasI && !hasJ) {
      // 新しい島の起点。島の中では 0 から始める（あとで足しこむ）。
      pos[L.i] = 0;
      island[L.i] = islandCount++;
      pos[L.j] = L.offsetSec;
      island[L.j] = island[L.i];
      detail[L.j] = { against: order[L.i].f.name, offsetSec: L.offsetSec,
                      overlapSec: L.overlap, score: L.score,
                      windows: L.windows, agree: L.agree };
      continue;
    }

    if (hasI && hasJ) {
      // 両方とも確定済み。別々の島なら、この組でつなげる。
      if (island[L.i] !== island[L.j]) {
        const from = island[L.j], to = island[L.i];
        const shift = (pos[L.i] + L.offsetSec) - pos[L.j];
        for (let k = 0; k < order.length; k++) {
          if (island[k] === from) { pos[k] += shift; island[k] = to; }
        }
      }
      continue;
    }

    if (hasI) {
      pos[L.j] = pos[L.i] + L.offsetSec;
      island[L.j] = island[L.i];
      detail[L.j] = { against: order[L.i].f.name, offsetSec: L.offsetSec,
                      overlapSec: L.overlap, score: L.score,
                      windows: L.windows, agree: L.agree };
    } else {
      pos[L.i] = pos[L.j] - L.offsetSec;
      island[L.i] = island[L.j];
      detail[L.i] = { against: order[L.j].f.name, offsetSec: -L.offsetSec,
                      overlapSec: L.overlap, score: L.score,
                      windows: L.windows, agree: L.agree };
    }
  }

  // ■ 島どうしを時間順に並べる
  //
  // 島の中の位置は音で確かめてあるが、島と島の前後は分からない。
  // 撮影時刻の順（order の順）で、重ならないよう後ろへ積む。
  // ■ 島どうしは隙間なく隣接させる
  //
  // 前の島が終わった**次の1フレーム**から次の島を始める。
  // 編集ソフトでそのまま繋げて並べられるようにするため。
  // （2026-09-19 まで2秒の隙間を空けていた。根拠のない値で、
  //   編集時に手で詰める手間になるだけだった）
  const islandIds = [...new Set(island.filter((v) => v >= 0))];
  if (islandIds.length > 1) {
    // 各島の代表（order の中でいちばん前にあるもの）で順番を決める
    const firstIdx = new Map();
    for (let k = 0; k < order.length; k++) {
      if (island[k] >= 0 && !firstIdx.has(island[k])) firstIdx.set(island[k], k);
    }
    const sortedIslands = [...firstIdx.entries()]
      .sort((a, b) => a[1] - b[1]).map(([id]) => id);

    // ■ フレーム単位で隣接させる
    //
    // 前の島が終わった**次のフレーム**から次の島を始める。
    // 編集ソフトでそのまま繋げて並べられるようにするため。
    //
    // フレーム番号は 0 から始まるので、長さ N フレームのクリップは
    // 0 〜 N-1 を占め、**次のクリップの先頭は N**。+1 は要らない。
    //
    //   次の開始 = 前の開始フレーム + floor(長さ * fps)
    //
    // 長さは端数を切り捨てる。切り上げや四捨五入だと、実際には
    // 存在しないフレームぶん先へ進んでしまう
    // （実素材 847.445秒 = 25423.35フレーム → 25423 が正しい）。
    //
    // 秒のまま足して最後にフレームへ直すと丸めで1〜2フレームずれるので、
    // 必ずフレーム単位で積む。
    const toF = (sec) => Math.round(sec * fps);
    const durF = (sec) => Math.floor(sec * fps);
    let baseFrame = 0;
    for (const id of sortedIslands) {
      const members = [];
      for (let k = 0; k < order.length; k++) if (island[k] === id) members.push(k);
      const lo = Math.min(...members.map((k) => pos[k]));
      // 島の中の相対位置は保ったまま、島の先頭を baseFrame に合わせる
      const shiftSec = baseFrame / fps - lo;
      for (const k of members) pos[k] += shiftSec;
      baseFrame = Math.max(...members.map(
        (k) => toF(pos[k]) + durF(order[k].dur)));
    }
    notes.push(
      `重なりの組が ${islandIds.length}つ に分かれています`
      + `（別々の場面を撮ったもの）。場面どうしの前後は撮影時刻の順です`);
  }

  // ■ 4. どの組にも入らなかったもの（1カメのシーンなど）
  //
  // 音で位置を決められないので、撮影時刻の順に後ろへ並べる。
  // 確定済みの最後尾より後ろに、重ならないよう間隔を空けて置く。
  // 撮影時刻のずれをそのまま持ち込むと大きく外れるため、
  // 「順番だけは合っている」状態にとどめる。
  // 単独のクリップも同じく、直前の終わりの次のフレームから。
  const toFrame = (sec) => Math.round(sec * fps);
  const durFrame = (sec) => Math.floor(sec * fps);
  let tailFrame = 0;
  for (let i = 0; i < order.length; i++) {
    if (pos[i] != null) {
      tailFrame = Math.max(tailFrame,
                           toFrame(pos[i]) + durFrame(order[i].dur));
    }
  }
  const lonely = [];
  for (let i = 0; i < order.length; i++) {
    if (pos[i] == null) lonely.push(i);
  }
  for (const i of lonely) {
    pos[i] = tailFrame / fps;
    tailFrame += durFrame(order[i].dur);
  }
  if (lonely.length) {
    notes.push(
      `${lonely.map((i) => order[i].f.name).join('、')} は`
      + `他と重なりませんでした（1カメだけの場面など）。`
      + `撮影時刻の順に後ろへ並べています`);
  }

  // ■ 5. いちばん早いものを 0 にそろえる
  const min = Math.min(...pos);
  const items = order.map((o, i) => ({
    name: o.f.name,
    file: o.f.file,
    startSec: pos[i] - min,
    duration: o.dur,
    measured: detail[i] != null,
    isBase: detail[i] == null && pos[i] - min === 0,
    alone: detail[i] == null && !(pos[i] - min === 0),
    score: detail[i] ? detail[i].score : null,
    warn: null,
    detail: detail[i],
  })).sort((a, b) => a.startSec - b.startSec);

  onProgress({ done: order.length * 2, total: order.length * 2,
               message: '並べ終わりました' });
  return { items, notes };
}

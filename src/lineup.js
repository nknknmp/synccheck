/**
 * 放り込んだ動画を、1本の共通タイムラインに並べる
 *
 * ■ このアプリの本題
 *
 * 欲しいのは「編集ソフトのタイムラインで、どのクリップをどこに置くか」。
 * いちばん早く始まった1本を 00:00:00:00 とし、残りをそこからの
 * 位置で出す。2本でも6本でも同じ形で並ぶ。
 *
 * ■ A側/B側という分け方はしない
 *
 * 以前は「基準のカメラ」と「合わせるカメラ」を分けて組にしていたが、
 * 4本・6本と増えると組の数だけ結果が出てしまい、
 * 「結局どこに置くのか」が読み取れなかった。
 *
 * ■ 位置の決め方
 *
 * 撮影時刻は当てにしない。ファイルごとに意味が違うため
 * （実素材で mov=録画開始 / mp4=録画終了 になっていて、
 *  そのまま信じると 5.2秒ずれた。timeline.js のコメント参照）。
 *
 * かわりに**音で測る**。撮影時刻は「どのあたりを探すか」の
 * 目安にだけ使う。音量やマイク位置が違っても答えは変わらない
 * （正規化するため。test/volume_test.py で実証している）。
 *
 * ■ つなぎ方
 *
 * 1本目を基準に、2本目以降を順に測って位置を確定していく。
 * 測る回数は「本数 - 1」で済む（総当たりはしない）。
 *
 * 直前に確定した1本と測るのではなく、**すでに確定した中で
 * いちばん重なりが長いもの**と測る。重なりが長いほど答えが安定し、
 * 誤差の積み上がりも減る。
 */

import { measurePair } from './measure.js';

/** 測定に必要な最低限の重なり（これ未満は測らない） */
export const MIN_OVERLAP_SEC = 10;

/**
 * 撮影時刻から、各ファイルのだいたいの開始位置を秒で見積もる。
 *
 * ここで出すのは「どのあたりを探すか」の当たりであって、
 * 答えではない。音で測って上書きする。
 *
 * 撮影時刻が読めないファイルは、名前順で後ろに積む
 * （重なっている前提で測りにいく）。
 */
export function guessStarts(files) {
  const withTime = files.filter((f) => f.creationMs);
  if (withTime.length === 0) {
    // 手がかりが無い。全部 0 から始まっていることにして音で測る。
    return files.map(() => 0);
  }
  const base = Math.min(...withTime.map((f) => f.creationMs));
  return files.map((f) => (f.creationMs ? (f.creationMs - base) / 1000 : 0));
}

/**
 * 2本の重なりを、それぞれのファイル内の位置として返す。
 *
 * @returns {{overlapSec, aOffsetSec, bOffsetSec}|null}
 */
function overlapOf(aStart, aDur, bStart, bDur) {
  const start = Math.max(aStart, bStart);
  const end = Math.min(aStart + aDur, bStart + bDur);
  const overlap = end - start;
  if (overlap <= 0) return null;
  return {
    overlapSec: overlap,
    aOffsetSec: start - aStart,
    bOffsetSec: start - bStart,
  };
}

/**
 * 全ファイルを1本の軸に並べる。
 *
 * @param {Array} files  {name, file, duration, creationMs} の配列
 * @param {(p:object)=>void} onProgress
 * @param {number} maxLenSec  1回の測定で使う音声の長さ
 * @returns {{items:Array, notes:Array}}
 *   items: {name, file, startSec, duration, measured, score, warn} の配列
 *          startSec はいちばん早いものを 0 とした秒
 */
export async function lineUp(files, onProgress = () => {}, maxLenSec = 180) {
  if (files.length === 0) return { items: [], notes: [] };

  const notes = [];
  const guess = guessStarts(files);

  // 推定開始が早い順に並べる。これが測る順番になる。
  const order = files
    .map((f, i) => ({ f, guessStart: guess[i], dur: f.duration || 0 }))
    .sort((x, y) => x.guessStart - y.guessStart);

  if (order.length === 1) {
    return {
      items: [{
        name: order[0].f.name, file: order[0].f.file,
        startSec: 0, duration: order[0].dur,
        measured: false, score: null, warn: null,
      }],
      notes: ['1本しかないので測っていません'],
    };
  }

  // 先頭を仮の基準にする（あとで最小値を引いて 0 起点に直す）
  const placed = [{
    name: order[0].f.name, file: order[0].f.file,
    startSec: 0, duration: order[0].dur,
    measured: false, score: null, warn: null,
    _ref: order[0],
  }];

  const total = order.length - 1;
  for (let i = 1; i < order.length; i++) {
    const cur = order[i];
    onProgress({ done: i - 1, total, message: `${cur.f.name} の位置を測っています` });

    // すでに置いたもののうち、いちばん重なりが長いものを相手に選ぶ。
    // 重なりが長いほど答えが安定する。
    let best = null;
    for (const p of placed) {
      const gap = cur.guessStart - p._ref.guessStart;   // 推定のズレ
      const ov = overlapOf(p.startSec, p.duration,
                           p.startSec + gap, cur.dur);
      if (!ov) continue;
      if (!best || ov.overlapSec > best.ov.overlapSec) best = { p, ov, gap };
    }

    if (!best || best.ov.overlapSec < MIN_OVERLAP_SEC) {
      // どれとも重なっていない。撮影時刻の見積もりだけで置く。
      const fallbackStart = placed[0].startSec
        + (cur.guessStart - placed[0]._ref.guessStart);
      placed.push({
        name: cur.f.name, file: cur.f.file,
        startSec: fallbackStart, duration: cur.dur,
        measured: false, score: null,
        warn: '他と重なっていないので撮影時刻のまま置いています',
        _ref: cur,
      });
      notes.push(`${cur.f.name} は他と重なりが足りず、音で測れませんでした`);
      continue;
    }

    // 音で測る。measurePair は「b の遅れ」を返す。
    const pair = {
      a: { ...best.p._ref.f, name: best.p.name, file: best.p.file },
      b: { ...cur.f },
      overlapSec: best.ov.overlapSec,
      aOffsetSec: best.ov.aOffsetSec,
      bOffsetSec: best.ov.bOffsetSec,
    };

    let r;
    try {
      r = await measurePair(pair, (m) => onProgress({ done: i - 1, total, message: m }),
                            maxLenSec);
    } catch (err) {
      r = { ok: false, reason: err.message };
    }

    if (!r.ok) {
      const fallbackStart = best.p.startSec + best.gap;
      placed.push({
        name: cur.f.name, file: cur.f.file,
        startSec: fallbackStart, duration: cur.dur,
        measured: false, score: null,
        warn: `測れなかったので撮影時刻のまま（${r.reason}）`,
        _ref: cur,
      });
      notes.push(`${cur.f.name}: ${r.reason}`);
      continue;
    }

    // このファイルの位置 = 相手の位置 + 推定のズレ + 音で測った補正
    //
    // best.gap は撮影時刻から見た推定のズレ。そこを起点に
    // aOffsetSec/bOffsetSec で切り出して測っているので、
    // measuredSec（音で測った差）を足せば正しい位置になる。
    // r.totalOffsetSec は timeGapSec を含む別の基準なので使わない。

    placed.push({
      name: cur.f.name, file: cur.f.file,
      startSec: best.p.startSec + best.gap + r.measuredSec,
      duration: cur.dur,
      measured: true,
      score: r.score,
      warn: r.lowConfidence
        ? '窓の過半数が一致しなかった。この位置は信用しないこと'
        : (r.drift ? '区間ごとにズレが変わっている' : null),
      _ref: cur,
    });

    if (r.lowConfidence) {
      notes.push(`${cur.f.name} は測定が安定しませんでした（スコア ${r.score.toFixed(3)}）`);
    }
  }

  // いちばん早いものを 0 にそろえる
  const min = Math.min(...placed.map((p) => p.startSec));
  const items = placed
    .map(({ _ref, ...p }) => ({ ...p, startSec: p.startSec - min }))
    .sort((a, b) => a.startSec - b.startSec);

  onProgress({ done: total, total, message: '並べ終わりました' });
  return { items, notes };
}

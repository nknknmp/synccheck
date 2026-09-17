/*
 * SyncCheck - 組ごとにズレを測る
 *
 * ■ 組ごとに測るのがこのアプリの主目的
 *
 * 2カメでも録画を止めて再開するので、A側3本 / B側3本のようになる。
 * **録画を止めて再開するとズレ方が変わる**（移植元の実測）。
 * だから1組目の値を他の組に当てはめてはいけない。
 * 「全部ずれている」という誤判定になる。
 */

import { buildEnvelope, verifySync, crossCorrelate, findOffsetFullRange } from './sync.js';
import { extractSyncPCM, SYNC_RATE, ENV_RATE } from './audio.js';

/** 1組で測る長さの上限。長すぎると遅いだけで精度は上がらない。 */
export const MEASURE_LEN_SEC = 180;

/** これ未満の重なりしかない組は、波形が一致しているか判断できない。 */
export const MIN_MEASURE_SEC = 10;

/**
 * 重なっている組をひとつ測る。
 *
 * @param {object} pair findOverlappingPairs が返した組
 * @param {(msg:string)=>void} onLog
 * @returns {object} 測定結果
 */
export async function measurePair(pair, onLog = () => {}, maxLenSec = MEASURE_LEN_SEC) {
  const { a, b, overlapSec, aOffsetSec, bOffsetSec } = pair;
  const label = `${a.name} ↔ ${b.name}`;

  const len = Math.min(maxLenSec, overlapSec);
  if (len < MIN_MEASURE_SEC) {
    return {
      pair, label, ok: false,
      reason: `重なりが ${overlapSec.toFixed(1)}秒 しかない（${MIN_MEASURE_SEC}秒 以上必要）`,
    };
  }

  onLog(`${label} … 音声を抜いています`);

  let pcmA, pcmB;
  try {
    // 必ず1本ずつ抜く。つないでから -ss するとずれる（audio.js のコメント）。
    pcmA = await extractSyncPCM(a.file, aOffsetSec, len);
    pcmB = await extractSyncPCM(b.file, bOffsetSec, len);
  } catch (err) {
    return { pair, label, ok: false, reason: `音声を抜けなかった: ${err.message}` };
  }

  if (pcmA.length === 0 || pcmB.length === 0) {
    return { pair, label, ok: false, reason: '音声が入っていない' };
  }

  const envA = buildEnvelope(pcmA, SYNC_RATE, ENV_RATE);
  const envB = buildEnvelope(pcmB, SYNC_RATE, ENV_RATE);

  onLog(`${label} … 波形を突き合わせています`);

  // ■ まず全体で1回測って、おおよそのズレを掴む
  //
  // 窓に分けて測ると、1窓の長さに対して探索幅が広すぎる場合に
  // 端の偶然一致を拾う（crossCorrelate のコメント参照）。
  // 全体で測れば重なりが長いので、大きなズレでも見つけられる。
  const rough = crossCorrelate(envA, envB, ENV_RATE, 30);

  // ■ 次に窓ごとに測って、ずれが一定かどうかを見る
  //
  // 探索幅は「おおよその答え ± 5秒」で足りる。
  // 窓に対して広すぎる探索幅を与えないことが大事。
  const windows = 3;
  const winSec = Math.floor(Math.min(envA.length, envB.length) / windows / ENV_RATE);
  // 窓の半分までしか lag を振れない（MIN_OVERLAP_RATIO = 0.5）
  const lagRoom = Math.max(1, Math.floor(winSec * 0.5) - 1);
  const wantLag = Math.abs(rough.offsetSec) + 5;
  const lagSec = Math.min(wantLag, lagRoom);

  const r = verifySync(envA, envB, ENV_RATE, windows, lagSec);

  // 窓の答えと全体の答えが食い違うなら、窓が短すぎて当てにならない。
  // 全体の答えを採り、信用できない印を付ける。
  const disagree = Math.abs(r.offsetSec - rough.offsetSec) > 0.5;
  if (disagree) {
    return {
      pair, label, ok: true,
      measuredSec: rough.offsetSec,
      timeGapSec: b.startSec - a.startSec,
      totalOffsetSec: (b.startSec - a.startSec) + rough.offsetSec,
      score: rough.score,
      drift: false,
      maxDeviationSec: Math.abs(r.offsetSec - rough.offsetSec),
      lowConfidence: true,
      singleWindow: true,
      points: r.points,
      measuredLenSec: len,
      note: `全体で測った値（${rough.offsetSec.toFixed(2)}秒）と`
          + `窓ごとの値（${r.offsetSec.toFixed(2)}秒）が食い違った。`
          + `窓が短いか、区間でズレが変わっている`,
    };
  }

  // 測定値は「重なりの中でのズレ」。撮影時刻から見た総ズレに直す。
  //   B の τ秒目 = A の (τ + totalOffsetSec) 秒目
  const timeGapSec = b.startSec - a.startSec;   // 撮影時刻から見た差
  const totalOffsetSec = timeGapSec + r.offsetSec;

  return {
    pair, label, ok: true,
    measuredSec: r.offsetSec,        // 重なり区間で測ったズレ
    timeGapSec,                      // 撮影時刻から見た差
    totalOffsetSec,                  // 実際に合わせるべきズレ
    score: r.score,
    drift: r.drift,
    maxDeviationSec: r.maxDeviationSec,
    lowConfidence: r.lowConfidence,
    singleWindow: r.singleWindow === true,
    points: r.points,
    measuredLenSec: len,
  };
}

/**
 * 全部の組を順に測る。
 *
 * 組ごとに独立して測る。前の組の結果は使わない。
 */
export async function measureAll(pairs, onProgress = () => {},
                                 maxLenSec = MEASURE_LEN_SEC) {
  const results = [];

  for (let i = 0; i < pairs.length; i++) {
    onProgress({
      done: i, total: pairs.length,
      message: `${i + 1}/${pairs.length} 組目を測っています`,
    });
    results.push(await measurePair(pairs[i], (msg) =>
      onProgress({ done: i, total: pairs.length, message: msg }),
      maxLenSec
    ));
  }

  onProgress({ done: pairs.length, total: pairs.length, message: '測り終わりました' });
  return results;
}

/**
 * 撮影時刻が当てにならない組を、音だけで探し直す。
 *
 * 撮影時刻が壊れていると重なる組が見つからない。
 * そのときは全域探索で「B が A のどこにあるか」を音だけで探す。
 * 重いので、ユーザーが明示的に選んだときだけ動かす。
 */
export async function searchBlind(fileA, fileB, onLog = () => {}) {
  onLog(`${fileA.name} の全体から ${fileB.name} を探しています（時間がかかります）`);

  // A は全体、B は先頭の3分だけで足りる
  const pcmA = await extractSyncPCM(fileA.file, 0, null);
  const pcmB = await extractSyncPCM(fileB.file, 0, Math.min(180, fileB.duration || 180));

  const envA = buildEnvelope(pcmA, SYNC_RATE, ENV_RATE);
  const envB = buildEnvelope(pcmB, SYNC_RATE, ENV_RATE);

  const r = findOffsetFullRange(envA, envB, ENV_RATE, 5);

  return {
    aName: fileA.name,
    bName: fileB.name,
    // 「A の何秒目に B の先頭が来るか」
    positionSec: r.offsetSec,
    score: r.score,
    confident: r.confident,
    margin: r.margin,
  };
}

/**
 * 結果のまとめ。画面に出す文と、注意すべき点を作る。
 */
export function summarize(results) {
  const ok = results.filter((r) => r.ok);
  const failed = results.filter((r) => !r.ok);
  const drifting = ok.filter((r) => r.drift);
  const lowConf = ok.filter((r) => r.lowConfidence);

  const warnings = [];

  if (failed.length > 0) {
    warnings.push(`${failed.length}組 測れなかった`);
  }
  if (lowConf.length > 0) {
    warnings.push(
      `${lowConf.length}組 で窓の過半数が一致しなかった。値を信用しないこと`
    );
  }
  if (drifting.length > 0) {
    warnings.push(
      `${drifting.length}組 で区間ごとにズレが変わっている（録画の中断など）`
    );
  }

  // 組ごとにズレが違うのは想定どおりだが、気付けるように出しておく
  if (ok.length >= 2) {
    const vals = ok.map((r) => r.totalOffsetSec);
    const spread = Math.max(...vals) - Math.min(...vals);
    if (spread > 1.0) {
      warnings.push(
        `組ごとにズレが最大 ${spread.toFixed(2)}秒 違う。` +
        `1つの値で全体を合わせることはできない`
      );
    }
  }

  return { total: results.length, ok: ok.length, failed: failed.length, warnings };
}

/*
 * SyncCheck - 同期の計算
 *
 * SemiCut の src/core.js から、同期に必要な部分だけを移植した。
 * 移植元の実測にもとづく判断（符号の導出、多数決、更新日時の扱い）は
 * コメントごと持ってきている。消さないこと。理由は 使い方.txt に書いた。
 *
 * このファイルは映像を一切見ない。音量の線（エンベロープ）だけを扱う。
 */

// ---------------------------------------------------------------------------
// 波形の下ごしらえ
// ---------------------------------------------------------------------------

/**
 * 相互相関用のエンベロープ（音量の包絡線）を作る。
 * 生波形のままだと位相ズレに弱いので、区間ごとのRMSに落とす。
 */
export function buildEnvelope(pcm, sampleRate, envRate = 100) {
  const win = Math.max(1, Math.floor(sampleRate / envRate));
  const n = Math.floor(pcm.length / win);
  const env = new Float32Array(n);

  for (let i = 0; i < n; i++) {
    let sum = 0;
    const base = i * win;
    for (let j = 0; j < win; j++) {
      const v = pcm[base + j];
      sum += v * v;
    }
    env[i] = Math.sqrt(sum / win);
  }
  return env;
}

/** 平均0・標準偏差1にそろえる。音量の大小を無視して形だけ比べるため。 */
function normalize(arr) {
  const n = arr.length;
  if (n === 0) return new Float32Array(0);

  let mean = 0;
  for (let i = 0; i < n; i++) mean += arr[i];
  mean /= n;

  let variance = 0;
  for (let i = 0; i < n; i++) {
    const d = arr[i] - mean;
    variance += d * d;
  }
  const sd = Math.sqrt(variance / n) || 1e-9;

  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = (arr[i] - mean) / sd;
  return out;
}

/** エンベロープを間引く（粗い全域探索用） */
export function downsampleEnvelope(env, factor) {
  const f = Math.max(1, Math.floor(factor));
  if (f === 1) return env;
  const n = Math.floor(env.length / f);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let s = 0;
    for (let j = 0; j < f; j++) s += env[i * f + j];
    out[i] = s / f;
  }
  return out;
}

// ---------------------------------------------------------------------------
// 相互相関
// ---------------------------------------------------------------------------

/**
 * 相関を取るとき、窓のうち最低これだけの割合は重なっていること。
 *
 * 0.5 なら「半分以上重なる lag だけ見る」。
 * 下げると広い範囲を探せるが、端の偶然一致を拾いやすくなる。
 */
export const MIN_OVERLAP_RATIO = 0.5;

/**
 * 2つの音声エンベロープ間のオフセットを相互相関で求める。
 *
 * 戻り値は「b が a より何秒遅れているか」。
 * 正なら b のほうが後、負なら b のほうが先に始まっている。
 *
 * ■ 符号は紙の上で決めないこと（移植元で1度間違えて、正しい部品まで疑った）
 *
 *   crossCorrelate(a, b) は a[i] と b[i+lag] を突き合わせる。
 *   a = 横（LS秒目から）、b = 縦（PS秒目から）なら
 *     横(LS + i) = 縦(PS + i + lag)
 *   「縦のτ = 横のτ+D」と定義するなら
 *     LS = PS + lag + D   ⇒   D = LS - PS - lag
 *
 *   符号が逆だと、測定点をずらしたとき答えが2倍の速さで動く。
 *   疑ったら測定点を変えて同じ答えになるか確かめること。
 */
export function crossCorrelate(a, b, sampleRate, maxLagSec = 30,
                               minOverlapRatio = MIN_OVERLAP_RATIO) {
  const maxLag = Math.min(Math.floor(maxLagSec * sampleRate), Math.max(a.length, b.length) - 1);

  const na = normalize(a);
  const nb = normalize(b);

  // ■ 重なりが短い lag は見ない（実測で必要だった）
  //
  // 重なり長で割って正規化しても、重なりが数秒まで減ると
  // 偶然そこだけ形が合って高いスコアが出る。
  // 20秒の窓に探索幅15秒を与えたとき、正しい答え（+3.13秒）より
  // 誤った端のほう（-13.59秒、重なり6秒）が高スコアになった。
  //
  // そこで「窓の何割かは重なっていること」を条件にする。
  // 探索幅が窓に対して広すぎる場合も、ここで自動的に狭まる。
  const shorter = Math.min(na.length, nb.length);
  const minOverlap = Math.max(sampleRate, Math.floor(shorter * minOverlapRatio));

  let bestLag = 0;
  let bestScore = -Infinity;

  for (let lag = -maxLag; lag <= maxLag; lag++) {
    // b が lag だけ遅れているとき b[i+lag] = a[i] になる。
    // よって a[i] と b[i+lag] を突き合わせ、最も一致する lag が「bの遅れ」。
    const start = Math.max(0, -lag);
    const end = Math.min(na.length, nb.length - lag);
    const count = end - start;

    if (count < minOverlap) continue;

    let sum = 0;
    for (let i = start; i < end; i++) {
      sum += na[i] * nb[i + lag];
    }

    // 重なりが短いほど偶然スコアが跳ねやすいので、重なり長で正規化する
    const score = sum / count;
    if (score > bestScore) {
      bestScore = score;
      bestLag = lag;
    }
  }

  // どの lag も重なりが足りなかった（窓が探索幅より短いなど）
  if (bestScore === -Infinity) {
    return { offsetSec: 0, score: -Infinity, tooShort: true };
  }

  return { offsetSec: bestLag / sampleRate, score: bestScore };
}

/**
 * 1つの窓に最低これだけの秒数を確保する。
 * 短い窓は偶然一致しやすく、「合意できた」という誤判定を生む。
 */
export const MIN_WINDOW_SEC = 15;

/**
 * タイムライン上の複数地点でオフセットを測り、ずれが一定かどうか確かめる。
 *
 * ■ 相関スコアの高さは当てにならない
 *
 * セミナー音声は同じ部屋・同じ声で似た音が続くため、誤った位置のほうが
 * 高スコアになることが実際にある（移植元で冒頭窓が +63秒 で最高スコアに
 * なった例がある）。本当のオフセットは「多くの窓が同じ値で一致するもの」
 * なので、スコアではなく多数決で決める。
 */
export function verifySync(envA, envB, envRate, windows = 5, maxLagSec = 30,
                           minWindowSec = MIN_WINDOW_SEC) {
  const winLen = Math.floor(Math.min(envA.length, envB.length) / windows);
  const points = [];

  // 窓が短すぎると相関が当てにならないので、最低の長さを確保する。
  // 既定は15秒。ここを下げすぎると、短い窓が偶然一致して
  // 「合意できた」と誤判定する（移植元は30秒固定だった）。
  if (winLen < envRate * minWindowSec) {
    const g = crossCorrelate(envA, envB, envRate, maxLagSec);
    return {
      offsetSec: g.offsetSec, score: g.score, drift: false,
      points: [], maxDeviationSec: 0, lowConfidence: false, singleWindow: true,
    };
  }

  for (let i = 0; i < windows; i++) {
    const start = i * winLen;
    const a = envA.subarray(start, start + winLen);
    const b = envB.subarray(start, start + winLen);
    if (a.length < envRate || b.length < envRate) continue;

    const r = crossCorrelate(a, b, envRate, maxLagSec);
    // 窓が探索幅に対して短すぎて測れなかったものは数に入れない
    if (r.tooShort) continue;
    points.push({ atSec: start / envRate, offsetSec: r.offsetSec, score: r.score });
  }

  if (points.length === 0) {
    const g = crossCorrelate(envA, envB, envRate, maxLagSec);
    return {
      offsetSec: g.offsetSec, score: g.score, drift: false,
      points: [], maxDeviationSec: 0, lowConfidence: false, singleWindow: true,
    };
  }

  const TOL = 0.5; // これ以内なら同じオフセットとみなす

  let best = { offset: points[0].offsetSec, members: [] };
  for (const cand of points) {
    const members = points.filter((p) => Math.abs(p.offsetSec - cand.offsetSec) <= TOL);
    // 同数なら相関スコアの合計が高いほうを採る
    const sum = (arr) => arr.reduce((s, p) => s + p.score, 0);
    if (
      members.length > best.members.length ||
      (members.length === best.members.length && sum(members) > sum(best.members))
    ) {
      best = { offset: cand.offsetSec, members };
    }
  }

  const offsets = best.members.map((p) => p.offsetSec).sort((x, y) => x - y);
  const median = offsets[Math.floor(offsets.length / 2)];

  // 合意した窓だけでばらつきを見る。合意から外れた窓は誤検出として無視する。
  let maxDeviationSec = 0;
  for (const p of best.members) {
    maxDeviationSec = Math.max(maxDeviationSec, Math.abs(p.offsetSec - median));
  }

  const meanScore = best.members.reduce((s, p) => s + p.score, 0) / best.members.length;

  // 過半数が一致していないなら、そもそも同期が信用できない
  const consensus = best.members.length / points.length;
  if (consensus < 0.5) {
    return {
      offsetSec: median, score: meanScore, drift: true, points,
      maxDeviationSec: Math.max(...points.map((p) => Math.abs(p.offsetSec - median))),
      lowConfidence: true, agreed: best.members.length, total: points.length,
    };
  }

  return {
    offsetSec: median,
    score: meanScore,
    // 合意した窓の中でばらつくなら、録画の中断など単一オフセットで扱えない要因がある
    drift: maxDeviationSec > 0.5,
    points,
    maxDeviationSec,
    lowConfidence: false,
    agreed: best.members.length,
    total: points.length,
  };
}

/**
 * 位置の手がかりが無い状態で、b が a のどこにあるかを全域から探す。
 *
 * 撮影時刻が壊れているとき（コピーやクラウド経由で日時が失われた場合）に使う。
 * 総当たりは重すぎるので、粗く間引いて全域を探し、
 * 見つかった位置の周辺だけを細かく見直す二段構えにする。
 *
 * @returns offsetSec は「a の何秒目に b の先頭が来るか」
 */
export function findOffsetFullRange(envA, envB, envRate, coarseHz = 5) {
  const empty = { offsetSec: 0, score: 0, confident: false, margin: 0 };
  if (!envA || !envB || envA.length === 0 || envB.length === 0) return empty;

  const factor = Math.max(1, Math.round(envRate / coarseHz));
  const a = downsampleEnvelope(envA, factor);
  const b = downsampleEnvelope(envB, factor);
  if (a.length === 0 || b.length === 0) return empty;

  const rate = envRate / factor;

  // 粗探索: b の先頭を a のどこに置くかを全域で試す。
  // 重なりが短いところは偶然スコアが跳ねるので、最低限の重なりを要求する。
  const minOverlap = Math.max(1, Math.floor(Math.min(a.length, b.length) * 0.3));
  const na = normalize(a);
  const nb = normalize(b);

  let bestLag = 0;
  let bestScore = -Infinity;
  let second = -Infinity;

  for (let lag = -(b.length - 1); lag <= a.length - 1; lag++) {
    const start = Math.max(0, lag);
    const end = Math.min(a.length, lag + b.length);
    const count = end - start;
    if (count < minOverlap) continue;

    let sum = 0;
    for (let i = start; i < end; i++) sum += na[i] * nb[i - lag];
    const score = sum / count;

    if (score > bestScore) {
      second = bestScore;
      bestScore = score;
      bestLag = lag;
    } else if (score > second) {
      second = score;
    }
  }

  if (bestScore === -Infinity) return empty;

  // 細探索: 粗い答えの周りだけ、元の解像度で見直す
  const coarseSec = bestLag / rate;
  const shift = Math.round(coarseSec * envRate);
  const span = Math.max(1, Math.round((factor / envRate) * 2 * envRate));

  let fineBest = { offsetSec: coarseSec, score: bestScore };
  for (let d = -span; d <= span; d++) {
    const lag = shift + d;
    const start = Math.max(0, lag);
    const end = Math.min(envA.length, lag + envB.length);
    const count = end - start;
    if (count < envRate) continue;

    const sa = normalize(envA.subarray(start, end));
    const sb = normalize(envB.subarray(start - lag, end - lag));
    let sum = 0;
    for (let i = 0; i < count; i++) sum += sa[i] * sb[i];
    const score = sum / count;
    if (score > fineBest.score) fineBest = { offsetSec: lag / envRate, score };
  }

  // 2番目の候補と差が無いなら、どれが正解か決められていない
  const margin = second === -Infinity ? 1 : bestScore - second;
  return {
    offsetSec: fineBest.offsetSec,
    score: fineBest.score,
    confident: margin > 0.05 && fineBest.score > 0.2,
    margin,
  };
}

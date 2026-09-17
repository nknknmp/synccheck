/*
 * SyncCheck - 複数本を実時間軸に載せて、重なる組を見つける
 *
 * このアプリの主目的。2カメでも録画を止めて再開するため、
 * A側3本 / B側3本のような構成になる。
 * **組ごとにズレ方が変わる**ので、1組目の値を他に当てはめてはいけない
 * （移植元のノートに「組ごとに別の値になる」と実測が残っている）。
 *
 * SemiCut の src/core.js から placeOnTimeline / resolveRecordingTimes を移植。
 */

/**
 * 各ファイルが「実際に何時何分から録画されたか」を決める。
 *
 * ■ 更新日時はあてにならない
 *
 * File.lastModified は録画終了時刻とは限らない。移植元で素材23本を
 * 調べた結果:
 *
 *   mp4（スマホ）          更新日時 = 録画終了
 *   mov（iPad / LocalSend）更新日時 = 録画終了
 *   MOV（iPad / USB）      更新日時 = 録画開始   ← これだけ違う
 *
 * 同じ iPad の同じ録画でも、取り込み経路が違うだけで意味が変わる。
 * USB（MTP）で吸い出すと Windows は端末側の「作成日時」をファイルの
 * 日時にするが、LocalSend は端末側の「更新日時」をそのまま渡すため。
 *
 * ■ 動画の中の撮影時刻（creation_time）のほうが安定している
 *
 * こちらはファイルの中身なので、コピーしても消えない。
 * ただし開始か終了かはカメラで違う（iPad=開始 / スマホ=終了）ので、
 * これ単体でも決め打ちはできない。
 *
 * ■ 両方を突き合わせると、その場で確定できる場合がある
 *
 *   更新日時 ≒ 埋め込み + 長さ
 *     → 更新日時は録画終了、埋め込みは録画開始。**確定**（実測8本）
 *
 * 確定しないものだけ2通り試して「2台のカメラは同じ時間帯を撮っている」
 * という事実で決める。A側とB側の重なりが増えるほうを採る。
 */
const NEAR_MS = 5000;   // 5秒以内なら同じ時刻とみなす（実測の誤差は0〜2秒）

export function resolveRecordingTimes(groupA, groupB) {
  const prep = (files) => files.map((f) => {
    const ms = f.lastModified != null ? f.lastModified
      : (f.file && f.file.lastModified != null ? f.file.lastModified : 0);
    const cms = f.creationMs != null ? f.creationMs
      : (f.file && f.file.creationMs != null ? f.file.creationMs : null);
    const durMs = (f.duration || 0) * 1000;

    // 候補は「録画開始はいつか」の案。先頭が既定。
    let candidates;
    if (cms != null && cms > 0) {
      if (Math.abs(ms - (cms + durMs)) < NEAR_MS) {
        // 更新日時が「埋め込み＋長さ」＝録画終了。埋め込みが開始で確定。
        candidates = [cms];
      } else {
        // 埋め込みが開始なのか終了なのか決められない。両方試す。
        // 更新日時はここでは使わない（壊れている可能性があるため）。
        candidates = [cms, cms - durMs];
      }
    } else {
      // 埋め込みが無い素材。従来どおり更新日時で判断する。
      candidates = [ms - durMs, ms];
    }
    return { f, durMs, candidates, idx: 0 };
  });

  const A = prep(groupA);
  const B = prep(groupB);
  if (A.length === 0 || B.length === 0) {
    return { groupA, groupB, resolved: false };
  }

  const startOf = (x) => x.candidates[x.idx];
  const total = () => {
    let sec = 0;
    for (const a of A) {
      for (const b of B) {
        const s1 = startOf(a), e1 = s1 + a.durMs;
        const s2 = startOf(b), e2 = s2 + b.durMs;
        sec += Math.max(0, Math.min(e1, e2) - Math.max(s1, s2));
      }
    }
    return sec;
  };

  // 1本ずつ別の候補にしてみて、重なりが増えるなら採用する。
  // 変化が無くなるまで繰り返す（数本なので数回で収束する）。
  // 候補が1つに確定しているファイルは動かさない。
  const all = [...A, ...B].filter((x) => x.candidates.length > 1);
  for (let pass = 0; pass < 4; pass++) {
    let changed = false;
    for (const x of all) {
      const before = total();
      x.idx = 1 - x.idx;
      if (total() <= before) x.idx = 1 - x.idx;   // 良くならないなら戻す
      else changed = true;
    }
    if (!changed) break;
  }

  const applied = (arr) => arr.map((x) => ({ ...x.f, startMs: startOf(x) }));
  return { groupA: applied(A), groupB: applied(B), resolved: true };
}

/**
 * 全ファイルを共通の秒数軸に載せる。
 * いちばん早いファイルの開始を 0 秒とする。
 */
export function placeOnTimeline(files) {
  const items = files.map((f) => {
    const dur = f.duration || 0;
    // resolveRecordingTimes が決めた開始時刻があればそれに従う。
    if (f.startMs != null) {
      return { ...f, _startMs: f.startMs, _endMs: f.startMs + dur * 1000 };
    }
    const endMs = f.lastModified != null ? f.lastModified
      : (f.file && f.file.lastModified != null ? f.file.lastModified : 0);
    return { ...f, _endMs: endMs, _startMs: endMs - dur * 1000 };
  });

  if (items.length === 0) return [];

  const base = Math.min(...items.map((i) => i._startMs));

  return items
    .map((i) => ({
      ...i,
      startSec: (i._startMs - base) / 1000,
      endSec: (i._endMs - base) / 1000,
      baseMs: base,
    }))
    .sort((a, b) => a.startSec - b.startSec);
}

/**
 * A側とB側をまとめて1つの実時間軸に載せる。
 * 両方に共通の原点を使わないと意味がないので、ここでまとめて計算する。
 */
export function buildTimeline(groupA, groupB) {
  const fixed = resolveRecordingTimes(groupA, groupB);
  const all = placeOnTimeline([...fixed.groupA, ...fixed.groupB]);
  const inB = new Set(fixed.groupB.map((f) => f.name));
  return {
    groupA: all.filter((f) => !inB.has(f.name)),
    groupB: all.filter((f) => inB.has(f.name)),
    all,
    resolved: fixed.resolved,
  };
}

/** 重なりが短すぎると相関が当てにならない。これ未満の組は測らない。 */
export const MIN_OVERLAP_SEC = 10;

/**
 * 時間軸上で重なっている A×B の組を洗い出す。
 *
 * 「途中で切れて再開する」構成では、重なる組は
 * A1-B1 / A2-B2 のように素直に並ぶことが多いが、
 * 片方だけ切れた場合は A2 が B1 と B2 の両方に重なる。
 * そのため総当たりで見て、重なりのある組すべてを返す。
 *
 * @returns {Array<{a, b, overlapStartSec, overlapEndSec, overlapSec,
 *                  aOffsetSec, bOffsetSec}>}
 *   aOffsetSec / bOffsetSec は、その組の重なり部分が
 *   各ファイルの先頭から何秒目に当たるか（音声を抜く位置）。
 */
export function findOverlappingPairs(timeline, minOverlapSec = MIN_OVERLAP_SEC) {
  const pairs = [];

  for (const a of timeline.groupA) {
    for (const b of timeline.groupB) {
      const start = Math.max(a.startSec, b.startSec);
      const end = Math.min(a.endSec, b.endSec);
      const overlap = end - start;
      if (overlap < minOverlapSec) continue;

      pairs.push({
        a, b,
        overlapStartSec: start,
        overlapEndSec: end,
        overlapSec: overlap,
        // その組の重なりが、各ファイルの何秒目から始まるか
        aOffsetSec: start - a.startSec,
        bOffsetSec: start - b.startSec,
      });
    }
  }

  // 重なりが長い組から測る。長いほど答えが安定するため。
  pairs.sort((x, y) => y.overlapSec - x.overlapSec);
  return pairs;
}

/**
 * どのファイルも組に入らなかったものを拾う。
 * 撮影時刻が壊れている、または本当に重なっていない。
 */
export function findOrphans(timeline, pairs) {
  const used = new Set();
  for (const p of pairs) {
    used.add(p.a.name);
    used.add(p.b.name);
  }
  return timeline.all.filter((f) => !used.has(f.name));
}

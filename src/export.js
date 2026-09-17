/*
 * SyncCheck - 書き出し（オプション）
 *
 * 測った結果を、手で読める形と編集ソフトに渡せる形で出す。
 * 動画そのものは書き出さない（このアプリは測るだけ）。
 */

// ---------------------------------------------------------------------------
// テキスト / CSV / JSON
// ---------------------------------------------------------------------------

/** 秒を 1:23:45.67 の形にする */
export function fmtClock(sec) {
  const sign = sec < 0 ? '-' : '';
  const s = Math.abs(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = s % 60;
  const mm = String(m).padStart(2, '0');
  const ss = rest.toFixed(2).padStart(5, '0');
  return h > 0 ? `${sign}${h}:${mm}:${ss}` : `${sign}${m}:${ss}`;
}

/** 符号つきで秒を出す（+3.13秒 / -0.42秒） */
export function fmtOffset(sec) {
  return `${sec >= 0 ? '+' : ''}${sec.toFixed(2)}秒`;
}

export function buildReportText(results, summary, meta = {}) {
  const L = [];
  L.push('════════════════════════════════════════');
  L.push(' SyncCheck 測定結果');
  L.push('════════════════════════════════════════');
  L.push('');
  L.push(`測った日時: ${new Date().toLocaleString('ja-JP')}`);
  if (meta.groupAName) L.push(`A側（基準）: ${meta.groupAName}`);
  if (meta.groupBName) L.push(`B側: ${meta.groupBName}`);
  L.push(`組の数: ${summary.total}（測れた ${summary.ok} / 測れなかった ${summary.failed}）`);
  L.push('');

  if (summary.warnings.length > 0) {
    L.push('── 注意 ──────────────────────');
    for (const w of summary.warnings) L.push(`  ・${w}`);
    L.push('');
  }

  L.push('── 組ごとの結果 ──────────────');
  L.push('');
  for (const r of results) {
    L.push(`【${r.label}】`);
    if (!r.ok) {
      L.push(`  測れなかった: ${r.reason}`);
      L.push('');
      continue;
    }

    L.push(`  合わせるズレ  ${fmtOffset(r.totalOffsetSec)}`);
    L.push(`    B の 0秒目 = A の ${fmtOffset(r.totalOffsetSec)} の位置`);
    L.push(`  内訳`);
    L.push(`    撮影時刻の差   ${fmtOffset(r.timeGapSec)}`);
    L.push(`    音で測った差   ${fmtOffset(r.measuredSec)}`);
    L.push(`  重なり ${r.pair.overlapSec.toFixed(1)}秒 のうち ${r.measuredLenSec.toFixed(0)}秒 で測定`);
    L.push(`  相関スコア ${r.score.toFixed(3)}`);

    if (r.singleWindow) {
      L.push(`  ※ 短いので1回しか測っていない（窓に分けられなかった）`);
    } else {
      L.push(`  窓ごとの測定値（${r.points.length}窓）`);
      for (const p of r.points) {
        L.push(`    ${fmtClock(p.atSec).padStart(8)} → ${fmtOffset(p.offsetSec).padStart(9)}`
               + `  (スコア ${p.score.toFixed(3)})`);
      }
      L.push(`  窓のばらつき 最大 ${r.maxDeviationSec.toFixed(2)}秒`);
    }

    if (r.note) {
      L.push(`  ★ ${r.note}`);
    }
    if (r.lowConfidence && !r.note) {
      L.push(`  ★ 窓の過半数が一致しなかった。この値は信用できない`);
    }
    if (r.drift) {
      L.push(`  ★ 区間ごとにズレが変わっている。1つの値では合わせられない`);
    }
    L.push('');
  }

  L.push('── 読み方 ────────────────────');
  L.push('');
  L.push('「合わせるズレ」が +3.13秒 なら、B側の映像を');
  L.push('タイムライン上で 3.13秒 後ろにずらすと合う。');
  L.push('負の値なら前にずらす。');
  L.push('');
  L.push('★ が付いた組は、値をそのまま使わないこと。');
  L.push('  音が似ている区間で誤検出している可能性がある。');
  L.push('  編集ソフトで実際に波形を見て確かめること。');
  L.push('');
  L.push('════════════════════════════════════════');
  return L.join('\n');
}

export function buildCSV(results) {
  const rows = [[
    'A側ファイル', 'B側ファイル', '合わせるズレ秒', '撮影時刻の差秒',
    '音で測った差秒', '重なり秒', '測定長秒', 'スコア',
    'ドリフト', '信用できない', '備考',
  ]];

  for (const r of results) {
    if (!r.ok) {
      rows.push([r.pair.a.name, r.pair.b.name, '', '', '',
                 r.pair.overlapSec.toFixed(1), '', '', '', '', r.reason]);
      continue;
    }
    rows.push([
      r.pair.a.name, r.pair.b.name,
      r.totalOffsetSec.toFixed(3), r.timeGapSec.toFixed(3),
      r.measuredSec.toFixed(3), r.pair.overlapSec.toFixed(1),
      r.measuredLenSec.toFixed(0), r.score.toFixed(4),
      r.drift ? 'あり' : '', r.lowConfidence ? 'はい' : '',
      r.singleWindow ? '窓に分けられず1回測定' : '',
    ]);
  }

  // Excel で開いたとき文字化けしないよう BOM を付ける
  return '﻿' + rows.map((r) =>
    r.map((c) => {
      const s = String(c);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(',')
  ).join('\r\n');
}

export function buildJSON(results, summary) {
  return JSON.stringify({
    app: 'SyncCheck',
    measuredAt: new Date().toISOString(),
    summary,
    pairs: results.map((r) => r.ok ? {
      a: r.pair.a.name,
      b: r.pair.b.name,
      totalOffsetSec: Number(r.totalOffsetSec.toFixed(3)),
      timeGapSec: Number(r.timeGapSec.toFixed(3)),
      measuredSec: Number(r.measuredSec.toFixed(3)),
      overlapSec: Number(r.pair.overlapSec.toFixed(1)),
      measuredLenSec: r.measuredLenSec,
      score: Number(r.score.toFixed(4)),
      drift: r.drift,
      lowConfidence: r.lowConfidence,
      singleWindow: r.singleWindow,
      windows: r.points.map((p) => ({
        atSec: Number(p.atSec.toFixed(2)),
        offsetSec: Number(p.offsetSec.toFixed(3)),
        score: Number(p.score.toFixed(4)),
      })),
    } : {
      a: r.pair.a.name, b: r.pair.b.name, ok: false, reason: r.reason,
    }),
  }, null, 2);
}

// ---------------------------------------------------------------------------
// fcpxml
// ---------------------------------------------------------------------------

/**
 * フレームレートごとの時間の刻み。
 * fcpxml の時間は「分子/分母s」の分数で書く。整数フレームに丸めないと
 * 編集ソフト側で1フレームずれることがある。
 */
export const TIMEBASE = {
  30:    { fd: 100,  tb: 3000,  name: '30p' },
  29.97: { fd: 1001, tb: 30000, name: '2997p' },
  25:    { fd: 120,  tb: 3000,  name: '25p' },
  24:    { fd: 125,  tb: 3000,  name: '24p' },
  60:    { fd: 50,   tb: 3000,  name: '60p' },
};

export function timebaseFor(fps) {
  return TIMEBASE[fps] || TIMEBASE[30];
}

/**
 * 実測のフレームレートを、よく使う値のどれかに寄せる。
 * ffprobe は 29.97 を 29.97003 のように返してくるため。
 */
export function nearestFps(fps) {
  const known = Object.keys(TIMEBASE).map(Number);
  let best = 30, diff = Infinity;
  for (const k of known) {
    const d = Math.abs(k - fps);
    if (d < diff) { diff = d; best = k; }
  }
  return best;
}

/** 秒を fcpxml の分数表記にする。フレーム単位に丸める。 */
export function toTime(sec, fd = 100, tb = 3000) {
  const frames = Math.round((sec * tb) / fd);
  return `${frames * fd}/${tb}s`;
}

export function xmlEscape(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * 測定結果を fcpxml にする。
 *
 * ■ 何が入るか
 *
 * A側を下のトラック、B側を lane="1" の上のトラックに置き、
 * 測ったズレのぶんだけ B をずらして並べる。
 * 組が複数あれば、時間軸の順に並べて1本のタイムラインにする。
 *
 * ■ 入らないもの
 *
 * カット、色、位置、拡大。このアプリは測るだけなので、
 * 「同期した状態で並んでいる」ところまでしか作らない。
 *
 * ■ 実機未確認
 *
 * Resolve / FCP で開けるかは、このPCでは確かめられない
 * （実機が繋がっていない）。開けなかったときは
 * 使い方.txt の「fcpxml が開けないとき」を見ること。
 */
export function buildFCPXML(results, options = {}) {
  const {
    fps = 30,
    width = 1920,
    height = 1080,
    projectName = 'SyncCheck',
  } = options;

  const ok = results.filter((r) => r.ok);
  if (ok.length === 0) {
    throw new Error('書き出せる組がありません（測れた組が0）');
  }

  const nf = nearestFps(fps);
  const { fd, tb, name: fpsName } = timebaseFor(nf);
  const T = (sec) => toTime(sec, fd, tb);

  // ファイルごとに asset を作る。同じファイルが複数の組に出てくることがある。
  const assets = new Map();
  const assetId = (f) => {
    if (!assets.has(f.name)) {
      assets.set(f.name, {
        id: `r${assets.size + 2}`,   // r1 は format に使う
        name: f.name,
        duration: f.duration || 0,
        // ブラウザはファイルの絶対パスを知らないので、名前だけ書く。
        // 編集ソフト側で「見つからない」と言われたら、素材を指定し直すこと。
        //
        // ここで encodeURIComponent はかけない。出力時に xmlEscape を通すので、
        // 両方かけると & が &amp;25... のように二重に化ける。
        src: `./${f.name}`,
      });
    }
    return assets.get(f.name).id;
  };

  // 先に全部の id を確定させる
  for (const r of ok) { assetId(r.pair.a); assetId(r.pair.b); }

  // タイムライン上の置き場所を決める。
  // 組を時間順に並べ、A側の開始が早いものから詰めていく。
  const sorted = [...ok].sort((x, y) => x.pair.a.startSec - y.pair.a.startSec);

  const clips = [];
  let cursor = 0;

  for (const r of sorted) {
    const { a, b } = r.pair;
    const aDur = a.duration || r.pair.overlapSec;
    const bDur = b.duration || r.pair.overlapSec;

    // B は「A の何秒目に B の先頭が来るか」の位置に置く
    const bStart = cursor + r.totalOffsetSec;

    // A より前に出てしまう場合は、B の頭を削って合わせる。
    // マイナス位置に置くと編集ソフトが読めない。
    const bOffsetIntoSource = bStart < cursor ? cursor - bStart : 0;
    const bPlaceAt = Math.max(cursor, bStart);
    const bVisibleDur = bDur - bOffsetIntoSource;

    const inner = bVisibleDur > 0 ? [
      `                    <asset-clip lane="1" ref="${assetId(b)}"`
      + ` name="${xmlEscape(b.name)}"`
      + ` offset="${T(bPlaceAt)}"`
      + ` start="${T(bOffsetIntoSource)}"`
      + ` duration="${T(bVisibleDur)}"`
      + ` audioRole="dialogue"/>`,
    ] : [];

    clips.push(
      `                <asset-clip ref="${assetId(a)}"`
      + ` name="${xmlEscape(a.name)}"`
      + ` offset="${T(cursor)}"`
      + ` start="0s"`
      + ` duration="${T(aDur)}"`
      + ` audioRole="dialogue">`,
      ...inner,
      `                </asset-clip>`
    );

    cursor += aDur;
  }

  const assetLines = [...assets.values()].map((a) =>
    `        <asset id="${a.id}" name="${xmlEscape(a.name)}"`
    + ` start="0s" duration="${T(a.duration)}"`
    + ` hasVideo="1" hasAudio="1" format="r1"`
    + ` audioSources="1" audioChannels="2">\n`
    + `            <media-rep kind="original-media" src="${xmlEscape(a.src)}"/>\n`
    + `        </asset>`
  );

  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<!DOCTYPE fcpxml>`,
    `<!--`,
    `  SyncCheck が書き出したファイル`,
    `  ${new Date().toLocaleString('ja-JP')}`,
    ``,
    `  A側を下、B側を上（lane 1）に置き、測ったズレのぶんだけ`,
    `  B をずらして並べてある。カットや色の調整は入っていない。`,
    `  素材の場所はファイル名だけなので、開いたあと指定し直す必要がある。`,
    `-->`,
    `<fcpxml version="1.9">`,
    `    <resources>`,
    `        <format id="r1" name="FFVideoFormat${width}x${height}${fpsName}"`
    + ` frameDuration="${fd}/${tb}s" width="${width}" height="${height}"`
    + ` colorSpace="1-1-1 (Rec. 709)"/>`,
    ...assetLines,
    `    </resources>`,
    `    <library>`,
    `        <event name="${xmlEscape(projectName)}">`,
    `            <project name="${xmlEscape(projectName)}">`,
    `                <sequence format="r1" duration="${T(cursor)}"`
    + ` tcStart="0s" tcFormat="NDF"`
    + ` audioLayout="stereo" audioRate="48k">`,
    `                    <spine>`,
    ...clips.map((l) => '    ' + l),
    `                    </spine>`,
    `                </sequence>`,
    `            </project>`,
    `        </event>`,
    `    </library>`,
    `</fcpxml>`,
  ].join('\n');
}

/**
 * 文字列をファイルとして保存させる。
 *
 * ブラウザから保存する方法は2つある。
 * File System Access API が使えるなら保存先を選べる。
 * 使えない（Safari など）なら a[download] に落とす。
 */
export async function saveText(filename, text, mime = 'text/plain') {
  if (window.showSaveFilePicker) {
    try {
      const ext = filename.split('.').pop();
      const handle = await window.showSaveFilePicker({
        suggestedName: filename,
        types: [{ description: ext.toUpperCase(), accept: { [mime]: [`.${ext}`] } }],
      });
      const w = await handle.createWritable();
      await w.write(text);
      await w.close();
      return true;
    } catch (err) {
      if (err.name === 'AbortError') return false;   // ユーザーが取り消した
      // それ以外は下の方法に落とす
    }
  }

  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return true;
}

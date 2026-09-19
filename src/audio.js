/*
 * SyncCheck - 音声の抜き出し（ffmpeg.wasm）
 *
 * 動画はブラウザの中だけで扱う。サーバーに送らない。
 * 抜くのは 8kHz モノラルの PCM だけで、映像は 1 フレームも読まない
 * （-vn）。1時間の動画でも 8kHz×4byte ≒ 115MB だが、
 * 必要なのは一部の区間だけなので実際にはもっと小さい。
 *
 * ■ concat してから -ss してはいけない（移植元の実測）
 *
 * SemiCut で、横動画が複数本のとき concat デマルチプレクサでつないでから
 * -ss で頭出しすると、指定した位置ちょうどには止まらなかった。
 *
 *   4.069秒を頼んだら 5.08秒 から返ってきた（1.01秒 late）
 *
 * 同期はこの音声で測るので、測定値がまるごとずれる。
 * このアプリは**必ず1本ずつ抜く**。つなぐ処理は持たない
 * （組ごとに測るので、つなぐ必要がそもそも無い）。
 */

// CDN から直接読むと、ffmpeg が内部で立ち上げる worker が
// 「別オリジンのスクリプトは Worker にできない」というブラウザの制限に
// 引っかかる。そのため一式を vendor/ に置いて、同一オリジンから読む。
const VENDOR = new URL('../vendor/', import.meta.url);
const FFMPEG_BASE = new URL('core/', VENDOR).href;

let ffmpeg = null;
let loadPromise = null;
let logging = false;   // ffmpeg の生ログを流すか（既定は黙らせる）

export const SYNC_RATE = 8000;   // 同期用 PCM のサンプルレート
export const ENV_RATE = 100;     // エンベロープのサンプルレート

/** ffmpeg の生ログを画面に出すかどうか。不具合を追うときだけ true にする。 */
export function setLogging(on) {
  logging = !!on;
}

export function isLoaded() {
  return ffmpeg !== null;
}

/**
 * ffmpeg.wasm を読み込む。初回は数十MBのダウンロードが走る。
 *
 * iPad Safari には SharedArrayBuffer が無い前提でシングルスレッド版を使う。
 * マルチスレッド版のほうが速いが、動く端末が限られる。
 * このアプリは音声だけなので、シングルスレッドでも実用になる。
 */
export async function loadFFmpeg(onProgress = () => {}) {
  if (ffmpeg) return ffmpeg;
  if (loadPromise) return loadPromise;

  loadPromise = (async () => {
    const { FFmpeg } = await import(new URL('ffmpeg/index.js', VENDOR).href);
    const { toBlobURL } = await import(new URL('util/index.js', VENDOR).href);

    const inst = new FFmpeg();

    // ffmpeg のログは1行ずつ大量に出る。読み込み中だけ伝えて、
    // そのあとは黙らせる（画面が ffmpeg のログで埋まると読めなくなる）。
    // 詳しく見たいときは logging を true にする。
    const relay = ({ message }) => {
      if (logging) onProgress({ type: 'log', message });
    };
    inst.on('log', relay);

    onProgress({ type: 'log', message: 'FFmpeg を読み込んでいます...' });

    await inst.load({
      coreURL: await toBlobURL(`${FFMPEG_BASE}ffmpeg-core.js`, 'text/javascript'),
      wasmURL: await toBlobURL(`${FFMPEG_BASE}ffmpeg-core.wasm`, 'application/wasm'),
    });

    ffmpeg = inst;
    onProgress({ type: 'log', message: 'FFmpeg の準備ができました' });
    return inst;
  })();

  try {
    return await loadPromise;
  } catch (err) {
    loadPromise = null;
    throw err;
  }
}

/**
 * 1本のファイルから、同期用の PCM を抜く。
 *
 * @param {File} file ブラウザが持っているファイル（アップロードはしない）
 * @param {number} startSec 抜き始める位置
 * @param {number} durationSec 抜く長さ
 * @returns {Float32Array}
 */
export async function extractSyncPCM(file, startSec = 0, durationSec = null) {
  const ff = await loadFFmpeg();
  const ext = (file.name || 'x.mp4').split('.').pop().toLowerCase();
  const input = `in_${Date.now()}.${ext}`;
  const output = 'out.raw';

  await ff.writeFile(input, new Uint8Array(await file.arrayBuffer()));

  try {
    const args = [];
    // -ss を -i より前に置くと速い（キーフレーム単位で飛ぶ）。
    // 1本のファイルへの -ss は正確（実測 0.000秒）。
    // concat 経由だとずれるので、このアプリはつながない。
    if (startSec > 0) args.push('-ss', String(startSec));
    if (durationSec != null) args.push('-t', String(durationSec));

    await ff.exec([
      ...args,
      '-i', input,
      '-vn',                        // 映像は読まない
      '-ac', '1',                   // モノラル
      '-ar', String(SYNC_RATE),     // 8kHz
      '-f', 'f32le',
      output,
    ]);

    const data = await ff.readFile(output);
    await ff.deleteFile(output);
    return new Float32Array(
      data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)
    );
  } finally {
    try { await ff.deleteFile(input); } catch { /* 消せなくても進む */ }
  }
}

/**
 * ファイルの長さと、中に埋め込まれた撮影時刻を読む。
 *
 * ■ なぜ埋め込みの時刻が要るか
 *
 * File.lastModified は「録画終了」とは限らない（取り込み経路で意味が変わる）。
 * 詳しくは src/timeline.js のコメント。
 * 埋め込みの creation_time はコピーしても消えないので、こちらを優先したい。
 *
 * ffmpeg.wasm には ffprobe が無いので、-i だけ実行して
 * ログに出るメタデータから読み取る。
 */
export async function readMeta(file) {
  const ff = await loadFFmpeg();
  const ext = (file.name || 'x.mp4').split('.').pop().toLowerCase();
  const input = `probe_${Date.now()}.${ext}`;

  const lines = [];
  const collect = ({ message }) => lines.push(message);
  ff.on('log', collect);

  await ff.writeFile(input, new Uint8Array(await file.arrayBuffer()));

  try {
    // メタデータは -i を読んだ時点でログに出るので、変換は要らない。
    // -t 0 で「0秒だけ処理する」とし、映像のデコードを走らせない。
    // -f null - で全部デコードすると、2時間の動画で何十秒もかかる。
    try {
      await ff.exec(['-i', input, '-t', '0', '-f', 'null', '-']);
    } catch { /* 解析だけが目的なので失敗してよい */ }

    const text = lines.join('\n');

    // Duration: 00:10:00.53
    let duration = 0;
    const d = text.match(/Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/);
    if (d) {
      duration = Number(d[1]) * 3600 + Number(d[2]) * 60 + Number(d[3]);
    }

    // creation_time : 2026-09-14T10:23:45.000000Z
    let creationMs = null;
    const c = text.match(/creation_time\s*:\s*(\S+)/);
    if (c) {
      const t = Date.parse(c[1]);
      if (!Number.isNaN(t)) creationMs = t;
    }

    // 音声トラックが無いファイルは同期を測れないので先に分かるようにする
    const hasAudio = /Stream #\d+:\d+.*: Audio:/.test(text);

    // フレームレート（ズレをフレーム数で見せるのに使う）
    //
    //   Video: hevc ..., 1280x720, 4841 kb/s, 30 fps, 30 tbr, ...
    //
    // 入力側の行だけを見る。-f null で出る出力側の行にも fps があり、
    // そちらは変換後の値なので素材のものではない。
    let fps = null;
    const vLine = text.match(/Stream #\d+:\d+[^\n]*: Video:[^\n]*/);
    if (vLine) {
      const m = vLine[0].match(/([\d.]+)\s*fps/);
      if (m) {
        const v = Number(m[1]);
        if (v > 0 && v < 1000) fps = v;
      }
    }

    return { duration, creationMs, hasAudio, fps, log: text };
  } finally {
    ff.off('log', collect);
    try { await ff.deleteFile(input); } catch { /* 消せなくても進む */ }
  }
}

/**
 * ブラウザだけでファイルの長さを読む（ffmpeg を使わない速い道）。
 *
 * <video> に読ませて duration を見るだけなので一瞬で終わる。
 * ただし埋め込みの撮影時刻は読めない。
 * ファイルを並べて見せる最初の表示に使い、必要になったら readMeta に進む。
 */
export function readDurationQuick(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement('video');
    v.preload = 'metadata';

    const done = (duration) => {
      URL.revokeObjectURL(url);
      resolve(duration);
    };

    v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : 0);
    v.onerror = () => done(0);   // ブラウザが読めない形式。ffmpeg 側に任せる
    v.src = url;
  });
}

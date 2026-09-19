/*
 * SyncCheck のオフライン用キャッシュ
 *
 * 出先で使うのが前提なので、圏外・細い回線でも開けるようにする。
 * 初回に一式（ffmpeg.wasm 約31MB を含む）を端末に取り込み、
 * 2回目からはネットを見ない。
 *
 * ■ 動画はここを通らない
 *
 * キャッシュするのはこのアプリ自身のファイルだけ。測る動画は
 * ブラウザの中で処理され、fetch そのものが発生しない。
 */

// 中身を直したらこの番号を上げる。上げ忘れると古いままが出る。
const VERSION = 'v7';
const CACHE = `synccheck-${VERSION}`;

// 相対パスにしておく。GitHub Pages ではサイトが
// /synccheck/ の下にぶら下がるため、絶対パスだと外れる。
const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon.svg',
  './src/audio.js',
  './src/export.js',
  './src/measure.js',
  './src/sync.js',
  './src/timeline.js',
  './src/lineup.js',
  './vendor/ffmpeg/index.js',
  './vendor/ffmpeg/classes.js',
  './vendor/ffmpeg/const.js',
  './vendor/ffmpeg/errors.js',
  './vendor/ffmpeg/types.js',
  './vendor/ffmpeg/utils.js',
  './vendor/ffmpeg/worker.js',
  './vendor/util/index.js',
  './vendor/util/const.js',
  './vendor/util/errors.js',
  './vendor/util/types.js',
  './vendor/core/ffmpeg-core.js',
  './vendor/core/ffmpeg-core.wasm',   // 約31MB。これが本体
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);

    // addAll は1つでも失敗すると全部捨てる。31MB の wasm が
    // 途中で切れただけで何も残らないのは困るので、1つずつ入れて
    // 失敗したものだけ諦める（次に開いたときに拾い直せる）。
    await Promise.all(ASSETS.map(async (url) => {
      try {
        const res = await fetch(url, { cache: 'reload' });
        if (res.ok) await cache.put(url, res);
      } catch (_) {
        /* 入らなかったものはネットワークから読む */
      }
    }));

    // 古い版を待たずに入れ替える。測定の途中で切り替わることは無い
    // （測っている間はページを開いたままなので）。
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names.filter((n) => n.startsWith('synccheck-') && n !== CACHE)
           .map((n) => caches.delete(n))
    );
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // GET 以外は素通し。テスト結果の POST（serve.py 宛）を
  // キャッシュが横取りしないようにする。
  if (req.method !== 'GET') return;

  // 別オリジンには手を出さない。
  if (new URL(req.url).origin !== self.location.origin) return;

  const url = new URL(req.url);
  const isWasm = url.pathname.endsWith('.wasm');

  event.respondWith((async () => {
    const cache = await caches.open(CACHE);

    // ■ ffmpeg 本体（31MB）はキャッシュ優先
    //
    // 中身が変わることはまず無いし、毎回 31MB を取りに行くと
    // 出先では即座に破綻する。VERSION を上げたときだけ入れ替わる。
    if (isWasm) {
      const hit = await cache.match(req, { ignoreSearch: true });
      if (hit) return hit;
    }

    // ■ それ以外はネット優先（手が届くなら必ず新しいものを使う）
    //
    // 2026-09-19: ここがキャッシュ優先だったせいで、符号バグを
    // 直して公開しても iPad に届かなかった。VERSION を上げても、
    // 古い Service Worker が自分の持っている古いファイルを
    // 返し続けるため、利用者側から直す手段が無い状態になる。
    //
    // 通信できるときは取りに行き、駄目ならキャッシュに落とす。
    // オフラインでの起動はこれまでどおり効く。
    try {
      // 3秒で見切る。出先の細い回線で待たされ続けないため。
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 3000);
      const res = await fetch(req, { signal: ctrl.signal });
      clearTimeout(timer);

      if (res.ok && res.type === 'basic') {
        cache.put(req, res.clone());
      }
      return res;
    } catch (err) {
      // 圏外・回線が細い・3秒で間に合わなかった
      const hit = await cache.match(req, { ignoreSearch: true });
      if (hit) return hit;

      if (req.mode === 'navigate') {
        const shell = await cache.match('./index.html');
        if (shell) return shell;
      }
      throw err;
    }
  })());
});

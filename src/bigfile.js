/**
 * 大きな動画ファイルを、メモリに丸ごと載せずに扱う
 *
 * ■ なぜ要るか
 *
 * ブラウザの `file.arrayBuffer()` はファイル全体をメモリに載せる。
 * ffmpeg.wasm は 32bit なので**アドレス空間の上限が 4GB**。
 * 仮想ファイルシステムにコピーも要るので、実質2倍要る。
 *
 * 実素材 `916質疑応答.mov`（4.2GB / 1時間45分）で、
 * ブラウザが次のエラーを返した（2026-09-20）:
 *
 *     The requested file could not be read, typically due to
 *     permission problems that have occurred after a reference
 *     to a file was acquired.
 *
 * 文面は「権限の問題」と言っているが、実態は**サイズ超過**。
 *
 * ■ どう解くか: WORKERFS でマウントする
 *
 * ffmpeg.wasm は `WORKERFS` をサポートしている。これは **Blob を
 * コピーせずにそのままファイルとして見せる**仕組みで、ffmpeg が
 * 必要な部分だけを読みに行く。4GB のファイルでもメモリに載らない。
 *
 * ■ 途中を切り貼りする方式は捨てた（失敗の記録）
 *
 * 最初は「先頭の一部 + 末尾の moov」をつないだ小さいファイルを
 * その場で作る方式にした。mp4 では動いたが、**mov で壊れた**。
 *
 *   mov（音声が pcm_s16le・無圧縮）は mdat の中で映像と音声が
 *   細かく交互に並ぶ。mdat のサイズ宣言だけ書き換えても、moov の
 *   索引は元の全長を指したままなので、ffmpeg が誤った位置から
 *   サンプルを拾う。
 *
 *   実測: 同じ 603.5秒 を抜いても
 *     フル読み   → 相関 +2.20秒（正解）
 *     切り貼り   → 相関 +398.40秒（でたらめ）
 *
 * 音は「抜けている」ように見えるので気づきにくい。
 * **中身が正しいかは相関で確かめないと分からない。**
 */

/** これを超えたら部分読みに切り替える（バイト） */
export const BIG_FILE_BYTES = 1.5 * 1024 * 1024 * 1024;

/**
 * ffmpeg に入力を用意する。
 *
 * 小さいファイルは今までどおりメモリに書く。
 * 大きいファイルは WORKERFS でマウントして、コピーを避ける。
 *
 * @returns {{path: string, cleanup: () => Promise<void>}}
 *   path: ffmpeg の -i に渡すパス
 */
export async function mountInput(ff, file, name) {
  if (file.size <= BIG_FILE_BYTES) {
    await ff.writeFile(name, new Uint8Array(await file.arrayBuffer()));
    return {
      path: name,
      cleanup: async () => {
        try { await ff.deleteFile(name); } catch { /* 消せなくても進む */ }
      },
    };
  }

  // WORKERFS は Blob をコピーせずに見せる。4GB でもメモリに載らない。
  const dir = `/m_${Date.now()}`;
  try { await ff.createDir(dir); } catch { /* すでにあるなら使う */ }
  await ff.mount('WORKERFS', { files: [file] }, dir);
  return {
    path: `${dir}/${file.name}`,
    cleanup: async () => {
      try { await ff.unmount(dir); } catch { /* 無視 */ }
      try { await ff.deleteDir(dir); } catch { /* 無視 */ }
    },
  };
}

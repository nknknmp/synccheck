# -*- coding: utf-8 -*-
r"""
SyncCheck をローカルで動かすための小さなサーバー

    python serve.py

■ なぜサーバーが必要か

index.html をダブルクリックで開くと file:// になり、
ES モジュール（import 文）がブラウザに拒否される。
中身は静的ファイルを返すだけで、動画を受け取る処理は**一切ない**。
動画はブラウザの中だけで処理される。

■ ネットに公開するときは不要

GitHub Pages などに置く場合、このファイルは使わない。
静的ファイルだけで動く。
"""

import http.server
import socketserver
import webbrowser
import os
import sys

PORT = 8770   # SemiCut(8000番台) と当たらない番号にしておく
ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):
        """
        テスト結果の受け取り口（開発用）。

        test/ 以下のチェックページが、ヘッドレスブラウザで動いたときに
        結果をここへ送る。--dump-dom では ffmpeg.wasm の読み込みを
        待ちきれないため。**動画は送られてこない**（テキストの結果だけ）。
        """
        if self.path != '/__test_result':
            self.send_error(404)
            return
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n).decode('utf-8', 'replace')
        with open(os.path.join(ROOT, 'test', '_last_result.txt'), 'w',
                  encoding='utf-8') as fp:
            fp.write(body)
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        # .wasm を毎回読み直すと遅いのでキャッシュを許す。
        # ただし自分で書いたファイルは毎回読ませる（直したのに古いままを防ぐ）。
        if self.path.endswith('.wasm'):
            self.send_header('Cache-Control', 'public, max-age=86400')
        else:
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        # 404 だけ出す。全部出すとうるさい。
        if args and len(args) > 1 and str(args[1]).startswith('4'):
            sys.stderr.write(f"  404 {args[0]}\n")


# .wasm と .mjs の種類を登録しておく（古い Python だと入っていない）
Handler.extensions_map['.wasm'] = 'application/wasm'
Handler.extensions_map['.mjs'] = 'text/javascript'
Handler.extensions_map['.js'] = 'text/javascript'


def main():
    if not os.path.isdir(os.path.join(ROOT, 'vendor', 'core')):
        print('！ vendor/core が見つかりません。')
        print('  ffmpeg.wasm が入っていないと動きません。')
        print('  使い方.txt の「vendor が無いとき」を見てください。')
        print()

    url = f'http://localhost:{PORT}/'
    socketserver.TCPServer.allow_reuse_address = True

    try:
        with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as httpd:
            print('════════════════════════════════════════')
            print(' SyncCheck')
            print('════════════════════════════════════════')
            print(f'  {url}')
            print()
            print('  終わるときは Ctrl+C')
            print()
            webbrowser.open(url)
            httpd.serve_forever()
    except OSError as e:
        print(f'！ ポート {PORT} が使えません: {e}')
        print('  すでに起動しているか、別のプログラムが使っています。')
        sys.exit(1)
    except KeyboardInterrupt:
        print('\n終わりました。')


if __name__ == '__main__':
    main()

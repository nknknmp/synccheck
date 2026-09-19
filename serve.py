# -*- coding: utf-8 -*-
r"""
SyncCheck をローカルで動かすための小さなサーバー

    python serve.py

■ なぜサーバーが必要か

index.html をダブルクリックで開くと file:// になり、
ES モジュール（import 文）がブラウザに拒否される。
中身は静的ファイルを返すだけで、動画を受け取る処理は**一切ない**。
動画はブラウザの中だけで処理される。

■ iPad など別の端末から開くとき

    python serve.py --lan

同じ Wi-Fi の中からだけ見えるようになる（0.0.0.0 で待ち受ける）。
既定で付けていないのは、このサーバーが SyncCheck フォルダの中身を
そのまま返すため。要らないときまで外に見せない。

■ ネットに公開するときは不要

GitHub Pages などに置く場合、このファイルは使わない。
静的ファイルだけで動く。
"""

import http.server
import socketserver
import webbrowser
import socket
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


def lan_ip():
    """
    この PC が LAN で名乗っている IPv4 を返す。

    ルーター宛に UDP ソケットを「繋いだふり」をして、OS がどの
    ネットワーク越しに出ていくつもりかを聞く。実際の通信は起きない。
    Hyper-V の仮想スイッチ（192.168.80.x など）を拾わないための方法。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def main():
    if not os.path.isdir(os.path.join(ROOT, 'vendor', 'core')):
        print('！ vendor/core が見つかりません。')
        print('  ffmpeg.wasm が入っていないと動きません。')
        print('  使い方.txt の「vendor が無いとき」を見てください。')
        print()

    lan = '--lan' in sys.argv
    host = '0.0.0.0' if lan else '127.0.0.1'
    url = f'http://localhost:{PORT}/'
    socketserver.TCPServer.allow_reuse_address = True

    try:
        with socketserver.TCPServer((host, PORT), Handler) as httpd:
            print('════════════════════════════════════════')
            print(' SyncCheck')
            print('════════════════════════════════════════')
            print(f'  このPC : {url}')
            if lan:
                ip = lan_ip()
                if ip:
                    print(f'  iPad   : http://{ip}:{PORT}/')
                else:
                    print('  iPad   : IP を特定できませんでした。')
                    print('           ipconfig で Wi-Fi の IPv4 を見てください。')
                print()
                print('  ※ 同じ Wi-Fi に繋がっている端末から見えます。')
                print('     初回は Windows の警告が出るので「プライベート」を許可。')
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

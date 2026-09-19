# -*- coding: utf-8 -*-
r"""
全ファイルを1本の軸に並べる計算の検算

    python test/lineup_test.py

src/lineup.js の「音で見つけた組をつないで位置を決める」部分と
同じ手順を Python で書いて確かめる。

音の測定そのものは sign_test.py / volume_test.py で見ているので、
ここは**つなぎ方**（島の扱い、1カメの扱い、位置の積み上げ）だけを見る。
測定結果は既知の値を差し込む。

■ 実素材から分かっている形（2026-09-19）

    Downloads\９１６烏口突起\ の6本を音で総当たりしたところ:

      実技1.mov ↔ 実技1.mp4   +68.19秒（窓 4/5 一致）
      実技1.mov ↔ 実技2.mp4  +418.14秒（窓 7/7 一致）★名前と中身が違う
      実技3.mov ↔ 実技3.mp4    +9.95秒（窓 2/2 一致）
      実技2.mov                どれとも重ならない（1カメだけの場面）

    → 島が2つ + 単独1本。この形を再現できることを見る。
"""

import sys

failed = 0
MIN_OVERLAP_SEC = 20
FPS = 30


def ok(cond, label, extra=''):
    global failed
    if cond:
        print('  ok   %s%s' % (label, (' ' + extra) if extra else ''))
    else:
        failed += 1
        print('  FAIL %s%s' % (label, (' ' + extra) if extra else ''))


def near(actual, expected, tol, label):
    ok(abs(actual - expected) <= tol, label,
       '(期待 %+.2f / 実際 %+.2f)' % (expected, actual))


def line_up(files, links):
    """
    files: [{'name','duration'}]（撮影時刻順に並んでいる前提）
    links: [(i, j, offsetSec)]  音で重なると確認できた組
    """
    n = len(files)
    # 重なりを計算して長い順に
    ls = []
    for (i, j, off) in links:
        ov = min(files[i]['duration'], off + files[j]['duration']) - max(0, off)
        if ov < MIN_OVERLAP_SEC:
            continue
        ls.append({'i': i, 'j': j, 'off': off, 'ov': ov})
    ls.sort(key=lambda x: -x['ov'])

    pos = [None] * n
    island = [-1] * n
    island_count = 0

    for L in ls:
        i, j, off = L['i'], L['j'], L['off']
        hi, hj = pos[i] is not None, pos[j] is not None
        if not hi and not hj:
            pos[i] = 0.0
            island[i] = island_count
            island_count += 1
            pos[j] = off
            island[j] = island[i]
        elif hi and hj:
            if island[i] != island[j]:
                frm, to = island[j], island[i]
                shift = (pos[i] + off) - pos[j]
                for k in range(n):
                    if island[k] == frm:
                        pos[k] += shift
                        island[k] = to
        elif hi:
            pos[j] = pos[i] + off
            island[j] = island[i]
        else:
            pos[i] = pos[j] - off
            island[i] = island[j]

    # 島を時間順に積む（フレーム単位で隣接させる）
    #
    # フレーム番号は0始まりなので、長さ N フレームのクリップは
    # 0〜N-1 を占め、次のクリップの先頭は N。+1 は要らない。
    # 長さは切り捨て（切り上げると存在しないフレームぶん進む）。
    def toF(sec):
        return int(round(sec * FPS))

    def durF(sec):
        return int(sec * FPS)          # 切り捨て

    ids = sorted({v for v in island if v >= 0},
                 key=lambda v: min(k for k in range(n) if island[k] == v))
    if len(ids) > 1:
        base_frame = 0
        for idv in ids:
            members = [k for k in range(n) if island[k] == idv]
            lo = min(pos[k] for k in members)
            shift = base_frame / FPS - lo
            for k in members:
                pos[k] += shift
            base_frame = max(toF(pos[k]) + durF(files[k]['duration'])
                             for k in members)

    # 1カメだけのものを後ろへ（同じく隣接）
    tail_frame = 0
    for k in range(n):
        if pos[k] is not None:
            tail_frame = max(tail_frame,
                             toF(pos[k]) + durF(files[k]['duration']))
    lonely = [k for k in range(n) if pos[k] is None]
    for k in lonely:
        pos[k] = tail_frame / FPS
        tail_frame += durF(files[k]['duration'])

    mn = min(pos)
    out = [{'name': files[k]['name'], 'startSec': pos[k] - mn,
            'measured': island[k] >= 0, 'alone': island[k] < 0}
           for k in range(n)]
    return sorted(out, key=lambda x: x['startSec'])


def mk(name, dur):
    return {'name': name, 'duration': dur}


print('=== 実素材と同じ形（島2つ + 単独1本）===')
files = [mk('1.mov', 847.4), mk('1.mp4', 342.3), mk('2.mp4', 421.3),
         mk('2.mov', 100.5), mk('3.mov', 181.8), mk('3.mp4', 162.6)]
links = [(0, 1, 68.19), (0, 2, 418.14), (4, 5, 9.95)]
res = line_up(files, links)
pos = {r['name']: r['startSec'] for r in res}
for r in res:
    print('  %-8s %8.2f秒  %s' % (r['name'], r['startSec'],
          '単独' if r['alone'] else '音で測定'))
print()
near(pos['1.mp4'] - pos['1.mov'], 68.19, 0.01, '1.mov ↔ 1.mp4 の差')
near(pos['2.mp4'] - pos['1.mov'], 418.14, 0.01, '1.mov ↔ 2.mp4 の差')
near(pos['3.mp4'] - pos['3.mov'], 9.95, 0.01, '3.mov ↔ 3.mp4 の差')
ok(pos['2.mov'] >= 0, '2.mov（1カメ）も軸に載る')
ok(min(pos.values()) == 0, 'いちばん早いものが 0')
ok(all(v >= 0 for v in pos.values()), '負の位置が無い')

print()
print('=== 島どうしが隙間なく隣接すること ===')
# 実素材の実測: k1.mov は 847.445秒 = 25423.35フレーム
#   → 占めるのは 0〜25422、次の開始は 25423
files2 = [mk('a.mov', 847.445), mk('b.mov', 100.0)]
res2 = line_up(files2, [])        # 重なりなし＝2本とも単独
pos2 = {r['name']: r['startSec'] for r in res2}
near(round(pos2['b.mov'] * 30), 25423, 0, 'b は a の次のフレームから',)
ok(round(pos2['a.mov'] * 30) == 0, 'a は 0 から')

print()
print('=== 島が2つに分かれること ===')
# 隙間なく隣接させるので「ちょうど終わりの位置」から始まる（> ではなく >=）
ok(pos['3.mov'] >= pos['1.mov'] + 847.4 - 0.05,
   '実技3 の島は実技1 の島の直後から始まる',
   '(3.mov=%.1f / 1.mov終わり=%.1f)' % (pos['3.mov'], pos['1.mov'] + 847.4))
ok(pos['3.mov'] < pos['1.mov'] + 847.4 + 1.0,
   '余計な隙間が空いていない（1秒以内）')

print()
print('=== 2本だけ（いちばん普通の使い方）===')
res = line_up([mk('A.mov', 660), mk('B.mp4', 659)], [(0, 1, -3.50)])
pos = {r['name']: r['startSec'] for r in res}
near(pos['B.mp4'], 0.0, 0.01, 'B が先なので 0')
near(pos['A.mov'], 3.50, 0.01, 'A は 3.50秒')
ok(res[0]['name'] == 'B.mp4', '早い順に並ぶ')

print()
print('=== 島どうしが後からつながる場合 ===')
# 先に (0,1) と (2,3) が別々の島になり、あとで (1,2) がつなぐ
files = [mk('a', 300), mk('b', 300), mk('c', 300), mk('d', 300)]
res = line_up(files, [(0, 1, 10.0), (2, 3, 10.0), (1, 2, 5.0)])
pos = {r['name']: r['startSec'] for r in res}
near(pos['b'] - pos['a'], 10.0, 0.01, 'a → b は 10秒')
near(pos['c'] - pos['b'], 5.0, 0.01, 'b → c は 5秒（島がつながった）')
near(pos['d'] - pos['c'], 10.0, 0.01, 'c → d は 10秒')
ok(len({r['name'] for r in res if r['alone']}) == 0, '全部つながって単独が無い')

print()
print('=== 重なりが足りない組は採らない ===')
res = line_up([mk('x', 100), mk('y', 100)], [(0, 1, 95.0)])   # 重なり5秒
ok(all(r['alone'] for r in res), '重なり5秒（20秒未満）は採用しない')

print()
print('━━━ すべて通った ━━━' if failed == 0 else '━━━ 失敗 %d 件 ━━━' % failed)
sys.exit(1 if failed else 0)

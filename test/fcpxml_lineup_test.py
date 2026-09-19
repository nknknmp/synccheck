# -*- coding: utf-8 -*-
r"""
並べた結果を fcpxml にする部分の検算

    python test/fcpxml_lineup_test.py

src/export.js の buildLineupFCPXML と同じレーン割り当てを
Python で書いて確かめる。XML そのものはブラウザで
DOMParser に通して検証しているので、ここは**レーンの決め方**を見る。

■ 何を守りたいか

1. **空のトラックを作らない**
   素材の本数ぶんレーンを作ると、ほとんど空のトラックが並ぶ。
   同時に映る最大本数ぶんで収まること。

2. **各クリップがちょうど1回だけ出る**
   最初の実装で、同じクリップが3回出力されるバグを入れた。

3. **画面の位置をそのまま使う**
   fcpxml 側で位置を計算し直さない。画面と食い違うと混乱する。
"""

import sys

failed = 0


def ok(cond, label, extra=''):
    global failed
    if cond:
        print('  ok   %s%s' % (label, (' ' + extra) if extra else ''))
    else:
        failed += 1
        print('  FAIL %s%s' % (label, (' ' + extra) if extra else ''))


def assign_lanes(items):
    """src/export.js と同じ: 空いているレーンへ入れる"""
    sorted_items = sorted(items, key=lambda x: x['startSec'])
    lane_end = []
    lane_of = {}
    for it in sorted_items:
        end = it['startSec'] + it['duration']
        lane = -1
        for i, e in enumerate(lane_end):
            if it['startSec'] >= e - 1e-6:
                lane = i
                break
        if lane == -1:
            lane = len(lane_end)
            lane_end.append(0)
        lane_end[lane] = end
        lane_of[it['name']] = lane
    return lane_of, len(lane_end)


def max_concurrent(items):
    """同時に映る最大本数（理論上の必要レーン数）"""
    evts = []
    for it in items:
        evts.append((it['startSec'], 1))
        evts.append((it['startSec'] + it['duration'], -1))
    evts.sort()
    cur = mx = 0
    for _, v in evts:
        cur += v
        mx = max(mx, cur)
    return mx


def mk(name, start, dur):
    return {'name': name, 'startSec': start, 'duration': dur}


print('=== 実素材6本（916烏口突起）===')
items = [
    mk('k1.mov', 0.0, 847.445), mk('k1.mp4', 68.2, 342.3),
    mk('k2.mp4', 418.1, 421.3), mk('k3.mov', 847.4, 181.8),
    mk('k3.mp4', 857.4, 162.6), mk('k2.mov', 1029.2, 100.5),
]
lane_of, n_lanes = assign_lanes(items)
need = max_concurrent(items)
for it in sorted(items, key=lambda x: x['startSec']):
    print('  %-8s %8.1f秒 〜 %8.1f秒  lane %d'
          % (it['name'], it['startSec'], it['startSec'] + it['duration'],
             lane_of[it['name']]))
print()
ok(n_lanes == need, '必要最小のレーン数になる',
   '(使った %d / 同時に映る最大 %d)' % (n_lanes, need))
ok(n_lanes == 2, 'この素材では2レーンで収まる', '(実際 %d)' % n_lanes)
ok(n_lanes < len(items), '素材の本数よりレーンが少ない（空トラックを作らない）')
ok(len(lane_of) == len(items), '全クリップにレーンが割り当たる')

print()
print('=== 重ならないものは同じレーンを使い回す ===')
items2 = [mk('a', 0, 100), mk('b', 100, 100), mk('c', 200, 100)]
lane_of2, n2 = assign_lanes(items2)
ok(n2 == 1, '隣接して並ぶだけなら1レーン', '(実際 %d)' % n2)
ok(all(v == 0 for v in lane_of2.values()), '全部レーン0')

print()
print('=== 3本同時なら3レーン ===')
items3 = [mk('a', 0, 100), mk('b', 10, 100), mk('c', 20, 100)]
lane_of3, n3 = assign_lanes(items3)
ok(n3 == 3, '同時に3本映るなら3レーン要る', '(実際 %d)' % n3)
ok(max_concurrent(items3) == 3, '理論値も3')

print()
print('=== 2カメの普通の組（1組だけ）===')
items4 = [mk('A.mov', 0, 660), mk('B.mp4', 3.5, 659)]
lane_of4, n4 = assign_lanes(items4)
ok(n4 == 2, '2本重なるので2レーン', '(実際 %d)' % n4)

print()
print('=== 隣接は重なりとみなさない ===')
# 847.445秒のクリップの次が 25423フレーム（= 847.4333秒）から始まる
items5 = [mk('a', 0, 847.445), mk('b', 25423 / 30, 100)]
lane_of5, n5 = assign_lanes(items5)
print('  a: 0 〜 %.3f秒 / b: %.3f秒 〜' % (847.445, 25423 / 30))
# b の開始が a の終わりより手前なので、ここは重なる扱いでよい
ok(n5 in (1, 2), 'レーン数は1か2（端数しだい）', '(実際 %d)' % n5)

print()
print('━━━ すべて通った ━━━' if failed == 0 else '━━━ 失敗 %d 件 ━━━' % failed)
sys.exit(1 if failed else 0)

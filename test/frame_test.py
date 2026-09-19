# -*- coding: utf-8 -*-
r"""
秒 → フレーム換算の検算

    python test/frame_test.py

src/export.js の realFps / toFrames / frameRemainderSec と同じ式を
Python で書いて確かめる。

■ 29.97 を分数で持っている理由

29.97 や 23.98 は表示用に丸めた値で、本当の値は 30000/1001
（= 29.9700299...）や 24000/1001。

ただし**実際に差が出るのは約 20000秒（5時間半）を超えてから**で、
同期のズレは普通 数秒なので、この差が現場で効くことはまず無い
（2026-09-19 に実測して確かめた）。

それでも分数で持つのは、この関数が秒→フレームの一般的な換算として
他の用途にも使われうるため。害が無く、正しいほうを選んでおく。
"""

import math
import sys

failed = 0


def real_fps(fps):
    if abs(fps - 29.97) < 0.01:
        return 30000 / 1001
    if abs(fps - 23.98) < 0.02:
        return 24000 / 1001
    if abs(fps - 59.94) < 0.01:
        return 60000 / 1001
    return fps


def to_frames(sec, fps):
    # JS の Math.round は .5 を上へ（-0.5 は 0 へ）。Python の round は
    # 偶数丸めなので合わせる。
    v = sec * real_fps(fps)
    return math.floor(v + 0.5)


def remainder_sec(sec, fps):
    r = real_fps(fps)
    return sec - to_frames(sec, fps) / r


def ok(cond, label, extra=''):
    global failed
    if cond:
        print('  ok   %s%s' % (label, (' ' + extra) if extra else ''))
    else:
        failed += 1
        print('  FAIL %s%s' % (label, (' ' + extra) if extra else ''))


def eq(actual, expected, label):
    ok(actual == expected, label, '(期待 %s / 実際 %s)' % (expected, actual))


print('=== 基本の換算 ===')
eq(to_frames(1.0, 30), 30, '30fps で 1秒 = 30フレーム')
eq(to_frames(-3.50, 30), -105, '30fps で -3.50秒 = -105フレーム（実素材の値）')
eq(to_frames(0.0, 30), 0, 'ズレなしは 0フレーム')
eq(to_frames(2.0, 60), 120, '60fps で 2秒 = 120フレーム')
eq(to_frames(1.0, 25), 25, '25fps で 1秒 = 25フレーム')

print()
print('=== 29.97 は 30000/1001 で計算する ===')
eq(to_frames(3600.0, 29.97), 107892, '1時間 = 107892フレーム')
eq(to_frames(1.0, 29.97), 30, '29.97fps で 1秒 = 30フレーム')

# 実測: 分数と素朴な掛け算で答えが割れるのは約20000秒から。
# 同期のズレは数秒なので現場では差が出ないが、式としては分数が正しい。
eq(to_frames(20000.0, 29.97), 599401, '20000秒では分数のほうが1多い')
ok(to_frames(20000.0, 29.97) != math.floor(20000.0 * 29.97 + 0.5),
   'そこでは素朴な掛け算と食い違う',
   '(分数 %d / 素朴 %d)'
   % (to_frames(20000.0, 29.97), math.floor(20000.0 * 29.97 + 0.5)))
ok(to_frames(10.0, 29.97) == math.floor(10.0 * 29.97 + 0.5),
   '数秒〜数十秒の範囲では差が出ない（実用上は同じ）')

print()
print('=== 23.98 / 59.94 ===')
eq(to_frames(1.0, 23.98), 24, '23.98fps で 1秒 = 24フレーム')
eq(to_frames(1.0, 59.94), 60, '59.94fps で 1秒 = 60フレーム')

print()
print('=== 符号を保つこと（前へ / 後ろへ を間違えない）===')
ok(to_frames(-3.50, 30) < 0, '負の秒は負のフレーム')
ok(to_frames(+3.50, 30) > 0, '正の秒は正のフレーム')
eq(to_frames(-3.50, 30), -to_frames(3.50, 30), '符号だけが反転する')

print()
print('=== 丸めの端数 ===')
# 30fps なら1フレーム = 0.0333秒。端数は最大その半分
r = remainder_sec(3.51, 30)
ok(abs(r) <= 1 / 30 / 2 + 1e-9,
   '端数は半フレーム以内', '(%.4f秒)' % r)
ok(abs(remainder_sec(1.0, 30)) < 1e-9, 'ちょうど割り切れるなら端数なし')

# 実素材の値で、端数がどれだけ出るか
for sec in (-3.50, -3.48, 2.017):
    fr = to_frames(sec, 30)
    rem = remainder_sec(sec, 30)
    print('    %+.3f秒 → %+d フレーム（端数 %+.1f ミリ秒）'
          % (sec, fr, rem * 1000))

print()
print('═' * 56)
print(' 失敗: %d 件' % failed if failed else ' すべて通った')
print('═' * 56)
sys.exit(1 if failed else 0)

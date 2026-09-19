# -*- coding: utf-8 -*-
r"""
全ファイルを1本の軸に並べる計算の検算

    python test/lineup_test.py

src/lineup.js の lineUp() と同じ手順を Python で書いて確かめる。
音の測定そのものは sign_test.py / volume_test.py で見ているので、
ここは**位置の組み立て**（誰を基準にどう足すか）だけを見る。

測定値は既知の値を差し込む（実際に ffmpeg は回さない）。
"""

import sys

failed = 0
MIN_OVERLAP_SEC = 10


def ok(cond, label, extra=''):
    global failed
    if cond:
        print('  ok   %s%s' % (label, (' ' + extra) if extra else ''))
    else:
        failed += 1
        print('  FAIL %s%s' % (label, (' ' + extra) if extra else ''))


def near(actual, expected, tol, label):
    d = abs(actual - expected)
    ok(d <= tol, label, '(期待 %+.2f / 実際 %+.2f)' % (expected, actual))


def guess_starts(files):
    """
    撮影時刻から推定開始位置を出す。

    埋め込み時刻が「録画開始」か「録画終了」か分からないので、
    両方の案を試して**全体の重なりが最大**になる組み合わせを選ぶ。
    """
    with_time = [f for f in files if f.get('creationMs')]
    if not with_time:
        return [0] * len(files)

    cands = []
    for f in files:
        if not f.get('creationMs'):
            cands.append([0])
        else:
            dur_ms = f.get('duration', 0) * 1000
            cands.append([f['creationMs'], f['creationMs'] - dur_ms])

    idx = [0] * len(files)

    def starts():
        return [cands[i][idx[i]] for i in range(len(files))]

    def total():
        st = starts()
        s = 0
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                di = files[i].get('duration', 0) * 1000
                dj = files[j].get('duration', 0) * 1000
                s += max(0, min(st[i] + di, st[j] + dj) - max(st[i], st[j]))
        return s

    for _ in range(4):
        changed = False
        for i in range(len(files)):
            if len(cands[i]) < 2:
                continue
            before = total()
            idx[i] = 1 - idx[i]
            if total() <= before:
                idx[i] = 1 - idx[i]
            else:
                changed = True
        if not changed:
            break

    st = starts()
    base = min(st[i] for i in range(len(files)) if files[i].get('creationMs'))
    return [((st[i] - base) / 1000 if files[i].get('creationMs') else 0)
            for i in range(len(files))]


def overlap_of(a_start, a_dur, b_start, b_dur):
    start = max(a_start, b_start)
    end = min(a_start + a_dur, b_start + b_dur)
    ov = end - start
    if ov <= 0:
        return None
    return {'overlapSec': ov, 'aOffsetSec': start - a_start,
            'bOffsetSec': start - b_start}


def line_up(files, measured):
    """measured[(a_name,b_name)] = 音で測った差（b の遅れ）"""
    guess = guess_starts(files)
    order = sorted(
        [{'f': f, 'guessStart': g, 'dur': f['duration']}
         for f, g in zip(files, guess)],
        key=lambda x: x['guessStart'])

    placed = [{'name': order[0]['f']['name'], 'startSec': 0.0,
               'duration': order[0]['dur'], 'measured': False,
               '_ref': order[0]}]

    for cur in order[1:]:
        best = None
        for p in placed:
            gap = cur['guessStart'] - p['_ref']['guessStart']
            ov = overlap_of(p['startSec'], p['duration'],
                            p['startSec'] + gap, cur['dur'])
            if not ov:
                continue
            if best is None or ov['overlapSec'] > best['ov']['overlapSec']:
                best = {'p': p, 'ov': ov, 'gap': gap}

        if best is None or best['ov']['overlapSec'] < MIN_OVERLAP_SEC:
            fb = placed[0]['startSec'] + (cur['guessStart']
                                          - placed[0]['_ref']['guessStart'])
            placed.append({'name': cur['f']['name'], 'startSec': fb,
                           'duration': cur['dur'], 'measured': False,
                           '_ref': cur})
            continue

        key = (best['p']['name'], cur['f']['name'])
        m = measured.get(key, 0.0)
        placed.append({'name': cur['f']['name'],
                       'startSec': best['p']['startSec'] + best['gap'] + m,
                       'duration': cur['dur'], 'measured': True, '_ref': cur})

    mn = min(p['startSec'] for p in placed)
    out = [{'name': p['name'], 'startSec': p['startSec'] - mn,
            'duration': p['duration'], 'measured': p['measured']}
           for p in placed]
    return sorted(out, key=lambda x: x['startSec'])


def mk(name, creation_ms, dur):
    return {'name': name, 'creationMs': creation_ms, 'duration': dur}


T0 = 1_757_000_000_000   # 適当な基準ミリ秒

print('=== 実素材の2本（916まとめ）===')
print('mov: 撮影時刻 08:32:36 / 661.3秒  ← 録画開始を記録')
print('mp4: 撮影時刻 08:43:37 / 659.3秒  ← 録画終了を記録（11分1秒ずれる）')
print('音で測った差は -5.18秒、正しい置き場所の差は 3.50秒')
print()

mov = mk('916まとめ.mov', T0, 661.3)
mp4 = mk('916まとめ.mp4', T0 + 661_000, 659.3)   # 11分1秒後を記録

g = guess_starts([mov, mp4])
ov = min(g[0] + 661.3, g[1] + 659.3) - max(g[0], g[1])
print('  推定開始: mov %.1f秒 / mp4 %.1f秒' % (g[0], g[1]))
print('  重なり  : %.1f秒' % ov)
ok(ov >= MIN_OVERLAP_SEC,
   '重なっていると判定される（素直に並べると 0.3秒 で切り捨てられていた）',
   '(%.1f秒)' % ov)
near(g[1] - g[0], 1.7, 0.1, 'mp4 の時刻を「録画終了」と解釈して 1.7秒差になる')

print()
print('=== 撮影時刻が正しい素材で、音の補正が効くか ===')
# A が 0秒、B が 2秒後に始まった（撮影時刻もそう言っている）
a = mk('A.mp4', T0, 600.0)
b = mk('B.mp4', T0 + 2000, 600.0)
# 音で測ったら、実は 0.5秒 余分に遅れていた
res = line_up([a, b], {('A.mp4', 'B.mp4'): 0.5})
pos = {r['name']: r['startSec'] for r in res}
near(pos['A.mp4'], 0.0, 0.001, 'A は 0')
near(pos['B.mp4'], 2.5, 0.001, 'B は 2.0 + 0.5 = 2.5')

print()
print('=== 音の補正で順番が入れ替わる場合 ===')
# 撮影時刻では B が 1秒後。でも音で測ると 3秒 前だった
a = mk('A.mp4', T0, 600.0)
b = mk('B.mp4', T0 + 1000, 600.0)
res = line_up([a, b], {('A.mp4', 'B.mp4'): -3.0})
pos = {r['name']: r['startSec'] for r in res}
near(pos['B.mp4'], 0.0, 0.001, 'B が先になり 0 になる')
near(pos['A.mp4'], 2.0, 0.001, 'A は 2.0（= -(1-3)）')
ok(res[0]['name'] == 'B.mp4', '早い順に並んでいる')

print()
print('=== 4本 ===')
print('※ 相手は「すでに置いた中でいちばん重なりが長いもの」を選ぶ。')
print('  C3 は C1（重なり290秒）ではなく C2（295秒）と測る。')
print('  重なりが長いほど答えが安定するため、これが狙いどおり。')
files = [mk('C1.mp4', T0, 300.0), mk('C2.mp4', T0 + 5000, 300.0),
         mk('C3.mp4', T0 + 10000, 300.0), mk('C4.mp4', T0 + 15000, 300.0)]
# 直前のものと測られるので、測定値も「直前からの差」で与える。
# 各段で 0.2 ずつ補正が積み上がり、5.2 / 10.4 / 15.6 になる。
measured = {('C1.mp4', 'C2.mp4'): 0.2, ('C2.mp4', 'C3.mp4'): 0.2,
            ('C3.mp4', 'C4.mp4'): 0.2}
res = line_up(files, measured)
pos = {r['name']: r['startSec'] for r in res}
near(pos['C1.mp4'], 0.0, 0.001, 'C1 は 0')
near(pos['C2.mp4'], 5.2, 0.001, 'C2 は 5.0 + 0.2')
near(pos['C3.mp4'], 10.4, 0.001, 'C3 = C2(5.2) + 推定差5.0 + 測定0.2')
near(pos['C4.mp4'], 15.6, 0.001, 'C4 = C3(10.4) + 推定差5.0 + 測定0.2')
ok([r['name'] for r in res] == ['C1.mp4', 'C2.mp4', 'C3.mp4', 'C4.mp4'],
   '4本が早い順に並ぶ')

# どの相手と測ったかが結果を変えるので、そこを直接確かめる
print()
print('  -- 相手選びの確認 --')
ok(overlap_of(0.0, 300.0, 10.0, 300.0)['overlapSec'] == 290.0,
   'C1 と C3 の重なりは 290秒')
ok(overlap_of(5.2, 300.0, 10.2, 300.0)['overlapSec'] == 295.0,
   'C2 と C3 の重なりは 295秒（こちらが選ばれる）')

print()
print('=== 6本でも同じ形で並ぶ ===')
files = [mk('D%d.mp4' % i, T0 + i * 4000, 300.0) for i in range(6)]
measured = {('D0.mp4', 'D%d.mp4' % i): i * 0.1 for i in range(1, 6)}
res = line_up(files, measured)
ok(len(res) == 6, '6本すべて並ぶ')
near(res[0]['startSec'], 0.0, 0.001, '先頭は必ず 0')
ok(all(res[i]['startSec'] <= res[i + 1]['startSec'] for i in range(5)),
   '早い順に並んでいる')
ok(all(r['startSec'] >= 0 for r in res), '負の位置が無い')

print()
print('=== 重ならない1本が混ざっても落ちない ===')
files = [mk('E1.mp4', T0, 100.0), mk('E2.mp4', T0 + 1000, 100.0),
         mk('E3.mp4', T0 + 9_000_000, 100.0)]   # 2時間半後・重ならない
res = line_up(files, {('E1.mp4', 'E2.mp4'): 0.3})
ok(len(res) == 3, '3本とも結果に出る')
ok(any(not r['measured'] for r in res), '測れなかったものが記録される')

print()
print('━━━ すべて通った ━━━' if failed == 0
      else '━━━ 失敗 %d 件 ━━━' % failed)
sys.exit(1 if failed else 0)

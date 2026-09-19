# -*- coding: utf-8 -*-
r"""
符号だけを検算する（実素材ベース）

    python test/sign_test.py

■ なぜ別のテストにしたか

2026-09-19 まで cross_correlate の符号が逆だったのに、
sync_test.py の27件はすべて通っていた。

理由は、テストが自分で作った素材を使っていたから:

    delay_envelope(a, +D) は「D秒 遅れて始まった b」を作る
    → 合わせるには b を前へ動かす。正しい期待値は -D
    → なのに期待値を +D と書いていた

つまり「素材の作り方」と「期待値」の両方が同じ向きに間違っていて、
打ち消し合っていた。同じ思い違いで書いた2つを突き合わせても、
誤りは見つからない。

このテストは**1本の実ファイルから既知の秒数だけずらして切り出す**。
真値は ffmpeg の -ss が決めるので、こちらの思い込みが入らない。

■ 素材

test/fixtures/A_noise.mp4（ピンクノイズ・反復しない）を使う。
反復する音だと、ずらした先で偶然合ってしまい検算にならない。

■ ffmpeg が無い環境では飛ばす（失敗にはしない）
"""

import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'fixtures', 'A_noise.mp4')
RATE = 8000
ENV_RATE = 100
MIN_OVERLAP_RATIO = 0.5

failed = 0


def normalize(arr):
    n = len(arr)
    if n == 0:
        return []
    mean = sum(arr) / n
    var = sum((x - mean) ** 2 for x in arr) / n
    sd = math.sqrt(var)
    if sd == 0:
        return [0.0] * n
    return [(x - mean) / sd for x in arr]


def build_envelope(pcm, sample_rate, env_rate=ENV_RATE):
    """アプリ（src/sync.js）と同じ作り方で音量の線にする"""
    step = sample_rate // env_rate
    out = []
    for i in range(0, len(pcm) - step + 1, step):
        s = 0.0
        for j in range(i, i + step):
            s += pcm[j] * pcm[j]
        out.append(math.sqrt(s / step))
    return out


def cross_correlate(a, b, sample_rate, max_lag_sec=30):
    """src/sync.js の crossCorrelate と同じ（符号も同じ）"""
    max_lag = min(int(max_lag_sec * sample_rate), max(len(a), len(b)) - 1)
    na, nb = normalize(a), normalize(b)
    shorter = min(len(na), len(nb))
    min_overlap = max(sample_rate, int(shorter * MIN_OVERLAP_RATIO))

    best_lag, best_score = 0, -math.inf
    for lag in range(-max_lag, max_lag + 1):
        start = max(0, -lag)
        end = min(len(na), len(nb) - lag)
        count = end - start
        if count < min_overlap:
            continue
        s = 0.0
        for i in range(start, end):
            s += na[i] * nb[i + lag]
        score = s / count
        if score > best_score:
            best_score, best_lag = score, lag

    if best_score == -math.inf:
        return {'offsetSec': 0, 'score': -math.inf, 'tooShort': True}
    # b の先行量 → 「b の遅れ」にするため反転
    return {'offsetSec': -best_lag / sample_rate, 'score': best_score}


def near(actual, expected, tol, label):
    global failed
    d = abs(actual - expected)
    if d > tol or math.isnan(d):
        failed += 1
        print('  FAIL %s  (期待 %+.2f / 実際 %+.3f  差 %.3f)'
              % (label, expected, actual, d))
    else:
        print('  ok   %s  (%+.3f)' % (label, actual))


def extract(path, start_sec, len_sec):
    """ffmpeg で 8kHz モノラルの生 PCM を取り出す（アプリと同じ条件）"""
    cmd = ['ffmpeg', '-v', 'error', '-y', '-ss', str(start_sec),
           '-i', path, '-t', str(len_sec),
           '-vn', '-ac', '1', '-ar', str(RATE), '-f', 's16le', '-']
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    pcm = []
    for i in range(0, len(out) - 1, 2):
        v = out[i] | (out[i + 1] << 8)
        if v >= 32768:
            v -= 65536
        pcm.append(v / 32768.0)
    return pcm


def main():
    if not os.path.exists(SRC):
        print('！ 素材が無い:', SRC)
        return 0
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print('ffmpeg が PATH にないので飛ばす。')
        return 0

    print('=== 符号の検算（実素材から既知のズレを作る）===')
    print()
    print('同じ1本から2か所を切り出す。B の切り出し位置が A より後ろなら、')
    print('B の中身は先に進んでいる（B が先行）。合わせるには B を後ろへ')
    print('送るので、答えは正。')
    print()

    # (A の開始, B の開始, 説明)
    cases = [
        (10.0, 13.0, 'B が 3秒 先行'),
        (10.0, 10.0, 'ズレなし'),
        (13.0, 10.0, 'B が 3秒 遅れ'),
        (5.0, 6.5, 'B が 1.5秒 先行'),
    ]
    for a_start, b_start, label in cases:
        env_a = build_envelope(extract(SRC, a_start, 40), RATE)
        env_b = build_envelope(extract(SRC, b_start, 40), RATE)
        r = cross_correlate(env_a, env_b, ENV_RATE, 10)
        near(r['offsetSec'], b_start - a_start, 0.05, label)

    print()
    print('※ ここが落ちたら src/sync.js の crossCorrelate の符号を疑うこと。')
    print('  返すのは「B をずらすべき秒数」。B が先行なら正。')
    return failed


if __name__ == '__main__':
    n = main()
    print()
    print('━━━ 符号は正しい ━━━' if n == 0 else '━━━ 符号がおかしい（%d件）━━━' % n)
    sys.exit(1 if n else 0)

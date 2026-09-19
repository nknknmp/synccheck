# -*- coding: utf-8 -*-
r"""
音量やマイク位置が違っても答えが変わらないことの検算

    python test/volume_test.py

■ なぜこのテストが要るか

「カメラを置く位置が違うから、A ではかすかに聞こえる声が B では
大きく聞こえる。それで測定がずれるのでは」という当然の疑問がある。

答えは「ずれない」。相関を取る前に normalize() で平均を引いて
標準偏差で割るので、**音量の絶対値は計算から消える**。残るのは
「いつ大きくなって、いつ小さくなったか」という変化の形だけ。

実素材（916まとめ）でも、2本の平均音量は 10.2dB（振幅で約3.2倍）
違っていたが、正しい答えが出ていた。

この性質を壊す変更が入ったら気づけるよう、テストに残す。

■ やり方

1本の実ファイルから 100秒目と 103秒目を切り出す（真値は必ず +3.00秒）。
相手側に ffmpeg で加工をかけ、それでも +3.00秒 が出るか見る:

  - 音量 1/10 / 4倍
  - こもり（lowpass）+ 残響（aecho）… 遠いマイクの模擬
  - 上記 + ピンクノイズ

ffmpeg が無い環境では飛ばす。
"""

import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'fixtures', 'A_noise.mp4')
RATE = 8000
ENV_RATE = 100
BASE_AT = 2.0      # 基準の切り出し位置（秒）
OTHER_AT = 5.0     # 相手の切り出し位置 → 正解は +3.00秒
LEN = 30
TRUE = OTHER_AT - BASE_AT

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
    step = sample_rate // env_rate
    out = []
    for i in range(0, len(pcm) - step + 1, step):
        s = 0.0
        for j in range(i, i + step):
            s += pcm[j] * pcm[j]
        out.append(math.sqrt(s / step))
    return out


def cross_correlate(a, b, sample_rate, max_lag_sec=10):
    max_lag = min(int(max_lag_sec * sample_rate), max(len(a), len(b)) - 1)
    na, nb = normalize(a), normalize(b)
    shorter = min(len(na), len(nb))
    min_overlap = max(sample_rate, int(shorter * 0.5))
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
        return 0.0, -math.inf
    return -best_lag / sample_rate, best_score


def extract(start_sec, len_sec, afilter=None):
    cmd = ['ffmpeg', '-v', 'error', '-y', '-ss', str(start_sec),
           '-i', SRC, '-t', str(len_sec), '-vn', '-ac', '1',
           '-ar', str(RATE)]
    if afilter:
        cmd += ['-af', afilter]
    cmd += ['-f', 's16le', '-']
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    pcm = []
    for i in range(0, len(out) - 1, 2):
        v = out[i] | (out[i + 1] << 8)
        if v >= 32768:
            v -= 65536
        pcm.append(v / 32768.0)
    return pcm


def check(label, afilter):
    global failed
    env_b = build_envelope(extract(OTHER_AT, LEN, afilter), RATE)
    lag, score = cross_correlate(base_env, env_b, ENV_RATE)
    if abs(lag - TRUE) <= 0.05:
        print('  ok   %-34s %+.2f秒  (スコア %.3f)' % (label, lag, score))
    else:
        failed += 1
        print('  FAIL %-34s %+.2f秒  (期待 %+.2f / スコア %.3f)'
              % (label, lag, TRUE, score))


if __name__ == '__main__':
    if not os.path.exists(SRC):
        print('！ 素材が無い:', SRC)
        sys.exit(0)
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        print('ffmpeg が PATH にないので飛ばす。')
        sys.exit(0)

    print('=== 音量・マイク位置が違っても答えが変わらないこと ===')
    print()
    print('基準 %.0f秒目 / 相手 %.0f秒目 → 正解は必ず %+.2f秒'
          % (BASE_AT, OTHER_AT, TRUE))
    print()

    base_env = build_envelope(extract(BASE_AT, LEN), RATE)

    check('加工なし（参考）', None)
    check('音量 1/10 (-20dB)', 'volume=0.1')
    check('音量 4倍 (+12dB)', 'volume=4.0')
    check('こもり（高音を落とす）', 'lowpass=f=1800')
    check('遠いマイク: こもり+残響+小音量',
          'lowpass=f=1800,aecho=0.8:0.9:60:0.4,volume=0.15')
    check('さらに遠い: 強い残響+音量10%',
          'lowpass=f=1500,aecho=0.8:0.9:80:0.5,volume=0.1')

    print()
    print('※ スコアは下がってよい。答えが変わらないことが大事。')
    print('  絶対音量は normalize() で消え、変化のタイミングだけが残る。')
    print()
    print('━━━ 音量差に強い ━━━' if failed == 0
          else '━━━ 音量差でずれた（%d件）━━━' % failed)
    sys.exit(1 if failed else 0)

# -*- coding: utf-8 -*-
r"""
同期計算の検算（Node.js が無い環境用）

src/sync.js と src/timeline.js のアルゴリズムを Python に写して、
答えが分かっている合成波形で確かめる。

    python test\sync_test.py

■ これは何を保証するか

「符号の向き」「多数決のふるまい」「組の見つけ方」が意図どおりであること。
JS 側と Python 側は別の実装なので、**両方書き間違えていれば気付けない**。
JS そのものを動かす検算は test/sync.test.mjs にある（Node.js が必要）。

■ これは何を保証しないか

実素材で正しい値が出ること。合成波形はきれいすぎるので、
実際の録音で起きる問題（無音区間、音量の偏り、別の部屋の音）は再現していない。
実素材での確認は「使い方.txt」の手順で行うこと。
"""

import math
import sys

# ---------------------------------------------------------------------------
# src/sync.js の写し
# ---------------------------------------------------------------------------

def normalize(arr):
    n = len(arr)
    if n == 0:
        return []
    mean = sum(arr) / n
    var = sum((v - mean) ** 2 for v in arr) / n
    sd = math.sqrt(var) or 1e-9
    return [(v - mean) / sd for v in arr]


def build_envelope(pcm, sample_rate, env_rate=100):
    win = max(1, sample_rate // env_rate)
    n = len(pcm) // win
    env = []
    for i in range(n):
        base = i * win
        s = sum(pcm[base + j] ** 2 for j in range(win))
        env.append(math.sqrt(s / win))
    return env


MIN_OVERLAP_RATIO = 0.5


def cross_correlate(a, b, sample_rate, max_lag_sec=30,
                    min_overlap_ratio=MIN_OVERLAP_RATIO):
    max_lag = min(int(max_lag_sec * sample_rate), max(len(a), len(b)) - 1)
    na, nb = normalize(a), normalize(b)

    # 重なりが短い lag は見ない。重なり長で割っても、数秒まで減ると
    # 偶然そこだけ形が合って高スコアが出る（実測で必要だった）。
    shorter = min(len(na), len(nb))
    min_overlap = max(sample_rate, int(shorter * min_overlap_ratio))

    best_lag, best_score = 0, -math.inf
    for lag in range(-max_lag, max_lag + 1):
        # b が lag だけ遅れているとき b[i+lag] = a[i]
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
        return {"offsetSec": 0, "score": -math.inf, "tooShort": True}

    return {"offsetSec": best_lag / sample_rate, "score": best_score}


MIN_WINDOW_SEC = 15


def verify_sync(env_a, env_b, env_rate, windows=5, max_lag_sec=30,
                min_window_sec=MIN_WINDOW_SEC):
    win_len = min(len(env_a), len(env_b)) // windows
    points = []

    if win_len < env_rate * min_window_sec:
        g = cross_correlate(env_a, env_b, env_rate, max_lag_sec)
        return {"offsetSec": g["offsetSec"], "score": g["score"], "drift": False,
                "points": [], "maxDeviationSec": 0, "lowConfidence": False,
                "singleWindow": True}

    for i in range(windows):
        start = i * win_len
        a = env_a[start:start + win_len]
        b = env_b[start:start + win_len]
        if len(a) < env_rate or len(b) < env_rate:
            continue
        r = cross_correlate(a, b, env_rate, max_lag_sec)
        if r.get("tooShort"):
            continue
        points.append({"atSec": start / env_rate,
                       "offsetSec": r["offsetSec"], "score": r["score"]})

    if not points:
        g = cross_correlate(env_a, env_b, env_rate, max_lag_sec)
        return {"offsetSec": g["offsetSec"], "score": g["score"], "drift": False,
                "points": [], "maxDeviationSec": 0, "lowConfidence": False,
                "singleWindow": True}

    TOL = 0.5
    best = {"offset": points[0]["offsetSec"], "members": []}
    for cand in points:
        members = [p for p in points
                   if abs(p["offsetSec"] - cand["offsetSec"]) <= TOL]
        ssum = lambda arr: sum(p["score"] for p in arr)
        if (len(members) > len(best["members"]) or
                (len(members) == len(best["members"]) and
                 ssum(members) > ssum(best["members"]))):
            best = {"offset": cand["offsetSec"], "members": members}

    offsets = sorted(p["offsetSec"] for p in best["members"])
    median = offsets[len(offsets) // 2]

    max_dev = max(abs(p["offsetSec"] - median) for p in best["members"])
    mean_score = sum(p["score"] for p in best["members"]) / len(best["members"])

    consensus = len(best["members"]) / len(points)
    if consensus < 0.5:
        return {"offsetSec": median, "score": mean_score, "drift": True,
                "points": points,
                "maxDeviationSec": max(abs(p["offsetSec"] - median) for p in points),
                "lowConfidence": True, "singleWindow": False}

    return {"offsetSec": median, "score": mean_score,
            "drift": max_dev > 0.5, "points": points,
            "maxDeviationSec": max_dev, "lowConfidence": False,
            "singleWindow": False}


# ---------------------------------------------------------------------------
# src/timeline.js の写し
# ---------------------------------------------------------------------------

NEAR_MS = 5000


def resolve_recording_times(group_a, group_b):
    def prep(files):
        out = []
        for f in files:
            ms = f.get("lastModified", 0)
            cms = f.get("creationMs")
            dur_ms = f.get("duration", 0) * 1000
            if cms is not None and cms > 0:
                if abs(ms - (cms + dur_ms)) < NEAR_MS:
                    candidates = [cms]
                else:
                    candidates = [cms, cms - dur_ms]
            else:
                candidates = [ms - dur_ms, ms]
            out.append({"f": f, "durMs": dur_ms, "candidates": candidates, "idx": 0})
        return out

    A, B = prep(group_a), prep(group_b)
    if not A or not B:
        return {"groupA": group_a, "groupB": group_b, "resolved": False}

    start_of = lambda x: x["candidates"][x["idx"]]

    def total():
        sec = 0
        for a in A:
            for b in B:
                s1, e1 = start_of(a), start_of(a) + a["durMs"]
                s2, e2 = start_of(b), start_of(b) + b["durMs"]
                sec += max(0, min(e1, e2) - max(s1, s2))
        return sec

    movable = [x for x in A + B if len(x["candidates"]) > 1]
    for _ in range(4):
        changed = False
        for x in movable:
            before = total()
            x["idx"] = 1 - x["idx"]
            if total() <= before:
                x["idx"] = 1 - x["idx"]
            else:
                changed = True
        if not changed:
            break

    applied = lambda arr: [dict(x["f"], startMs=start_of(x)) for x in arr]
    return {"groupA": applied(A), "groupB": applied(B), "resolved": True}


def place_on_timeline(files):
    items = []
    for f in files:
        dur = f.get("duration", 0)
        if f.get("startMs") is not None:
            items.append(dict(f, _startMs=f["startMs"],
                              _endMs=f["startMs"] + dur * 1000))
        else:
            end_ms = f.get("lastModified", 0)
            items.append(dict(f, _endMs=end_ms, _startMs=end_ms - dur * 1000))
    if not items:
        return []
    base = min(i["_startMs"] for i in items)
    out = [dict(i, startSec=(i["_startMs"] - base) / 1000,
                endSec=(i["_endMs"] - base) / 1000) for i in items]
    out.sort(key=lambda x: x["startSec"])
    return out


def build_timeline(group_a, group_b):
    fixed = resolve_recording_times(group_a, group_b)
    allf = place_on_timeline(fixed["groupA"] + fixed["groupB"])
    in_b = {f["name"] for f in fixed["groupB"]}
    return {"groupA": [f for f in allf if f["name"] not in in_b],
            "groupB": [f for f in allf if f["name"] in in_b],
            "all": allf, "resolved": fixed["resolved"]}


MIN_OVERLAP_SEC = 10


def find_overlapping_pairs(timeline, min_overlap_sec=MIN_OVERLAP_SEC):
    pairs = []
    for a in timeline["groupA"]:
        for b in timeline["groupB"]:
            start = max(a["startSec"], b["startSec"])
            end = min(a["endSec"], b["endSec"])
            overlap = end - start
            if overlap < min_overlap_sec:
                continue
            pairs.append({"a": a, "b": b, "overlapStartSec": start,
                          "overlapEndSec": end, "overlapSec": overlap,
                          "aOffsetSec": start - a["startSec"],
                          "bOffsetSec": start - b["startSec"]})
    pairs.sort(key=lambda p: -p["overlapSec"])
    return pairs


def find_orphans(timeline, pairs):
    used = set()
    for p in pairs:
        used.add(p["a"]["name"])
        used.add(p["b"]["name"])
    return [f for f in timeline["all"] if f["name"] not in used]


# ---------------------------------------------------------------------------
# 検算
# ---------------------------------------------------------------------------

PASS = 0
FAIL = 0


def ok(cond, label, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}  {extra}")


def near(actual, expected, tol, label):
    d = abs(actual - expected)
    ok(d <= tol, f"{label}  (期待 {expected} / 実際 {actual:.3f})",
       f"差 {d:.3f} > 許容 {tol}")


def make_envelope(len_sec, env_rate, seed=1):
    """セミナーっぽい音量の線。乱数は固定種（毎回同じ結果にする）"""
    s = seed
    def rnd():
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7fffffff
        return s / 0x7fffffff

    n = int(len_sec * env_rate)
    env = []
    for i in range(n):
        t = i / env_rate
        v = 0.25 + 0.08 * math.sin(t * 1.7) + 0.05 * rnd()
        # ときどき入る大きな音。素材固有の目印になる
        if int(t) % 37 == 0 and t % 1 < 0.4:
            v += 0.6
        if int(t) % 53 == 0 and t % 1 < 0.3:
            v += 0.45
        env.append(v)
    return env


def delay_envelope(env, env_rate, delay_sec):
    shift = round(delay_sec * env_rate)
    out = []
    for i in range(len(env)):
        src = i - shift
        out.append(env[src] if 0 <= src < len(env) else 0.02)
    return out


ENV_RATE = 100

print("\n=== build_envelope ===")
sr = 8000
pcm = [0.5] * (sr * 2)
env = build_envelope(pcm, sr, ENV_RATE)
ok(len(env) == 200, f"長さが 2秒×100Hz = 200 になる (実際 {len(env)})")
near(env[50], 0.5, 0.001, "一定音の RMS が振幅と一致する")

print("\n=== cross_correlate の符号 ===")
a = make_envelope(180, ENV_RATE, 7)
b = delay_envelope(a, ENV_RATE, 3.13)
r = cross_correlate(a, b, ENV_RATE, 15)
near(r["offsetSec"], 3.13, 0.02, "b を遅らせたら正の値が返る")

a = make_envelope(180, ENV_RATE, 11)
b = delay_envelope(a, ENV_RATE, -2.5)
r = cross_correlate(a, b, ENV_RATE, 15)
near(r["offsetSec"], -2.5, 0.02, "b が先なら負の値が返る")

# 測定点を変えても同じ答えになること（符号が逆だと2倍の速さで動く）
a = make_envelope(300, ENV_RATE, 13)
b = delay_envelope(a, ENV_RATE, 4.0)
r1 = cross_correlate(a[:100 * ENV_RATE], b[:100 * ENV_RATE], ENV_RATE, 15)
r2 = cross_correlate(a[120 * ENV_RATE:220 * ENV_RATE],
                     b[120 * ENV_RATE:220 * ENV_RATE], ENV_RATE, 15)
near(r1["offsetSec"], 4.0, 0.02, "前半で測っても 4.0")
near(r2["offsetSec"], 4.0, 0.02, "後半で測っても 4.0（測定点に依存しない）")

print("\n=== verify_sync ===")
a = make_envelope(600, ENV_RATE, 17)
b = delay_envelope(a, ENV_RATE, 1.75)
r = verify_sync(a, b, ENV_RATE, 5, 15)
near(r["offsetSec"], 1.75, 0.05, "5窓の多数決で 1.75 が出る")
ok(r["drift"] is False, "ずれが一定なら drift=False")
ok(r["lowConfidence"] is False, "合意できているので lowConfidence=False")
ok(len(r["points"]) == 5, f"窓が5つ測れている (実際 {len(r['points'])})")

a = make_envelope(40, ENV_RATE, 19)
b = delay_envelope(a, ENV_RATE, 0.8)
r = verify_sync(a, b, ENV_RATE, 5, 15)
ok(r["singleWindow"] is True, "30秒に割れない素材は singleWindow で返る")
near(r["offsetSec"], 0.8, 0.05, "短くても値は出る")

print("\n=== 重なり条件（端の偶然一致を拾わないこと） ===")
# 短い窓に広い探索幅を与えたとき、正しい答えを保てるか。
# 実素材で「20秒の窓 + 探索幅15秒」で誤検出が出たので入れた検算。
a = make_envelope(20, ENV_RATE, 29)
b = delay_envelope(a, ENV_RATE, 3.13)
r_wide = cross_correlate(a, b, ENV_RATE, 15)   # 窓20秒に対して探索15秒（広すぎる）
near(r_wide["offsetSec"], 3.13, 0.05,
     "20秒の窓に探索15秒でも正しい答えを保つ")

# 探索幅が窓に対して大きすぎると tooShort が返る
tiny = make_envelope(3, ENV_RATE, 31)
tiny_b = delay_envelope(tiny, ENV_RATE, 0.5)
r_tiny = cross_correlate(tiny, tiny_b, ENV_RATE, 30)
ok(r_tiny.get("tooShort") is True or abs(r_tiny["offsetSec"] - 0.5) < 0.1,
   f"3秒の窓に探索30秒 → tooShort か正答 (実際 {r_tiny})")

# verify_sync が tooShort の窓を数に入れないこと
short_a = make_envelope(50, ENV_RATE, 37)
short_b = delay_envelope(short_a, ENV_RATE, 1.0)
rv = verify_sync(short_a, short_b, ENV_RATE, 3, 9)
ok(all(abs(p["offsetSec"] - 1.0) < 0.05 for p in rv["points"]),
   f"窓に見合った探索幅なら全窓一致 ({[round(p['offsetSec'],2) for p in rv['points']]})")

print("\n=== resolve_recording_times ===")
t0 = 1_700_000_000_000
A = [{"name": "A1.mp4", "duration": 600, "creationMs": t0,
      "lastModified": t0 + 600_000}]
B = [{"name": "B1.mp4", "duration": 600, "creationMs": t0 + 3000,
      "lastModified": t0 + 603_000}]
r = resolve_recording_times(A, B)
ok(r["groupA"][0]["startMs"] == t0, "確定した素材は埋め込みをそのまま開始にする")
ok(r["groupB"][0]["startMs"] == t0 + 3000, "B側も同様")

A = [{"name": "A1.mp4", "duration": 600, "lastModified": t0 + 600_000}]
B = [{"name": "B1.mp4", "duration": 600, "lastModified": t0 + 600_000}]
r = resolve_recording_times(A, B)
ov = (min(r["groupA"][0]["startMs"] + 600_000, r["groupB"][0]["startMs"] + 600_000)
      - max(r["groupA"][0]["startMs"], r["groupB"][0]["startMs"]))
ok(ov > 0, f"埋め込み無しでも重なる置き方を選ぶ (重なり {ov / 1000}秒)")

print("\n=== find_overlapping_pairs（途中で切れて再開する構成） ===")


def mk(name, start_ms, dur):
    return {"name": name, "duration": dur, "creationMs": start_ms,
            "lastModified": start_ms + dur * 1000}


A = [mk("A1.mp4", t0, 600),
     mk("A2.mp4", t0 + 610_000, 600),
     mk("A3.mp4", t0 + 1_230_000, 600)]
B = [mk("B1.mp4", t0 + 2_000, 600),
     mk("B2.mp4", t0 + 615_000, 600),
     mk("B3.mp4", t0 + 1_233_000, 600)]

tl = build_timeline(A, B)
pairs = find_overlapping_pairs(tl)
ok(len(pairs) == 3, f"3組が見つかる (実際 {len(pairs)})")

names = sorted(f"{p['a']['name']}-{p['b']['name']}" for p in pairs)
ok(",".join(names) == "A1.mp4-B1.mp4,A2.mp4-B2.mp4,A3.mp4-B3.mp4",
   f"正しい組み合わせになる ({','.join(names)})")

p1 = next(p for p in pairs if p["a"]["name"] == "A1.mp4")
near(p1["overlapSec"], 598, 1, "1組目の重なりは約598秒")
near(p1["aOffsetSec"], 2, 0.5, "A1 の2秒目から重なる")
near(p1["bOffsetSec"], 0, 0.5, "B1 は先頭から重なる")
ok(len(find_orphans(tl, pairs)) == 0, "取り残されるファイルは無い")

# 片方だけ切れた場合。B が通し録り1本だと A2 も A3 も B1 と重なる
A = [mk("A1.mp4", t0, 600), mk("A2.mp4", t0 + 610_000, 600)]
B = [mk("B1.mp4", t0 + 1_000, 1300)]
pairs = find_overlapping_pairs(build_timeline(A, B))
ok(len(pairs) == 2, f"通し録り1本には2組できる (実際 {len(pairs)})")
ok(pairs[0]["overlapSec"] >= pairs[1]["overlapSec"], "重なりが長い組が先に来る")

# 重なりが短すぎる組は測らない
A = [mk("A1.mp4", t0, 600)]
B = [mk("B1.mp4", t0 + 595_000, 600)]
pairs = find_overlapping_pairs(build_timeline(A, B))
ok(len(pairs) == 0, f"重なり5秒の組は捨てる (実際 {len(pairs)})")

print("\n────────────────────────────")
print(f" 通った: {PASS} / 失敗: {FAIL}")
print("────────────────────────────\n")
sys.exit(0 if FAIL == 0 else 1)

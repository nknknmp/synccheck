# -*- coding: utf-8 -*-
r"""
fcpxml の書き出しの検算

src/export.js の toTime / buildFCPXML と同じ計算を Python で写して、
時間の分数表記と構造が壊れていないか確かめる。

    python test\fcpxml_test.py

■ これは何を保証するか

・時間がフレーム単位の分数になっていること（1フレームずれを防ぐ）
・XML として整形式であること
・組が複数あるとき、時間軸に順番に並ぶこと
・B が A より前に出る場合に、マイナス位置にならないこと

■ これは保証しない

**Resolve / FCP で実際に開けること。** このPCには編集ソフトが無いので
確かめられない。実機未確認。
"""

import math
import sys
import xml.etree.ElementTree as ET

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


# ---------------------------------------------------------------------------
# src/export.js の写し
# ---------------------------------------------------------------------------

TIMEBASE = {
    30:    {"fd": 100,  "tb": 3000,  "name": "30p"},
    29.97: {"fd": 1001, "tb": 30000, "name": "2997p"},
    25:    {"fd": 120,  "tb": 3000,  "name": "25p"},
    24:    {"fd": 125,  "tb": 3000,  "name": "24p"},
    60:    {"fd": 50,   "tb": 3000,  "name": "60p"},
}


def to_time(sec, fd=100, tb=3000):
    frames = round((sec * tb) / fd)
    return f"{frames * fd}/{tb}s"


def nearest_fps(fps):
    best, diff = 30, math.inf
    for k in TIMEBASE:
        d = abs(k - fps)
        if d < diff:
            diff, best = d, k
    return best


def xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def timecode_to_seconds(tc, fps):
    """src/export.js の timecodeToSeconds の写し"""
    import re
    m = re.match(r"^(\d+):(\d+):(\d+)([:;])(\d+)$", str(tc or ""))
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    drop = m.group(4) == ";"
    ff = int(m.group(5))
    t = TIMEBASE[nearest_fps(fps or 30)]
    fd, tb = t["fd"], t["tb"]
    nominal = round(tb / fd)
    frames = (h * 3600 + mi * 60 + s) * nominal + ff
    if drop:
        total_min = h * 60 + mi
        per = round(nominal / 15)
        frames -= per * (total_min - total_min // 10)
    return frames * fd / tb


def plan_asset_formats(files, seq, first_id, color_space=False):
    """src/export.js の planAssetFormats の写し"""
    by_key = {}
    lines = []
    nxt = first_id
    specs = []
    for f in files:
        fps = f.get("fps")
        if isinstance(fps, (int, float)) and fps > 0:
            t = TIMEBASE[nearest_fps(fps)]
        else:
            t = {"fd": seq["fd"], "tb": seq["tb"], "name": seq["name"]}
        w = f.get("width") or seq["width"]
        h = f.get("height") or seq["height"]
        tc_sec = 0
        if f.get("timecode"):
            v = timecode_to_seconds(f["timecode"], fps)
            tc_sec = v if v is not None else 0
        if t["fd"] == seq["fd"] and t["tb"] == seq["tb"] \
                and w == seq["width"] and h == seq["height"]:
            specs.append({"id": "r1", "fd": seq["fd"], "tb": seq["tb"],
                          "tcSec": tc_sec})
            continue
        key = f"{w}x{h}@{t['fd']}/{t['tb']}"
        if key not in by_key:
            by_key[key] = f"r{nxt}"
            nxt += 1
            lines.append(
                f'        <format id="{by_key[key]}"'
                f' name="FFVideoFormat{w}x{h}{t["name"]}"'
                f' frameDuration="{t["fd"]}/{t["tb"]}s" width="{w}" height="{h}"'
                + (' colorSpace="1-1-1 (Rec. 709)"' if color_space else '')
                + '/>'
            )
        specs.append({"id": by_key[key], "fd": t["fd"], "tb": t["tb"],
                      "tcSec": tc_sec})
    return specs, lines


def build_fcpxml(results, fps=30, width=1920, height=1080, project_name="SyncCheck"):
    okr = [r for r in results if r["ok"]]
    if not okr:
        raise ValueError("書き出せる組がありません")

    nf = nearest_fps(fps)
    tbi = TIMEBASE[nf]
    fd, tb, fps_name = tbi["fd"], tbi["tb"], tbi["name"]
    T = lambda sec: to_time(sec, fd, tb)

    assets = {}

    def asset_id(f):
        if f["name"] not in assets:
            assets[f["name"]] = {
                "id": f"r{len(assets) + 2}",
                "name": f["name"],
                "file": f,
                "duration": f.get("duration", 0),
                "src": f"./{f['name']}",
            }
        return assets[f["name"]]["id"]

    for r in okr:
        asset_id(r["pair"]["a"])
        asset_id(r["pair"]["b"])

    asset_list = list(assets.values())
    seq = {"fd": fd, "tb": tb, "name": fps_name, "width": width, "height": height}
    fmt_specs, fmt_lines = plan_asset_formats(
        [a["file"] for a in asset_list], seq, len(asset_list) + 2, True)
    spec_of = {a["id"]: fmt_specs[i] for i, a in enumerate(asset_list)}

    sorted_r = sorted(okr, key=lambda x: x["pair"]["a"]["startSec"])

    clips = []
    cursor = 0.0
    placements = []

    for r in sorted_r:
        a, b = r["pair"]["a"], r["pair"]["b"]
        a_dur = a.get("duration") or r["pair"]["overlapSec"]
        b_dur = b.get("duration") or r["pair"]["overlapSec"]

        b_start = cursor + r["totalOffsetSec"]
        b_offset_into_source = (cursor - b_start) if b_start < cursor else 0
        b_place_at = max(cursor, b_start)
        b_visible = b_dur - b_offset_into_source

        placements.append({
            "a": a["name"], "b": b["name"],
            "aAt": cursor, "bAt": b_place_at,
            "bSourceStart": b_offset_into_source, "bDur": b_visible,
        })

        s_a = spec_of[asset_id(a)]
        s_b = spec_of[asset_id(b)]

        inner = []
        if b_visible > 0:
            inner.append(
                f'                    <asset-clip lane="1" ref="{asset_id(b)}"'
                f' name="{xml_escape(b["name"])}"'
                f' offset="{to_time(s_a["tcSec"] + (b_place_at - cursor), s_a["fd"], s_a["tb"])}"'
                f' start="{to_time(s_b["tcSec"] + b_offset_into_source, s_b["fd"], s_b["tb"])}"'
                f' duration="{to_time(b_visible, s_b["fd"], s_b["tb"])}"'
                f' format="{s_b["id"]}"'
                f' audioRole="dialogue"/>'
            )

        a_start = to_time(s_a["tcSec"], s_a["fd"], s_a["tb"]) if s_a["tcSec"] else "0s"
        clips.append(
            f'                <asset-clip ref="{asset_id(a)}"'
            f' name="{xml_escape(a["name"])}"'
            f' offset="{T(cursor)}" start="{a_start}"'
            f' duration="{to_time(a_dur, s_a["fd"], s_a["tb"])}"'
            f' format="{s_a["id"]}"'
            f' audioRole="dialogue">'
        )
        clips.extend(inner)
        clips.append('                </asset-clip>')

        cursor += a_dur

    asset_lines = []
    for a in asset_list:
        s = spec_of[a["id"]]
        a_start = to_time(s["tcSec"], s["fd"], s["tb"]) if s["tcSec"] else "0s"
        asset_lines.append(
            f'        <asset id="{a["id"]}" name="{xml_escape(a["name"])}"'
            f' start="{a_start}" duration="{to_time(a["duration"], s["fd"], s["tb"])}"'
            f' hasVideo="1" hasAudio="1" format="{s["id"]}"'
            f' audioSources="1" audioChannels="2">\n'
            f'            <media-rep kind="original-media" src="{xml_escape(a["src"])}"/>\n'
            f'        </asset>'
        )

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE fcpxml>',
        '<fcpxml version="1.9">',
        '    <resources>',
        f'        <format id="r1" name="FFVideoFormat{width}x{height}{fps_name}"'
        f' frameDuration="{fd}/{tb}s" width="{width}" height="{height}"'
        f' colorSpace="1-1-1 (Rec. 709)"/>',
        *fmt_lines,
        *asset_lines,
        '    </resources>',
        '    <library>',
        f'        <event name="{xml_escape(project_name)}">',
        f'            <project name="{xml_escape(project_name)}">',
        f'                <sequence format="r1" duration="{T(cursor)}"'
        f' tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
        '                    <spine>',
        *['    ' + c for c in clips],
        '                    </spine>',
        '                </sequence>',
        '            </project>',
        '        </event>',
        '    </library>',
        '</fcpxml>',
    ]
    return "\n".join(lines), placements


# ---------------------------------------------------------------------------
# 検算
# ---------------------------------------------------------------------------

print("\n=== to_time（フレーム単位に丸まるか） ===")
ok(to_time(0, 100, 3000) == "0/3000s", f"0秒 → 0/3000s (実際 {to_time(0)})")
ok(to_time(1, 100, 3000) == "3000/3000s", f"1秒 → 3000/3000s (実際 {to_time(1)})")

# 30fps では 1フレーム = 1/30秒。3.13秒は 93.9フレーム → 94フレームに丸まる
t = to_time(3.13, 100, 3000)
num = int(t.split("/")[0])
ok(num % 100 == 0, f"3.13秒 がフレーム境界に丸まる ({t})")
frames = num // 100
ok(frames == 94, f"3.13秒 → 94フレーム (実際 {frames})")

# 29.97fps の分母が 30000 になっていること（ドロップフレーム対応）
t2997 = to_time(1, 1001, 30000)
ok(t2997.endswith("/30000s"), f"29.97fps は 30000 分母 ({t2997})")

ok(nearest_fps(29.97003) == 29.97, "29.97003 は 29.97 に寄る")
ok(nearest_fps(30.0) == 30, "30.0 は 30")
ok(nearest_fps(59.94) == 60, "59.94 は 60 に寄る")

print("\n=== 3組（途中で切れて再開する構成）の書き出し ===")


def mkfile(name, start_sec, dur):
    return {"name": name, "duration": dur, "startSec": start_sec,
            "endSec": start_sec + dur}


def mkresult(a, b, total_offset, overlap):
    return {
        "ok": True,
        "pair": {"a": a, "b": b, "overlapSec": overlap},
        "totalOffsetSec": total_offset,
    }


results = [
    mkresult(mkfile("A1.mp4", 0, 600), mkfile("B1.mp4", 2, 600), 2.0, 598),
    mkresult(mkfile("A2.mp4", 610, 600), mkfile("B2.mp4", 615, 600), 5.0, 595),
    mkresult(mkfile("A3.mp4", 1230, 600), mkfile("B3.mp4", 1233, 600), 3.0, 597),
]

xml_text, places = build_fcpxml(results)

# XML として読めるか（整形式か）
try:
    root = ET.fromstring(xml_text)
    ok(True, "XML として読める（整形式）")
except ET.ParseError as e:
    ok(False, "XML として読める（整形式）", str(e))
    print(xml_text)
    sys.exit(1)

ok(root.tag == "fcpxml", f"ルート要素が fcpxml (実際 {root.tag})")
ok(root.get("version") == "1.9", "version 1.9")

assets = root.findall(".//asset")
ok(len(assets) == 6, f"asset が6本ぶん (実際 {len(assets)})")

# asset の id が重複していないこと
ids = [a.get("id") for a in assets]
ok(len(ids) == len(set(ids)), f"asset の id が重複していない ({ids})")

# format の id と asset の参照が合っているか
fmt = root.find(".//format")
ok(fmt.get("id") == "r1", "format の id は r1")
ok(all(a.get("format") == "r1" for a in assets), "全 asset が r1 を指す")

spine = root.find(".//spine")
top = [c for c in spine if c.tag == "asset-clip"]
ok(len(top) == 3, f"下のトラックに3クリップ (実際 {len(top)})")

# それぞれに lane=1 の子が1つ
for i, c in enumerate(top):
    lanes = c.findall("asset-clip[@lane='1']")
    ok(len(lanes) == 1, f"{i+1}組目に lane=1 のクリップがある (実際 {len(lanes)})")

print("\n=== 並ぶ位置（時間軸に順番に詰まるか） ===")
ok(places[0]["aAt"] == 0, f"1組目のAは0秒 (実際 {places[0]['aAt']})")
ok(places[1]["aAt"] == 600, f"2組目のAは600秒 (実際 {places[1]['aAt']})")
ok(places[2]["aAt"] == 1200, f"3組目のAは1200秒 (実際 {places[2]['aAt']})")

ok(places[0]["bAt"] == 2.0, f"1組目のBは +2.0秒 (実際 {places[0]['bAt']})")
ok(places[1]["bAt"] == 605.0, f"2組目のBは 600+5.0 (実際 {places[1]['bAt']})")
ok(places[2]["bAt"] == 1203.0, f"3組目のBは 1200+3.0 (実際 {places[2]['bAt']})")

# 全クリップの offset が 0 以上（マイナス位置は編集ソフトが読めない）
for c in spine.iter("asset-clip"):
    off = c.get("offset")
    num = int(off.split("/")[0])
    ok(num >= 0, f"offset が負でない ({c.get('name')} = {off})")

print("\n=== B が A より前に始まる場合（負のズレ） ===")
neg = [mkresult(mkfile("A1.mp4", 5, 600), mkfile("B1.mp4", 0, 600), -5.0, 595)]
xml_neg, pneg = build_fcpxml(neg)

try:
    rn = ET.fromstring(xml_neg)
    ok(True, "負のズレでも XML として読める")
except ET.ParseError as e:
    ok(False, "負のズレでも XML として読める", str(e))

ok(pneg[0]["bAt"] == 0, f"B はマイナス位置にならず0秒に置かれる (実際 {pneg[0]['bAt']})")
ok(pneg[0]["bSourceStart"] == 5.0,
   f"代わりに B の頭を5秒削る (実際 {pneg[0]['bSourceStart']})")
ok(pneg[0]["bDur"] == 595.0, f"見える長さは595秒 (実際 {pneg[0]['bDur']})")

for c in ET.fromstring(xml_neg).find(".//spine").iter("asset-clip"):
    num = int(c.get("offset").split("/")[0])
    ok(num >= 0, f"負のズレでも offset が負でない ({c.get('offset')})")

print("\n=== 同じファイルが複数の組に出る場合 ===")
# B が通し録り1本で、A1 と A2 の両方に対応する
shared_b = mkfile("B1.mp4", 1, 1300)
results2 = [
    mkresult(mkfile("A1.mp4", 0, 600), shared_b, 1.0, 599),
    mkresult(mkfile("A2.mp4", 610, 600), shared_b, 1.0, 600),
]
xml2, _ = build_fcpxml(results2)
root2 = ET.fromstring(xml2)
assets2 = root2.findall(".//asset")
names2 = [a.get("name") for a in assets2]
ok(len(assets2) == 3, f"同じBは1つの asset にまとまる (実際 {len(assets2)}本: {names2})")
ok(names2.count("B1.mp4") == 1, "B1.mp4 の asset は1つだけ")

print("\n=== ファイル名に記号が入る場合 ===")
esc = [mkresult(mkfile("A&B<1>.mp4", 0, 600),
                mkfile('B"quote".mp4', 0, 600), 0.0, 600)]
xml_esc, _ = build_fcpxml(esc)
try:
    re = ET.fromstring(xml_esc)
    found = [a.get("name") for a in re.findall(".//asset")]
    ok("A&B<1>.mp4" in found, f"& < > が正しく戻る ({found})")
    ok('B"quote".mp4' in found, "引用符が正しく戻る")
except ET.ParseError as e:
    ok(False, "記号入りファイル名でも整形式", str(e))

print("\n=== 測れた組が0のとき ===")
try:
    build_fcpxml([{"ok": False, "pair": {"a": mkfile("x", 0, 1),
                                         "b": mkfile("y", 0, 1),
                                         "overlapSec": 0}, "reason": "短い"}])
    ok(False, "測れた組が0なら例外を出す", "例外が出なかった")
except ValueError:
    ok(True, "測れた組が0なら例外を出す")

print("\n=== 素材ごとにフレームレートが違う場合（29.97 のカメラ + 30 のスマホ） ===")
# Resolve が書き出す fcpxml では asset ごとに実素材の format が付く。
# 全 asset に 30p を付けると 29.97 の素材だけ「見つからない」になった。
def mkfile_meta(name, start_sec, dur, fps, w, h):
    d = mkfile(name, start_sec, dur)
    d.update({"fps": fps, "width": w, "height": h})
    return d


mixed = [mkresult(
    mkfile_meta("cam_720p.mp4", 0, 1336.37, 29.97, 1280, 720),
    mkfile_meta("phone_r.mp4", 0, 839.33, 30, 800, 480),
    13.07, 826.26)]
xml_mixed, _ = build_fcpxml(mixed)
rm = ET.fromstring(xml_mixed)
fmts_m = {f.get("id"): f for f in rm.findall(".//format")}
assets_m = {a.get("name"): a for a in rm.findall(".//asset")}

cam_fmt = fmts_m[assets_m["cam_720p.mp4"].get("format")]
ok(cam_fmt.get("frameDuration") == "1001/30000s",
   f"29.97 の素材は 1001/30000s (実際 {cam_fmt.get('frameDuration')})")
ok(cam_fmt.get("width") == "1280" and cam_fmt.get("height") == "720",
   "29.97 の素材は実解像度 1280x720")

phone_fmt = fmts_m[assets_m["phone_r.mp4"].get("format")]
ok(phone_fmt.get("frameDuration") == "100/3000s",
   f"30 の素材は 100/3000s (実際 {phone_fmt.get('frameDuration')})")
ok(phone_fmt.get("width") == "800" and phone_fmt.get("height") == "480",
   "30 の素材は実解像度 800x480")

all_ids = [e.get("id") for e in rm.findall(".//format")] \
    + [e.get("id") for e in rm.findall(".//asset")]
ok(len(all_ids) == len(set(all_ids)), f"format と asset の id が重複していない ({all_ids})")

# asset-clip 側にも素材の format が付き、duration が素材の分母で書かれる
clips_m = {c.get("name"): c for c in rm.findall(".//asset-clip")}
ok(clips_m["cam_720p.mp4"].get("format") == assets_m["cam_720p.mp4"].get("format"),
   "asset-clip にも素材の format が付く")
ok(clips_m["cam_720p.mp4"].get("duration").endswith("/30000s"),
   f"29.97 クリップの duration は /30000s (実際 {clips_m['cam_720p.mp4'].get('duration')})")
ok(clips_m["phone_r.mp4"].get("duration").endswith("/3000s"),
   f"30 クリップの duration は /3000s (実際 {clips_m['phone_r.mp4'].get('duration')})")

print("\n=== タイムコード埋め込み素材（Osmo Pocket 等） ===")
# DJI のカメラはタイムコード＝撮影時刻を埋め込む。asset の start に
# そのタイムコードを書かないと Resolve が素材を見つけられない。
ok(abs(timecode_to_seconds("23:03:32;06", 29.97) - 83012.1292) < 0.001,
   f"DF 23:03:32;06 → 83012.1292秒 (実際 {timecode_to_seconds('23:03:32;06', 29.97)})")
ok(timecode_to_seconds("00:00:10:15", 30) == 10.5, "NDF 00:00:10:15 → 10.5秒")
ok(abs(timecode_to_seconds("01:00:00;00", 29.97) - 3599.9964) < 0.001,
   "DF 01:00:00;00 → 3599.9964秒（1時間ちょうどにならない）")
ok(timecode_to_seconds("不明", 30) is None, "解釈できない文字列は None")

def mkfile_tc(name, start_sec, dur, fps, w, h, tc):
    d = mkfile_meta(name, start_sec, dur, fps, w, h)
    d["timecode"] = tc
    return d


tc_results = [mkresult(
    mkfile_tc("osmo_720p.mp4", 0, 567.73, 29.97, 1280, 720, "23:03:32;06"),
    mkfile_meta("phone_r.mp4", 0, 500, 30, 800, 480),
    3.0, 497)]
xml_tc, _ = build_fcpxml(tc_results)
rtc = ET.fromstring(xml_tc)
assets_tc = {a.get("name"): a for a in rtc.findall(".//asset")}
ok(assets_tc["osmo_720p.mp4"].get("start") == "2490363876/30000s",
   f"asset start がタイムコード (実際 {assets_tc['osmo_720p.mp4'].get('start')})")
ok(assets_tc["phone_r.mp4"].get("start") == "0s",
   "タイムコード無しの素材は start=0s のまま")
clips_tc = {c.get("name"): c for c in rtc.findall(".//asset-clip")}
ok(clips_tc["osmo_720p.mp4"].get("start") == "2490363876/30000s",
   "asset-clip start もタイムコード基点")
ok(clips_tc["phone_r.mp4"].get("start") == "0/3000s",
   f"スマホ側の start は従来通り素材内位置 (実際 {clips_tc['phone_r.mp4'].get('start')})")
# 重ねるクリップの offset は「親の start（TC）+ 親の中での位置」。
# 実効位置 = 親 offset(0) + 子 offset − 親 start が、置きたい位置3秒に一致すること
def parse_frac(t):
    t = t.rstrip("s")
    if "/" in t:
        n, d = t.split("/")
        return int(n) / int(d)
    return float(t)


child_off = parse_frac(clips_tc["phone_r.mp4"].get("offset"))
parent_start = parse_frac(clips_tc["osmo_720p.mp4"].get("start"))
effective = 0 + child_off - parent_start
ok(abs(effective - 3.0) < 0.034,
   f"子の実効位置が3秒に一致 (offset {clips_tc['phone_r.mp4'].get('offset')} → 実効 {effective:.3f}秒)")

print("\n────────────────────────────")
print(f" 通った: {PASS} / 失敗: {FAIL}")
print("────────────────────────────\n")
sys.exit(0 if FAIL == 0 else 1)

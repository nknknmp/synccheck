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
                "duration": f.get("duration", 0),
                "src": f"./{f['name']}",
            }
        return assets[f["name"]]["id"]

    for r in okr:
        asset_id(r["pair"]["a"])
        asset_id(r["pair"]["b"])

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

        inner = []
        if b_visible > 0:
            inner.append(
                f'                    <asset-clip lane="1" ref="{asset_id(b)}"'
                f' name="{xml_escape(b["name"])}"'
                f' offset="{T(b_place_at)}"'
                f' start="{T(b_offset_into_source)}"'
                f' duration="{T(b_visible)}"'
                f' audioRole="dialogue"/>'
            )

        clips.append(
            f'                <asset-clip ref="{asset_id(a)}"'
            f' name="{xml_escape(a["name"])}"'
            f' offset="{T(cursor)}" start="0s" duration="{T(a_dur)}"'
            f' audioRole="dialogue">'
        )
        clips.extend(inner)
        clips.append('                </asset-clip>')

        cursor += a_dur

    asset_lines = []
    for a in assets.values():
        asset_lines.append(
            f'        <asset id="{a["id"]}" name="{xml_escape(a["name"])}"'
            f' start="0s" duration="{T(a["duration"])}"'
            f' hasVideo="1" hasAudio="1" format="r1"'
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

print("\n────────────────────────────")
print(f" 通った: {PASS} / 失敗: {FAIL}")
print("────────────────────────────\n")
sys.exit(0 if FAIL == 0 else 1)

# -*- coding: utf-8 -*-
r"""
書き出すファイル名の検算

src/export.js の outName と同じ処理を Python で写して、素材の名前から
「<基準の名前>_同期済.<拡張子>」が正しく作れるか確かめる。

    python test\outname_test.py

■ これは何を保証するか

・基準クリップ（isBase）の名前が使われること
・拡張子が二重にならないこと（cam1.mp4 → cam1_同期済.fcpxml）
・Windows で使えない文字が混ざっても保存できる名前になること
・素材が無いときは日時の名前に落ちること（従来の動き）

■ これは保証しない

**ブラウザでの実際の保存。** Chrome/Edge は保存ダイアログに「提案」として
出るだけで、利用者が書き換えられる。iPad の Safari はこの名前がそのまま
使われる。どちらも実機未確認。
"""
import re as _re
import sys
from datetime import datetime

PASS = 0
FAIL = 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  NG   {label}" + (f" … {detail}" if detail else ""))


def out_name(line, ext, suffix="同期済"):
    """src/export.js の outName と同じ処理."""
    items = line.get("items", []) if line else []
    base = next((it for it in items if it.get("isBase")), None)
    if base is None:
        base = items[0] if items else None

    if not base or not base.get("name"):
        d = datetime.now()
        return f"SyncCheck_{d:%Y%m%d_%H%M}.{ext}"

    name = base["name"]
    stem = _re.sub(r"\.[^.\/]+$", "", name) or name
    safe = _re.sub(r'[\/:*?"<>|]', "_", stem).strip() or "SyncCheck"
    return f"{safe}_{suffix}.{ext}"


def clip(name=None, is_base=False):
    c = {"isBase": is_base}
    if name is not None:
        c["name"] = name
    return c


print("\n=== 基準クリップの名前を使う ===")
# items は startSec 順に並んでいるが、基準は先頭とは限らない
line = {"items": [clip("cam2.mp4"), clip("cam1.mp4", True)]}
ok(out_name(line, "fcpxml") == "cam1_同期済.fcpxml",
   "基準が先頭でなくても基準の名前を使う", out_name(line, "fcpxml"))

print("\n=== 拡張子 ===")
one = {"items": [clip("cam1.mp4", True)]}
for ext, want in [("fcpxml", "cam1_同期済.fcpxml"),
                  ("txt", "cam1_同期済.txt"),
                  ("csv", "cam1_同期済.csv")]:
    got = out_name(one, ext)
    ok(got == want, f"{ext} で {want}", got)

got = out_name({"items": [clip("C0001.take2.MP4", True)]}, "fcpxml")
ok(got == "C0001.take2_同期済.fcpxml",
   "点が複数あっても最後だけ落とす", got)

got = out_name({"items": [clip("clip", True)]}, "fcpxml")
ok(got == "clip_同期済.fcpxml", "拡張子が無い名前でも壊れない", got)

print("\n=== 基準が見つからないとき ===")
got = out_name({"items": [clip("a.MP4"), clip("b.mp4")]}, "fcpxml")
ok(got == "a_同期済.fcpxml", "先頭（一番早いクリップ）を使う", got)

print("\n=== ファイル名に使えない文字 ===")
got = out_name({"items": [clip('a:b*c?.mp4', True)]}, "fcpxml")
ok(got == "a_b_c__同期済.fcpxml", r'\ / : * ? " < > | を _ にする', got)
ok(not _re.search(r'[\/:*?"<>|]', got), "使えない文字が残っていない", got)

got = out_name({"items": [clip("カメラ1.mp4", True)]}, "fcpxml")
ok(got == "カメラ1_同期済.fcpxml", "日本語の名前はそのまま使える", got)

got = out_name({"items": [clip('???.mp4', True)]}, "fcpxml")
ok(got == "____同期済.fcpxml", "全部が使えない文字でも空にならない", got)

print("\n=== 素材が無いときは日時に落ちる ===")
stamp_re = _re.compile(r"^SyncCheck_\d{8}_\d{4}\.fcpxml$")
for label, line in [("items が空", {"items": []}),
                    ("line が null", None),
                    ("名前が無い", {"items": [clip(None, True)]})]:
    got = out_name(line, "fcpxml")
    ok(bool(stamp_re.match(got)), f"{label} → 日時の名前", got)

print("\n────────────────────────────")
print(f" 通った: {PASS} / 失敗: {FAIL}")
print("────────────────────────────\n")
sys.exit(0 if FAIL == 0 else 1)

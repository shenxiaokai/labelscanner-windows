# -*- coding: utf-8 -*-
"""本地测试：日志写入 / 读取 / 清理 / 图片哈希，不打开界面。"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from labelscanner import LogStore, parse_dict, default_rules

tmp = tempfile.mkdtemp(prefix="labelscanner_logtest_")
store = LogStore(tmp)

parsed = {"EXP Date": "14D20261028", "Lot No.": "1T2567770", "Qty": "8400",
          "Serial No.": "27T2868157-04", "Cust PN": "A0004-C707",
          "Bau No.": "PP000119553", "DESC": "SOT223 SPOT AG SFLA"}
full = "AAMI\nEXP Date:14D20261028\nQty:Q8400"
fake_jpg = b"\xff\xd8\xff\xe0FAKEJPEGDATA"

# 1) 连续写 3 条，序号应为 1、2、3，图片文件应存在
for i in range(3):
    row = store.append(parsed, full, ["1T2567770"], "拍照识别",
                       "3122868157", "[包含] 3122868157", fake_jpg)
    assert row[0] == i + 1, f"序号不对：{row[0]}"
    assert row[13].endswith(".jpg"), "图片文件名不对"
    assert len(row[14]) == 16, "图片哈希不对"
    assert os.path.exists(os.path.join(store.images_dir, row[13])), "图片文件没存下来"
print("写 3 条 OK")

# 2) 读回今天的记录
from datetime import datetime
today = datetime.now().strftime("%Y-%m-%d")
rows = store.read_day(today)
assert len(rows) == 3, f"读回条数不对：{len(rows)}"
assert rows[0]["Lot No."] == "1T2567770", "批号不对"
assert rows[0]["结论"] == "[包含] 3122868157", "结论不对"
assert rows[0]["图片哈希"], "哈希为空"
print("读回 OK，3 条，字段正确")

# 3) parse_dict 输出应与 parse_text 一致
from labelscanner import parse_text
text = "EXP Date:14D20261028\nLot no.: 1T2567770\nQty:Q8400"
d = parse_dict(text, default_rules())
assert d["EXP Date"] == "14D20261028" and d["Qty"] == "8400", d
assert parse_text(text, default_rules()).startswith("EXP Date: 14D20261028")
print("parse_dict OK")

# 4) 清理：造一个 100 天前的旧 CSV 和旧图，保留 90 天应删掉
old_csv = os.path.join(store.logs_dir, "2026-01-01.csv")
with open(old_csv, "w", encoding="utf-8-sig") as f:
    f.write("序号,时间\n1,2026-01-01 10:00:00\n")
old_img = os.path.join(store.images_dir, "20260101_100000_1.jpg")
with open(old_img, "wb") as f:
    f.write(b"old")
store.cleanup(90)
assert not os.path.exists(old_csv), "旧 CSV 没删掉"
assert not os.path.exists(old_img), "旧图片没删掉"
assert len(store.read_day(today)) == 3, "今天的记录被误删"
print("清理过期 OK（旧的删了，今天的还在）")

# 5) retention_days=0 永久保留
store.cleanup(0)
assert len(store.read_day(today)) == 3
print("保留 0 天 = 永久保留 OK")

shutil.rmtree(tmp)
print("全部日志测试通过")

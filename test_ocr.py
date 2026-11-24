# -*- coding: utf-8 -*-
"""本地测试：对用户发过的 AAMI 标签图跑 OCR + 解析 + 条码，验证识别效果。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
from labelscanner import default_rules, ocr_image, parse_text, scan_barcodes

IMAGES = [
    os.path.expanduser("~/workspace/user/media_library/image/2B0FDF0A-DD06-45C0-A864-5613C400F0C0.png"),
    os.path.expanduser("~/workspace/user/media_library/image/F1A8A348-CB26-4512-BF6A-924C4CB72761.png"),
]

for path in IMAGES:
    print("=" * 60)
    print("图片:", os.path.basename(path))
    img = cv2.imread(path)
    if img is None:
        print("读图失败")
        continue
    print("尺寸:", img.shape)
    full = ocr_image(img)
    print("--- OCR 全文 ---")
    print(full)
    print("--- 解析字段 ---")
    print(parse_text(full, default_rules()))
    print("--- 条码 ---")
    print(scan_barcodes(img) or "未扫到条码")
print("=" * 60)
print("测试完成")

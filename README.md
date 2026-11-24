# LabelScanner Windows 版

用电脑摄像头扫描 AAMI 产品标签，功能对齐安卓 V2（1.1 版）：

- **实时识别**：摄像头实时取景，约 700ms 识别一帧
- **拍照识别**：点按钮抓当前一帧识别，拍完暂停实时识别
- **打开图片**：选一张标签照片识别
- **字段解析可配置**：设置页可改字段名、正则、启用/关闭，带测试框
- **对比文本**：主界面输入一条，三个勾选（区分大小写 / 忽略空格和横杠 /
  仅比对解析字段），每次识别完先出 [包含] / [不包含] 结论条
- 条码识别（DataMatrix / 一维码）随识别结果一起显示

## 使用

下载 Releases 里的 `LabelScanner.exe`，双击即用，无需安装 Python。
首次打开会稍慢（解包中英文 OCR 模型），之后正常。
解析规则和对比文本存在 `%APPDATA%\LabelScanner\config.json`，重装软件还在。

## 本地运行（开发）

```bash
pip install -r requirements.txt
python labelscanner.py
```

## 打包

```bash
pyinstaller LabelScanner.spec
# 产物在 dist/LabelScanner.exe
```

打包前 `models/` 目录需放好三个 OCR 模型（`ch_PP-OCRv4_det_infer.onnx`、
`ch_PP-OCRv4_rec_infer.onnx`、`ch_ppocr_mobile_v2.0_cls_infer.onnx`），
可从已安装的 `rapidocr_onnxruntime` 包内 `models/` 复制。
GitHub Actions 会在编译时自动从 pip 包里取，仓库里不存模型文件。

## 日志记录（追溯 / 防甩锅）

- **什么时候记**：拍照识别、打开图片每次都记；实时识别只在填了对比文本、
  并且出现 [包含] / [不包含] 结论、且结论内容变化时记一条。
- **记什么**：时间、来源、7 个解析字段、条码、OCR 原文、对比文本和结论，
  以及当时那一帧画面（JPEG）和图片 SHA256。
- **存在哪**：`%APPDATA%\LabelScanner\logs\`，每天一个 CSV（Excel 直接打开），
  图片存在 `logs\images\`，文件名和记录一一对应。
- **保留天数**：设置页可填，默认 90 天，启动时自动清理过期记录；填 0 为永久保留。
- **查和导出**：主界面“历史记录”按钮，按日期、关键词查，双击看详情和原图，
  可导出 CSV。

## 技术栈

Python + Tkinter + OpenCV（摄像头）+ RapidOCR（中英文 OCR）+ zxing-cpp（条码）

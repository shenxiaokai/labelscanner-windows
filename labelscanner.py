# -*- coding: utf-8 -*-
"""
LabelScanner Windows 版 v1.0
功能对齐安卓 V2（1.1版）：
  1) 实时识别：电脑摄像头实时取景，节流约 700ms 识别一帧
  2) 拍照识别：点按钮抓当前一帧识别，拍完暂停实时识别
  3) 打开图片：选一张标签照片识别
  4) 字段解析可配置：规则存在本地 JSON，设置页可改（增/删/改/启用/测试）
  5) 对比文本：主界面输入一条，三个勾选（区分大小写 / 忽略空格和横杠 /
     仅比对解析字段），每次识别完先出 ✅/❌ 结论条

技术栈：Tkinter + OpenCV（摄像头）+ RapidOCR（中英文 OCR）+ zxing-cpp（条码）
打包：PyInstaller 单文件 .exe，双击即用，无需安装 Python。
"""

import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

APP_NAME = "LabelScanner"
VERSION = "1.0"


# ---------------- 配置：存在用户目录，重启软件还在 ----------------

def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/.config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


CONFIG_PATH = os.path.join(config_dir(), "config.json")


def default_rules():
    return [
        {"name": "EXP Date", "pattern": r"EXP\s*Date:?\s*([0-9A-Z]+)", "enabled": True},
        {"name": "Lot No.", "pattern": r"Lot\s*no\.?:?\s*([0-9A-Z]+)", "enabled": True},
        {"name": "Qty", "pattern": r"Qty:?\s*Q?(\d+)", "enabled": True},
        {"name": "Serial No.", "pattern": r"Serial\s*No\.?:?\s*([0-9A-Z\-]+)", "enabled": True},
        {"name": "Cust PN", "pattern": r"(?:Cust\s*PN|CUSTOMER\s*P/N):?\s*([0-9A-Z\-]+)", "enabled": True},
        {"name": "Bau No.", "pattern": r"Bau\s*(?:No\.?|NBR)?\s*:?\s*([0-9A-Z]+)", "enabled": True},
        {"name": "DESC", "pattern": r"DESC:?\s*(.+)", "enabled": True},
    ]


def load_config():
    cfg = {
        "rules": default_rules(),
        "compare_text": "",
        "case_sensitive": False,
        "ignore_space_hyphen": True,
        "only_parsed": False,
        "camera_index": 0,
        "logging_enabled": True,
        "retention_days": 90,
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update(saved)
        rules = []
        for r in cfg.get("rules") or []:
            name = str(r.get("name", "")).strip()
            pattern = str(r.get("pattern", "")).strip()
            if not name or not pattern:
                continue
            try:
                re.compile(pattern)
            except re.error:
                continue
            rules.append({"name": name, "pattern": pattern,
                          "enabled": bool(r.get("enabled", True))})
        cfg["rules"] = rules if rules else default_rules()
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def parse_dict(text, rules):
    """按当前配置解析全文，返回 {字段名: 值}，没取到写 未识别。"""
    result = {}
    for rule in rules:
        if not rule.get("enabled", True):
            result[rule["name"]] = "已关闭"
            continue
        try:
            m = re.search(rule["pattern"], text, re.IGNORECASE)
            result[rule["name"]] = (m.group(1).strip() if m and m.group(1)
                                    and m.group(1).strip() else "未识别")
        except Exception:
            result[rule["name"]] = "表达式错误"
    return result


def parse_text(text, rules):
    """按当前配置解析全文，返回每行 '字段名: 值'，没取到写 未识别。"""
    return "\n".join(f"{k}: {v}" for k, v in parse_dict(text, rules).items())


# ---------------- OCR 与条码：懒加载，第一次用时才初始化 ----------------

_ocr_engine = None
_ocr_lock = threading.Lock()


def bundled_models_dir():
    """PyInstaller 打包时模型放在 _MEIPASS/models；源码运行时放在脚本旁 models。"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "models")


def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    with _ocr_lock:
        if _ocr_engine is not None:
            return _ocr_engine
        from rapidocr_onnxruntime import RapidOCR
        models = bundled_models_dir()
        det = os.path.join(models, "ch_PP-OCRv4_det_infer.onnx")
        rec = os.path.join(models, "ch_PP-OCRv4_rec_infer.onnx")
        cls = os.path.join(models, "ch_ppocr_mobile_v2.0_cls_infer.onnx")
        if os.path.exists(det) and os.path.exists(rec):
            kwargs = {"det_model_path": det, "rec_model_path": rec}
            if os.path.exists(cls):
                kwargs["cls_model_path"] = cls
            _ocr_engine = RapidOCR(**kwargs)
        else:
            # 没带模型文件时让 RapidOCR 自己下载（首次需联网）
            _ocr_engine = RapidOCR()
        return _ocr_engine


def ocr_image(bgr):
    """返回识别出的全文（按行拼接）。"""
    engine = get_ocr_engine()
    result, _ = engine(bgr)
    if not result:
        return ""
    rows = sorted(result, key=lambda r: (r[0][0][1], r[0][0][0]))
    return "\n".join(r[1] for r in rows)


def scan_barcodes(bgr):
    try:
        import zxingcpp
        results = zxingcpp.read_barcodes(bgr)
        return [r.text for r in results if r.text]
    except Exception:
        return []





# ---------------- 日志记录：每天一个 CSV + 每条一张图 ----------------

import csv
import hashlib
from datetime import datetime, timedelta

LOG_CSV_HEADER = ["序号", "时间", "来源", "EXP Date", "Lot No.", "Qty",
                  "Serial No.", "Cust PN", "Bau No.", "DESC", "条码",
                  "对比文本", "结论", "图片文件", "图片哈希", "OCR原文"]


class LogStore:
    """日志存在配置目录下的 logs/：每天一个 CSV，图片存在 logs/images/。

    只追加不修改；每条一个流水号；图片存 SHA256 前 16 位，图被换过能发现。
    """

    def __init__(self, base_dir):
        self.logs_dir = os.path.join(base_dir, "logs")
        self.images_dir = os.path.join(self.logs_dir, "images")
        os.makedirs(self.images_dir, exist_ok=True)

    def day_csv(self, date_str):
        return os.path.join(self.logs_dir, f"{date_str}.csv")

    def append(self, parsed_dict, full_text, codes, source,
               compare_text, verdict, image_bytes):
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        csv_path = self.day_csv(date_str)
        exists = os.path.exists(csv_path)
        seq = 1
        if exists:
            try:
                with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                    seq = max(1, sum(1 for _ in csv.reader(f)))
            except Exception:
                seq = 1
        img_name = ""
        img_hash = ""
        if image_bytes:
            img_hash = hashlib.sha256(image_bytes).hexdigest()[:16]
            img_name = f"{now.strftime('%Y%m%d_%H%M%S')}_{seq}.jpg"
            try:
                with open(os.path.join(self.images_dir, img_name), "wb") as f:
                    f.write(image_bytes)
            except Exception:
                img_name = ""
                img_hash = ""
        row = [seq, time_str, source,
               parsed_dict.get("EXP Date", ""), parsed_dict.get("Lot No.", ""),
               parsed_dict.get("Qty", ""), parsed_dict.get("Serial No.", ""),
               parsed_dict.get("Cust PN", ""), parsed_dict.get("Bau No.", ""),
               parsed_dict.get("DESC", ""),
               "、".join(codes), compare_text, verdict,
               img_name, img_hash, full_text]
        with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(LOG_CSV_HEADER)
            w.writerow(row)
        return row

    def list_dates(self):
        dates = []
        try:
            for name in os.listdir(self.logs_dir):
                if name.endswith(".csv"):
                    dates.append(name[:-4])
        except Exception:
            pass
        return sorted(dates, reverse=True)

    def read_day(self, date_str):
        path = self.day_csv(date_str)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def cleanup(self, retention_days):
        """删掉超过保留天数的 CSV 和图片；retention_days <= 0 表示永久保留。"""
        if retention_days <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=retention_days)).date()
        try:
            names = os.listdir(self.logs_dir)
        except Exception:
            return
        for name in names:
            if not name.endswith(".csv"):
                continue
            try:
                d = datetime.strptime(name[:-4], "%Y-%m-%d").date()
            except ValueError:
                continue
            if d < cutoff:
                try:
                    os.remove(os.path.join(self.logs_dir, name))
                except Exception:
                    pass
        try:
            img_names = os.listdir(self.images_dir)
        except Exception:
            return
        for name in img_names:
            try:
                d = datetime.strptime(name.split("_")[0], "%Y%m%d").date()
            except (ValueError, IndexError):
                continue
            if d < cutoff:
                try:
                    os.remove(os.path.join(self.images_dir, name))
                except Exception:
                    pass

# ---------------- 主界面 ----------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{VERSION} - 标签识别")
        self.geometry("900x750")
        self.cfg = load_config()

        self.cap = None
        self.camera_index = int(self.cfg.get("camera_index", 0))
        self.live_on = False
        self.last_frame = None
        self.last_ocr_ms = 0
        self.result_queue = queue.Queue()
        self.ocr_busy = False
        self.closing = False
        self.log_store = LogStore(config_dir())
        self.last_log_signature = None
        try:
            self.log_store.cleanup(int(self.cfg.get("retention_days", 90)))
        except Exception:
            pass

        self._build_ui()
        self._restore_compare_ui()
        self.after(100, self._pump_queue)
        self.after(50, self._preview_loop)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.preview_label = ttk.Label(top, text="摄像头未开启",
                                       anchor=tk.CENTER, background="black",
                                       foreground="white")
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        cmp = ttk.Frame(top)
        cmp.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(cmp, text="对比文本：").pack(side=tk.LEFT)
        self.et_compare = ttk.Entry(cmp)
        self.et_compare.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.et_compare.bind("<KeyRelease>", self._on_compare_changed)
        ttk.Button(cmp, text="清除", command=self._clear_compare).pack(side=tk.LEFT)

        checks = ttk.Frame(top)
        checks.pack(fill=tk.X, pady=(4, 0))
        self.var_case = tk.BooleanVar()
        self.var_ignore = tk.BooleanVar()
        self.var_only = tk.BooleanVar()
        for text, var in (("区分大小写", self.var_case),
                          ("忽略空格和横杠", self.var_ignore),
                          ("仅比对解析字段", self.var_only)):
            ttk.Checkbutton(checks, text=text, variable=var,
                            command=self._on_compare_changed).pack(side=tk.LEFT, padx=(0, 12))

        self.verdict = tk.Label(top, text="", font=("", 13, "bold"), pady=6)
        self.verdict.pack(fill=tk.X, pady=(4, 0))

        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, pady=(8, 0))
        self.btn_live = ttk.Button(btns, text="开始实时识别", command=self._toggle_live)
        self.btn_live.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(btns, text="拍照识别", command=self._take_photo).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(btns, text="打开图片", command=self._open_image).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(btns, text="切换摄像头", command=self._switch_camera).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(btns, text="设置解析字段", command=self._open_settings).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(btns, text="历史记录", command=self._open_history).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        self.tv_result = scrolledtext.ScrolledText(top, height=14, font=("", 11))
        self.tv_result.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.tv_result.insert(tk.END,
            "点“开始实时识别”用摄像头对准标签，或点“拍照识别” / “打开图片”。")
        self.tv_result.config(state=tk.DISABLED)

        self.status = ttk.Label(self, text="就绪", anchor=tk.W)
        self.status.pack(fill=tk.X, padx=10, pady=(0, 6))

    def _restore_compare_ui(self):
        self.et_compare.insert(0, self.cfg.get("compare_text", ""))
        self.var_case.set(bool(self.cfg.get("case_sensitive", False)))
        self.var_ignore.set(bool(self.cfg.get("ignore_space_hyphen", True)))
        self.var_only.set(bool(self.cfg.get("only_parsed", False)))

    def _on_compare_changed(self, *args):
        self.cfg["compare_text"] = self.et_compare.get()
        self.cfg["case_sensitive"] = self.var_case.get()
        self.cfg["ignore_space_hyphen"] = self.var_ignore.get()
        self.cfg["only_parsed"] = self.var_only.get()
        save_config(self.cfg)

    def _clear_compare(self):
        self.et_compare.delete(0, tk.END)
        self.verdict.config(text="", background=self.cget("background"))
        self._on_compare_changed()

    def _set_status(self, text):
        self.status.config(text=text)

    def _set_result(self, text):
        self.tv_result.config(state=tk.NORMAL)
        self.tv_result.delete("1.0", tk.END)
        self.tv_result.insert(tk.END, text)
        self.tv_result.config(state=tk.DISABLED)

    def _open_camera(self):
        if self.cap is not None and self.cap.isOpened():
            return True
        for idx in [self.camera_index, 0, 1]:
            if sys.platform == "win32":
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(idx)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap = cap
                self.camera_index = idx
                self.cfg["camera_index"] = idx
                save_config(self.cfg)
                return True
            cap.release()
        return False

    def _close_camera(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def _preview_loop(self):
        if self.closing:
            return
        if self.cap is not None and self.cap.isOpened():
            ok, frame = self.cap.read()
            if ok and frame is not None:
                self.last_frame = frame
                self._show_frame(frame)
                if self.live_on:
                    now = time.time() * 1000
                    if not self.ocr_busy and now - self.last_ocr_ms >= 700:
                        self.last_ocr_ms = now
                        self._run_ocr_async(frame.copy(), "实时识别")
        self.after(50, self._preview_loop)

    def _show_frame(self, frame):
        h, w = frame.shape[:2]
        max_w, max_h = 860, 420
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        photo = ImageTk.PhotoImage(image=img)
        self.preview_label.config(image=photo, text="")
        self.preview_label.image = photo

    def _toggle_live(self):
        if self.live_on:
            self.live_on = False
            self.btn_live.config(text="开始实时识别")
            self._set_status("已停止实时识别")
        else:
            if not self._open_camera():
                messagebox.showerror("摄像头", "打不开摄像头：请确认电脑已接摄像头，"
                                     "且没有被别的程序占用。")
                return
            self.live_on = True
            self.btn_live.config(text="停止识别")
            self._set_status("实时识别中，把标签对准画面……")

    def _switch_camera(self):
        self.live_on = False
        self.btn_live.config(text="开始实时识别")
        self._close_camera()
        self.camera_index = (self.camera_index + 1) % 3
        if self._open_camera():
            self._set_status(f"已切换到摄像头 {self.camera_index}")
        else:
            self.preview_label.config(image="", text="摄像头未开启")
            messagebox.showerror("摄像头", "打不开摄像头。")

    def _take_photo(self):
        if self.cap is None or not self.cap.isOpened():
            if not self._open_camera():
                messagebox.showerror("摄像头", "打不开摄像头。")
                return
            self._set_status("正在启动相机……")
            self.after(500, self._take_photo)
            return
        frame = self.last_frame
        if frame is None:
            ok, frame = self.cap.read()
            if not ok or frame is None:
                messagebox.showerror("拍照", "拍照失败，没取到画面。")
                return
        self.live_on = False
        self.btn_live.config(text="开始实时识别")
        self._run_ocr_async(frame.copy(), "拍照识别")

    def _open_image(self):
        path = filedialog.askopenfilename(
            title="选择一张标签照片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.webp"), ("所有文件", "*.*")])
        if not path:
            return
        img = cv2.imread(path)
        if img is None:
            messagebox.showerror("打开图片", "图片读取失败。")
            return
        self.live_on = False
        self.btn_live.config(text="开始实时识别")
        self._run_ocr_async(img, "打开图片")

    def _run_ocr_async(self, bgr, source):
        if self.ocr_busy:
            return
        self.ocr_busy = True
        self._set_status(f"{source}识别中……")
        self._set_result("识别中……")

        def worker():
            try:
                full_text = ocr_image(bgr)
                codes = scan_barcodes(bgr)
                parsed = parse_text(full_text, self.cfg["rules"])
                parsed_dict = parse_dict(full_text, self.cfg["rules"])
                ok, buf = cv2.imencode(".jpg", bgr,
                                       [cv2.IMWRITE_JPEG_QUALITY, 85])
                image_bytes = buf.tobytes() if ok else b""
                parts = [f"[{source}]", parsed, "",
                         "条码：" + ("、".join(codes) if codes else "未扫到条码"),
                         "", "---- 原文 ----", full_text]
                self.result_queue.put(("result", full_text, parsed, "\n".join(parts),
                                       parsed_dict, codes, image_bytes, source))
            except Exception as e:
                self.result_queue.put(("error", f"识别失败：{e}"))
            finally:
                self.result_queue.put(("done",))

        threading.Thread(target=worker, daemon=True).start()

    def _pump_queue(self):
        if self.closing:
            return
        try:
            while True:
                msg = self.result_queue.get_nowait()
                if msg[0] == "result":
                    (_, full_text, parsed, display,
                     parsed_dict, codes, image_bytes, source) = msg
                    self._show_result(full_text, parsed, display,
                                      parsed_dict, codes, image_bytes, source)
                    self._set_status("识别完成")
                elif msg[0] == "error":
                    self.verdict.config(text="", background=self.cget("background"))
                    self._set_result(msg[1])
                    self._set_status("识别失败")
                elif msg[0] == "done":
                    self.ocr_busy = False
        except queue.Empty:
            pass
        self.after(100, self._pump_queue)

    def _show_result(self, full_text, parsed, display,
                     parsed_dict=None, codes=None, image_bytes=b"", source=""):
        target = self.cfg.get("compare_text", "").strip()
        verdict = ""
        if not target:
            self.verdict.config(text="", background=self.cget("background"))
        else:
            haystack = parsed if self.cfg.get("only_parsed", False) else full_text
            matched = self._contains_compare(haystack, target)
            verdict = f"[包含] {target}" if matched else f"[不包含] {target}"
            self.verdict.config(
                text=verdict,
                background="#C8E6C9" if matched else "#FFCDD2")
        self._set_result(display)
        self._maybe_log(source, full_text, parsed_dict or {}, codes or [],
                        image_bytes, target, verdict)

    def _maybe_log(self, source, full_text, parsed_dict, codes,
                   image_bytes, compare_text, verdict):
        """按定稿规则记日志：拍照/打开图片每次都记；实时只在出现对比结论、
        且结论内容变化时记。没填对比文本时实时不记。"""
        if not self.cfg.get("logging_enabled", True):
            return
        if source == "实时识别":
            if not verdict:
                return
            signature = (verdict, tuple(sorted(parsed_dict.items())))
            if signature == self.last_log_signature:
                return
            self.last_log_signature = signature
        try:
            self.log_store.append(parsed_dict, full_text, codes, source,
                                  compare_text, verdict, image_bytes)
        except Exception:
            pass

    def _open_history(self):
        HistoryWindow(self, self.log_store)

    def _contains_compare(self, haystack, target):
        h, t = haystack, target
        if self.cfg.get("ignore_space_hyphen", True):
            h = h.replace(" ", "").replace("-", "")
            t = t.replace(" ", "").replace("-", "")
        if not self.cfg.get("case_sensitive", False):
            h = h.upper()
            t = t.upper()
        return t in h

    def _open_settings(self):
        SettingsWindow(self, self.cfg, on_saved=self._on_rules_saved)

    def _on_rules_saved(self):
        save_config(self.cfg)
        self._set_status("解析规则已保存")

    def _on_close(self):
        self.closing = True
        self.live_on = False
        self._close_camera()
        save_config(self.cfg)
        self.destroy()


# ---------------- 设置窗口：字段名 / 正则 / 启用都能改 ----------------

class SettingsWindow(tk.Toplevel):
    def __init__(self, parent, cfg, on_saved=None):
        super().__init__(parent)
        self.title("设置解析字段")
        self.geometry("720x560")
        self.cfg = cfg
        self.on_saved = on_saved
        self.rows = []
        self.transient(parent)
        self.grab_set()

        tip = ttk.Label(self, text="每行一条规则：正则里第 1 个括号就是要取的值。"
                                   "改完点保存，下次识别生效。")
        tip.pack(fill=tk.X, padx=10, pady=(10, 4))

        header = ttk.Frame(self)
        header.pack(fill=tk.X, padx=10)
        ttk.Label(header, text="字段名", width=14).pack(side=tk.LEFT)
        ttk.Label(header, text="正则表达式", width=52).pack(side=tk.LEFT, padx=4)
        ttk.Label(header, text="启用").pack(side=tk.LEFT)

        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True, padx=10)
        self.canvas = tk.Canvas(container)
        scroll = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.rows_frame = ttk.Frame(self.canvas)
        self.rows_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.rows_frame, anchor=tk.NW)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for rule in self.cfg["rules"]:
            self._add_row(rule)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btns, text="新增一行", command=lambda: self._add_row(
            {"name": "新字段", "pattern": r"关键词:?\s*(.+)", "enabled": True})).pack(side=tk.LEFT)
        ttk.Button(btns, text="恢复默认", command=self._restore).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="保存", command=self._save).pack(side=tk.RIGHT)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=6)

        # 日志设置
        log_box = ttk.LabelFrame(self, text="日志设置")
        log_box.pack(fill=tk.X, padx=10, pady=(0, 8))
        self.var_logging = tk.BooleanVar(
            value=bool(self.cfg.get("logging_enabled", True)))
        ttk.Checkbutton(log_box, text="启用日志记录",
                        variable=self.var_logging).pack(side=tk.LEFT, padx=6, pady=6)
        ttk.Label(log_box, text="保留天数：").pack(side=tk.LEFT, padx=(10, 0))
        self.et_retention = ttk.Entry(log_box, width=6)
        self.et_retention.insert(0, str(self.cfg.get("retention_days", 90)))
        self.et_retention.pack(side=tk.LEFT)
        ttk.Label(log_box, text="天（0 = 永久保留）").pack(side=tk.LEFT)
        ttk.Button(log_box, text="打开日志文件夹",
                   command=self._open_logs_folder).pack(side=tk.RIGHT, padx=6)

        # 测试区
        test_box = ttk.LabelFrame(self, text="测试：贴一段识别文字，点测试看解析结果")
        test_box.pack(fill=tk.BOTH, padx=10, pady=(0, 10))
        self.et_test = tk.Text(test_box, height=4, font=("", 10))
        self.et_test.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(test_box, text="测试当前规则", command=self._test).pack(
            anchor=tk.W, padx=6, pady=(0, 4))
        self.tv_test = tk.Text(test_box, height=5, font=("", 10), state=tk.DISABLED)
        self.tv_test.pack(fill=tk.X, padx=6, pady=(0, 6))

    def _add_row(self, rule):
        frame = ttk.Frame(self.rows_frame)
        frame.pack(fill=tk.X, pady=2)
        name_e = ttk.Entry(frame, width=16)
        name_e.insert(0, rule["name"])
        name_e.pack(side=tk.LEFT)
        pat_e = ttk.Entry(frame, width=58)
        pat_e.insert(0, rule["pattern"])
        pat_e.pack(side=tk.LEFT, padx=4)
        var = tk.BooleanVar(value=bool(rule.get("enabled", True)))
        ttk.Checkbutton(frame, variable=var).pack(side=tk.LEFT)

        def delete():
            self.rows = [r for r in self.rows if r[3] is not frame]
            frame.destroy()

        ttk.Button(frame, text="删除", command=delete).pack(side=tk.LEFT, padx=4)
        self.rows.append((name_e, pat_e, var, frame))

    def _restore(self):
        for _, _, _, frame in self.rows:
            frame.destroy()
        self.rows = []
        for rule in default_rules():
            self._add_row(rule)

    def _collect(self):
        rules = []
        for i, (name_e, pat_e, var, _) in enumerate(self.rows):
            name = name_e.get().strip()
            pattern = pat_e.get().strip()
            if not name and not pattern:
                continue
            if not name:
                messagebox.showerror("保存", f"第 {i + 1} 行字段名不能为空。")
                return None
            if not pattern:
                messagebox.showerror("保存", f"第 {i + 1} 行正则不能为空。")
                return None
            try:
                re.compile(pattern)
            except re.error as e:
                messagebox.showerror("保存", f"第 {i + 1} 行正则无效：{e}")
                return None
            rules.append({"name": name, "pattern": pattern, "enabled": var.get()})
        if not rules:
            messagebox.showerror("保存", "至少保留一条规则。")
            return None
        return rules

    def _open_logs_folder(self):
        folder = self.master.log_store.logs_dir
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showinfo("日志文件夹", f"日志存在：\n{folder}\n（自动打开失败：{e}）")

    def _save(self):
        rules = self._collect()
        if rules is None:
            return
        try:
            retention = int(self.et_retention.get().strip())
            if retention < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("保存", "保留天数请填 0 或更大的整数。")
            return
        self.cfg["rules"] = rules
        self.cfg["logging_enabled"] = self.var_logging.get()
        self.cfg["retention_days"] = retention
        save_config(self.cfg)
        try:
            self.master.log_store.cleanup(retention)
        except Exception:
            pass
        messagebox.showinfo("保存", f"已保存，共 {len(rules)} 条规则。")
        if self.on_saved:
            self.on_saved()
        self.destroy()

    def _test(self):
        rules = self._collect()
        if rules is None:
            return
        text = self.et_test.get("1.0", tk.END)
        if not text.strip():
            messagebox.showinfo("测试", "先在测试框里贴一段识别文字。")
            return
        self.tv_test.config(state=tk.NORMAL)
        self.tv_test.delete("1.0", tk.END)
        self.tv_test.insert(tk.END, parse_text(text, rules))
        self.tv_test.config(state=tk.DISABLED)



# ---------------- 历史记录窗口：按日期查，按关键词筛，可导出 ----------------

class HistoryWindow(tk.Toplevel):
    def __init__(self, parent, log_store):
        super().__init__(parent)
        self.title("历史记录")
        self.geometry("920x600")
        self.log_store = log_store
        self.rows = []
        self.transient(parent)

        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(bar, text="日期：").pack(side=tk.LEFT)
        self.et_date = ttk.Entry(bar, width=12)
        self.et_date.insert(0, datetime.now().strftime("%Y-%m-%d"))
        self.et_date.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(bar, text="关键词：").pack(side=tk.LEFT)
        self.et_key = ttk.Entry(bar, width=20)
        self.et_key.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.et_key.bind("<Return>", lambda e: self._query())
        ttk.Button(bar, text="查询", command=self._query).pack(side=tk.LEFT)
        ttk.Button(bar, text="导出当前结果", command=self._export).pack(side=tk.LEFT, padx=6)

        cols = ("序号", "时间", "来源", "批号", "序列号", "结论", "图片")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=22)
        for c, w in zip(cols, (50, 150, 70, 130, 160, 120, 130)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        self.tree.bind("<Double-1>", self._show_detail)
        self._query()

    def _query(self):
        date_str = self.et_date.get().strip()
        keyword = self.et_key.get().strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("查询", "日期格式不对，请填 YYYY-MM-DD，例如 2026-11-24。")
            return
        rows = self.log_store.read_day(date_str)
        if keyword:
            rows = [r for r in rows
                    if any(keyword in (r.get(k) or "") for k in r.keys())]
        self.rows = rows
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in rows:
            self.tree.insert("", tk.END, values=(
                r.get("序号", ""), r.get("时间", ""), r.get("来源", ""),
                r.get("Lot No.", ""), r.get("Serial No.", ""),
                r.get("结论", ""), r.get("图片文件", "")))

    def _export(self):
        if not self.rows:
            messagebox.showinfo("导出", "当前没有可导出的记录。")
            return
        path = filedialog.asksaveasfilename(
            title="导出 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv")],
            initialfile=f"扫描记录_{self.et_date.get().strip()}.csv")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=LOG_CSV_HEADER)
                w.writeheader()
                for r in self.rows:
                    w.writerow({k: r.get(k, "") for k in LOG_CSV_HEADER})
            messagebox.showinfo("导出", f"已导出 {len(self.rows)} 条记录。")
        except Exception as e:
            messagebox.showerror("导出", f"导出失败：{e}")

    def _show_detail(self, event):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.rows):
            return
        r = self.rows[idx]
        win = tk.Toplevel(self)
        win.title(f"记录 {r.get('序号', '')} - {r.get('时间', '')}")
        win.geometry("700x620")
        txt = scrolledtext.ScrolledText(win, font=("", 11))
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        lines = []
        for k in LOG_CSV_HEADER:
            if k == "图片文件":
                continue
            lines.append(f"{k}：{r.get(k, '')}")
        txt.insert(tk.END, "\n".join(lines))
        txt.config(state=tk.DISABLED)
        img_name = r.get("图片文件", "")
        if img_name:
            img_path = os.path.join(self.log_store.images_dir, img_name)
            if os.path.exists(img_path):
                try:
                    im = Image.open(img_path)
                    im.thumbnail((640, 300))
                    photo = ImageTk.PhotoImage(im)
                    lab = ttk.Label(win, image=photo)
                    lab.image = photo
                    lab.pack(padx=10, pady=(0, 10))
                    ttk.Button(win, text="打开原图",
                               command=lambda: self._open_image_file(img_path)).pack(pady=(0, 10))
                except Exception:
                    pass

    def _open_image_file(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showinfo("打开图片", f"图片在：\n{path}\n（自动打开失败：{e}）")

def main():
    # 隐藏自检模式：LabelScanner --selftest <图片>，在终端打印识别结果后退出，
    # 用于验证打包后的 OCR/条码是否正常，不打开界面。
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        img = cv2.imread(sys.argv[2])
        if img is None:
            print("读图失败：", sys.argv[2])
            sys.exit(1)
        full_text = ocr_image(img)
        codes = scan_barcodes(img)
        print(parse_text(full_text, load_config()["rules"]))
        print("条码：" + ("、".join(codes) if codes else "未扫到条码"))
        print("---- 原文 ----")
        print(full_text)
        return
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()

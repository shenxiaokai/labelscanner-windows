# -*- coding: utf-8 -*-
"""本地测试：界面能打开，设置页保存、历史记录窗口不报错（xvfb 下跑）。"""
import os
import sys
import tkinter.messagebox as mb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

mb.showinfo = lambda *a, **k: None
mb.showerror = lambda *a, **k: None

from labelscanner import App

app = App()
app.update_idletasks()
app.update()
print("主界面 OK")

app._open_settings()
app.update_idletasks()
app.update()
settings = [w for w in app.winfo_children()
            if w.__class__.__name__ == "SettingsWindow"]
assert settings, "设置窗口没打开"
print("设置窗口 OK，行数：", len(settings[0].rows))
settings[0]._save()
app.update_idletasks()
app.update()
print("设置保存 OK")

app._open_history()
app.update_idletasks()
app.update()
hist = [w for w in app.winfo_children()
        if w.__class__.__name__ == "HistoryWindow"]
assert hist, "历史记录窗口没打开"
print("历史记录窗口 OK，当前记录数：", len(hist[0].rows))
app.destroy()
print("全部界面测试通过")

import tkinter as tk
from tkinter import ttk

from app.encode_tab import EncodeTab
from app.decode_tab import DecodeTab
from app.widgets import StatusBar


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QR DataBridge v1.0")
        self.geometry("900x700")
        self.minsize(700, 560)

        self._build_ui()
        # Global Ctrl+V: paste image only when decode tab is active and focus is not in a text widget
        self.bind("<Control-v>", self._route_ctrl_v)

    def _build_ui(self):
        self._status_bar = StatusBar(self)
        self._status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._encode_tab = EncodeTab(self._notebook, status_cb=self._status_bar.set)
        self._decode_tab = DecodeTab(self._notebook, status_cb=self._status_bar.set)

        self._notebook.add(self._encode_tab, text="📤 编码 Encode")
        self._notebook.add(self._decode_tab, text="📥 解码 Decode")

    def _route_ctrl_v(self, event):
        focused = self.focus_get()
        # If a text/entry widget has focus, let the default paste happen
        if focused and focused.winfo_class() in ("Text", "Entry", "TEntry"):
            return
        # Only paste image when decode tab is selected
        if self._notebook.index(self._notebook.select()) == 1:
            self._decode_tab._paste_image()
            return "break"

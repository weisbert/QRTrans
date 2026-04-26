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
        on_decode = self._notebook.index(self._notebook.select()) == 1
        if not on_decode:
            return
        # On the decode tab, only defer to default paste when focus is on an
        # editable text widget that actually lives inside the decode tab.
        # Otherwise focus may be stuck on the encode tab's hidden text box, or
        # on the decode tab's disabled output box — both swallow Ctrl+V silently.
        focused = self.focus_get()
        if focused and focused.winfo_class() in ("Text", "Entry", "TEntry"):
            inside_decode = str(focused).startswith(str(self._decode_tab))
            try:
                editable = str(focused.cget("state")) == "normal"
            except tk.TclError:
                editable = True
            if inside_decode and editable:
                return
        self._decode_tab._paste_image()
        return "break"

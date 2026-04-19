import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk


class QRCanvas(tk.Frame):
    """Scrollable canvas for displaying a PIL Image (QR grid)."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._photo = None

        self.canvas = tk.Canvas(self, bg="white", cursor="arrow")
        self.h_scroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.v_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)

        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def show_image(self, img: Image.Image):
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, img.width, img.height))

    def clear(self):
        self._photo = None
        self.canvas.delete("all")
        self.canvas.configure(scrollregion=(0, 0, 0, 0))


class StatusBar(tk.Frame):
    """Single-line status bar at the bottom of the main window."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, relief=tk.SUNKEN, bd=1, **kwargs)
        self._var = tk.StringVar(value="就绪")
        tk.Label(self, textvariable=self._var, anchor=tk.W, padx=6).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

    def set(self, msg: str):
        self._var.set(msg)

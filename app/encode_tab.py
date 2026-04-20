import math
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from PIL import Image, ImageTk

from core.encoder import encode_text, make_qr_image, paginate, get_max_payload
from core.utils import detect_encoding, gzip_compress
from app.widgets import QRCanvas


LAYOUTS = {
    "1×1": (1, 1),
    "2×1": (2, 1),
    "3×1": (3, 1),
    "2×2": (2, 2),
    "3×2": (3, 2),
    "4×2": (4, 2),
    "4×3": (4, 3),
    "5×3": (5, 3),
    "6×3": (6, 3),
    "5×4": (5, 4),
    "6×4": (6, 4),
    "8×4": (8, 4),
    "10×4": (10, 4),
    "8×5": (8, 5),
    "10×5": (10, 5),
}
EC_LEVELS = [
    "H — 最高纠错 (30%，推荐)",
    "Q — 较高纠错 (25%)",
    "M — 中等纠错 (15%)",
    "L — 低纠错   (7%，容量最大)",
]


def _ec_key(display: str) -> str:
    return display[0]


def _get_virtual_screen():
    """Return (x, y, width, height) of the full virtual desktop spanning all monitors."""
    if sys.platform == "win32":
        import ctypes
        u32 = ctypes.windll.user32
        return (
            u32.GetSystemMetrics(76),   # SM_XVIRTUALSCREEN
            u32.GetSystemMetrics(77),   # SM_YVIRTUALSCREEN
            u32.GetSystemMetrics(78),   # SM_CXVIRTUALSCREEN
            u32.GetSystemMetrics(79),   # SM_CYVIRTUALSCREEN
        )
    else:
        # Linux: winfo_vrootwidth/height covers the virtual root (works with most WMs)
        try:
            root = tk._default_root
            vw = root.winfo_vrootwidth()
            vh = root.winfo_vrootheight()
            return 0, 0, vw, vh
        except Exception:
            return None


class _CapacityBar(tk.Frame):
    """Segmented real-time capacity indicator showing per-QR fill ratio."""

    _H = 20  # bar pixel height

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._label = tk.Label(self, anchor=tk.W, fg="#555555", font=("", 9))
        self._label.pack(fill=tk.X)
        self._canvas = tk.Canvas(self, height=self._H, highlightthickness=0, bg="#E8E8E8")
        self._canvas.pack(fill=tk.X, pady=(2, 0))

    def refresh(self, char_count: int, compressed_size: int, num_qr: int, max_payload: int):
        if char_count == 0:
            self._label.config(text="")
            self._canvas.delete("all")
            return

        self._label.config(
            text=(
                f"{char_count:,} 字符  →  压缩后约 {compressed_size:,} B  →  "
                f"需要 {num_qr} 个QR码  （每码容量 {max_payload} B）"
            )
        )

        self._canvas.update_idletasks()
        W = self._canvas.winfo_width() or 400
        H = self._H
        self._canvas.delete("all")

        seg_w = W / num_qr
        for i in range(num_qr):
            used = min(max(compressed_size - i * max_payload, 0), max_payload)
            ratio = used / max_payload
            x0 = i * seg_w
            x1 = (i + 1) * seg_w - 1
            fill_x1 = x0 + seg_w * ratio

            # Background (empty portion)
            self._canvas.create_rectangle(x0, 0, x1, H, fill="#E0E0E0", outline="")
            # Filled portion — color by saturation level
            if ratio > 0:
                if ratio >= 0.95:
                    color = "#EF5350"   # red: nearly or fully packed
                elif ratio >= 0.75:
                    color = "#FFA726"   # orange: fairly full
                else:
                    color = "#66BB6A"   # green: comfortable
                self._canvas.create_rectangle(x0, 0, fill_x1, H, fill=color, outline="")

            # Label: "QR1  68%"
            label = f"QR{i + 1}  {ratio * 100:.0f}%"
            text_color = "white" if ratio > 0.35 else "#666666"
            mid_x = (x0 + x1) / 2
            self._canvas.create_text(mid_x, H / 2, text=label, fill=text_color, font=("", 9))

            # Divider between segments
            if i < num_qr - 1:
                self._canvas.create_line(x1 + 1, 0, x1 + 1, H, fill="#AAAAAA", width=1)

        # Outer border
        self._canvas.create_rectangle(0, 0, W - 1, H - 1, outline="#BBBBBB", fill="")


class GridPicker(tk.Toplevel):
    """Excel-style grid popup for selecting layout (cols × rows)."""

    MAX_COLS = 10
    MAX_ROWS = 8
    CELL = 24
    GAP = 1
    _C_INACTIVE = "#D8D8D8"
    _C_ACTIVE = "#4472C4"
    _C_BORDER = "#999999"

    def __init__(self, anchor: tk.Widget, on_select):
        super().__init__(anchor.winfo_toplevel())
        self._on_select = on_select
        self._hover_col = 0
        self._hover_row = 0
        self._root = anchor.winfo_toplevel()

        self.overrideredirect(True)
        self.transient(self._root)

        cw = self.MAX_COLS * (self.CELL + self.GAP) - self.GAP
        ch = self.MAX_ROWS * (self.CELL + self.GAP) - self.GAP
        frame = tk.Frame(self, bd=1, relief=tk.SOLID, bg="#CCCCCC")
        frame.pack(padx=1, pady=1)
        self._canvas = tk.Canvas(frame, width=cw, height=ch,
                                 highlightthickness=0, bg="#FFFFFF", cursor="hand2")
        self._canvas.pack(padx=4, pady=(4, 2))
        self._label = tk.Label(frame, text="", font=("", 9), bg="#FFFFFF")
        self._label.pack(pady=(0, 4))

        self._draw(0, 0)

        self._canvas.bind("<Motion>", self._on_motion)
        self._canvas.bind("<Button-1>", self._on_click)
        self.bind("<Escape>", lambda e: self._close())

        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 2
        pw = self.winfo_reqwidth()
        ph = self.winfo_reqheight()
        x = min(x, self.winfo_screenwidth() - pw - 4)
        y = min(y, self.winfo_screenheight() - ph - 4)
        self.geometry(f"+{x}+{y}")

        # Use a root-level click binding to detect outside clicks.
        # grab_set() + overrideredirect causes a deadlock on Windows.
        self._outside_id = self._root.bind("<ButtonPress>", self._on_outside_click, add="+")

    def _close(self):
        try:
            self._root.unbind("<ButtonPress>", self._outside_id)
        except Exception:
            pass
        self.destroy()

    def _on_outside_click(self, event):
        """Dismiss the picker when the user clicks outside it."""
        wx = self.winfo_rootx()
        wy = self.winfo_rooty()
        ww = self.winfo_width()
        wh = self.winfo_height()
        rx = event.x_root
        ry = event.y_root
        if not (wx <= rx <= wx + ww and wy <= ry <= wy + wh):
            self._close()

    def _cell_rect(self, c, r):
        x0 = (c - 1) * (self.CELL + self.GAP)
        y0 = (r - 1) * (self.CELL + self.GAP)
        return x0, y0, x0 + self.CELL, y0 + self.CELL

    def _draw(self, hc: int, hr: int):
        self._canvas.delete("all")
        for r in range(1, self.MAX_ROWS + 1):
            for c in range(1, self.MAX_COLS + 1):
                x0, y0, x1, y1 = self._cell_rect(c, r)
                fill = self._C_ACTIVE if (c <= hc and r <= hr) else self._C_INACTIVE
                self._canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline=self._C_BORDER)

    def _on_motion(self, event):
        col = max(1, min(self.MAX_COLS, event.x // (self.CELL + self.GAP) + 1))
        row = max(1, min(self.MAX_ROWS, event.y // (self.CELL + self.GAP) + 1))
        if col != self._hover_col or row != self._hover_row:
            self._hover_col, self._hover_row = col, row
            self._draw(col, row)
            self._label.config(text=f"{col} × {row}")

    def _on_click(self, event):
        col = max(1, min(self.MAX_COLS, event.x // (self.CELL + self.GAP) + 1))
        row = max(1, min(self.MAX_ROWS, event.y // (self.CELL + self.GAP) + 1))
        self._on_select(col, row)
        self._close()


class EncodeTab(tk.Frame):
    def __init__(self, parent, status_cb=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._status_cb = status_cb or (lambda msg: None)
        self._pages: list[Image.Image] = []
        self._qr_images: list[Image.Image] = []
        self._current_page = 0
        self._cap_after_id = None
        self._build_ui()

    def _build_ui(self):
        # Toolbar
        toolbar = tk.Frame(self)
        toolbar.pack(fill=tk.X, padx=6, pady=(6, 0))
        tk.Button(toolbar, text="📂 加载文件", command=self._load_file).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="📋 清空", command=self._clear).pack(side=tk.LEFT, padx=2)

        # Text input
        tk.Label(self, text="输入文本：", anchor=tk.W).pack(fill=tk.X, padx=6)
        self.text_input = scrolledtext.ScrolledText(self, height=8, wrap=tk.WORD)
        self.text_input.pack(fill=tk.BOTH, expand=False, padx=6, pady=2)
        self.text_input.bind("<KeyRelease>", self._schedule_capacity_update)
        self.text_input.bind("<<Paste>>", self._schedule_capacity_update)

        # Capacity indicator
        self._cap_bar = _CapacityBar(self)
        self._cap_bar.pack(fill=tk.X, padx=6, pady=(0, 4))

        # Options row: layout + EC level
        opts = tk.Frame(self)
        opts.pack(fill=tk.X, padx=6, pady=2)
        tk.Label(opts, text="布局:").pack(side=tk.LEFT)
        self._layout_var = tk.StringVar(value="2×1")
        self._layout_cb = ttk.Combobox(
            opts, textvariable=self._layout_var, values=list(LAYOUTS.keys()), width=6, state="readonly"
        )
        self._layout_cb.pack(side=tk.LEFT, padx=4)
        self._layout_btn = tk.Button(opts, text="⊞", width=2, command=self._open_grid_picker)
        self._layout_btn.pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(opts, text="纠错等级:").pack(side=tk.LEFT, padx=(12, 0))
        self._ec_var = tk.StringVar(value=EC_LEVELS[0])
        ec_cb = ttk.Combobox(opts, textvariable=self._ec_var, values=EC_LEVELS, width=26, state="readonly")
        ec_cb.pack(side=tk.LEFT, padx=4)
        ec_cb.bind("<<ComboboxSelected>>", self._schedule_capacity_update)

        # Generate button
        tk.Button(self, text="🔄 生成 QR 码", command=self._generate, height=2).pack(
            fill=tk.X, padx=6, pady=4
        )

        # Bottom controls — pack BEFORE canvas so expand=True never crowds them out
        btn_row = tk.Frame(self)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(2, 6))
        tk.Button(btn_row, text="🖥 当前屏全屏",
                  command=lambda: self._show_fullscreen(span=False)).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2)
        )
        tk.Button(btn_row, text="🖥🖥 跨屏全屏",
                  command=lambda: self._show_fullscreen(span=True)).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2)
        )
        tk.Button(btn_row, text="💾 保存当前页", command=self._save_page).pack(
            side=tk.LEFT, expand=True, fill=tk.X
        )

        page_frame = tk.Frame(self)
        page_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=2)
        tk.Button(page_frame, text="← 上一页", command=self._prev_page).pack(side=tk.LEFT)
        self._page_label = tk.Label(page_frame, text="第 - 页 / 共 - 页")
        self._page_label.pack(side=tk.LEFT, expand=True)
        tk.Button(page_frame, text="下一页 →", command=self._next_page).pack(side=tk.RIGHT)

        # QR display area — fills whatever space remains
        self._canvas = QRCanvas(self)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)

    # ── capacity indicator ─────────────────────────────────────────────���────

    def _schedule_capacity_update(self, event=None):
        if self._cap_after_id:
            self.after_cancel(self._cap_after_id)
        self._cap_after_id = self.after(400, self._update_capacity)

    def _update_capacity(self):
        self._cap_after_id = None
        text = self.text_input.get("1.0", tk.END).rstrip("\n")
        if not text.strip():
            self._cap_bar.refresh(0, 0, 0, 0)
            return
        try:
            ec = _ec_key(self._ec_var.get())
            max_payload = get_max_payload(ec)
            compressed = gzip_compress(text.encode("utf-8"))
            num_qr = max(1, math.ceil(len(compressed) / max_payload))
            self._cap_bar.refresh(len(text), len(compressed), num_qr, max_payload)
        except Exception:
            pass

    def _recommend_layout(self, num_packets: int) -> str:
        """Pick the smallest LAYOUTS entry that fits all packets."""
        for key, (cols, rows) in sorted(LAYOUTS.items(), key=lambda x: x[1][0] * x[1][1]):
            if cols * rows >= num_packets:
                return key
        return max(LAYOUTS, key=lambda k: LAYOUTS[k][0] * LAYOUTS[k][1])

    def _open_grid_picker(self):
        def on_select(cols, rows):
            key = f"{cols}×{rows}"
            if key not in LAYOUTS:
                LAYOUTS[key] = (cols, rows)
            self._layout_var.set(key)
            self._layout_cb.config(values=list(LAYOUTS.keys()))
        GridPicker(self._layout_btn, on_select)

    # ── file / clear ────────────────────────────────────────────────────────

    def _load_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("文本文件", "*.txt *.csv *.log *.tsv"), ("所有文件", "*.*")]
        )
        if not path:
            return
        with open(path, "rb") as f:
            raw = f.read()
        enc = detect_encoding(raw)
        try:
            text = raw.decode(enc)
        except Exception:
            for e in ("utf-8", "gbk", "latin-1"):
                try:
                    text = raw.decode(e)
                    break
                except Exception:
                    continue
            else:
                messagebox.showerror("编码错误", "无法自动检测文件编码，请手动转换为 UTF-8")
                return
        self.text_input.delete("1.0", tk.END)
        self.text_input.insert("1.0", text)
        self._schedule_capacity_update()
        self._status_cb(f"已加载文件: {path}（编码: {enc}，{len(text)} 字符）")

    def _clear(self):
        self.text_input.delete("1.0", tk.END)
        self._cap_bar.refresh(0, 0, 0, 0)
        self._canvas.clear()
        self._pages = []
        self._qr_images = []
        self._current_page = 0
        self._page_label.config(text="第 - 页 / 共 - 页")
        self._status_cb("已清空")

    # ── generate / display ──────────────────────────────────────────────────

    def _generate(self):
        text = self.text_input.get("1.0", tk.END).rstrip("\n")
        if not text.strip():
            messagebox.showwarning("提示", "请先输入数据")
            return

        self._status_cb("正在生成 QR 码...")
        self.update_idletasks()

        try:
            ec = _ec_key(self._ec_var.get())
            packets = encode_text(text, ec_level=ec)
            num_pkts = len(packets)

            self._layout_var.set(self._recommend_layout(num_pkts))
            cols, rows = LAYOUTS[self._layout_var.get()]
            qr_images = [make_qr_image(p, ec_level=ec) for p in packets]
            self._qr_images = qr_images
            self._pages = paginate(qr_images, cols, rows)
            self._current_page = 0
            self._show_page()
            self._status_cb(
                f"生成完成：{len(text)} 字符 → {num_pkts} 个QR码，"
                f"{cols}×{rows} 布局，共 {len(self._pages)} 页"
            )
        except Exception as e:
            messagebox.showerror("生成失败", str(e))
            self._status_cb(f"生成失败：{e}")

    def _show_page(self):
        if not self._pages:
            return
        self._canvas.show_image(self._pages[self._current_page])
        self._page_label.config(
            text=f"第 {self._current_page + 1} 页 / 共 {len(self._pages)} 页"
        )

    def _prev_page(self):
        if self._pages and self._current_page > 0:
            self._current_page -= 1
            self._show_page()

    def _next_page(self):
        if self._pages and self._current_page < len(self._pages) - 1:
            self._current_page += 1
            self._show_page()

    # ── fullscreen display ──────────────────────────────────────────────────

    def _show_fullscreen(self, span: bool = False):
        if not self._qr_images:
            messagebox.showwarning("提示", "请先生成 QR 码")
            return

        if span:
            info = _get_virtual_screen()
            sw, sh = (info[2], info[3]) if info else (self.winfo_screenwidth(), self.winfo_screenheight())
        else:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()

        # Respect the user's chosen layout; scale QR images to fill the screen.
        cols, rows = LAYOUTS[self._layout_var.get()]
        padding = 10
        label_h = 22
        qr_px = max(80, min(
            (sw - padding * (cols + 1)) // cols,
            (sh - padding * (rows + 1) - label_h * rows) // rows,
        ))

        scaled = [img.resize((qr_px, qr_px), Image.NEAREST) for img in self._qr_images]
        # padding must match the value used when computing qr_px above, or the
        # grid will overflow the screen and show_page's NEAREST downscale
        # corrupts QR modules enough to defeat pyzbar.
        fs_pages = paginate(scaled, cols=cols, rows=rows, padding=padding)
        n_total = len(self._qr_images)
        n_pages = len(fs_pages)

        win = tk.Toplevel(self)
        win.configure(bg="black")
        win.bind("<Escape>", lambda e: win.destroy())
        if span:
            self._apply_span(win)
        else:
            self._apply_maximize(win)

        lbl = tk.Label(win, bg="black", cursor="hand2")
        lbl.pack(expand=True)
        page_idx = [0]

        def show_page(idx):
            page_idx[0] = idx % n_pages
            img = fs_pages[page_idx[0]]
            ww, wh = win.winfo_width(), win.winfo_height()
            if ww < 100 or wh < 100:
                win.after(50, lambda: show_page(idx))
                return
            ratio = min(ww / img.width, wh / img.height, 1.0)
            disp = img if ratio >= 0.99 else img.resize(
                (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                Image.NEAREST,
            )
            photo = ImageTk.PhotoImage(disp)
            lbl.config(image=photo)
            lbl.image = photo
            pg = page_idx[0] + 1
            nav = "  ←→/点击翻页  " if n_pages > 1 else "  点击"
            win.title(
                f"QR 全屏 — 第 {pg}/{n_pages} 页  {n_total}个码  {cols}×{rows}/页"
                f"  [Esc 关闭{nav}]"
            )

        def on_key(e):
            if e.keysym in ("Right", "space", "Next"):
                show_page(page_idx[0] + 1)
            elif e.keysym in ("Left", "Prior"):
                show_page(page_idx[0] - 1)

        win.bind("<Key>", on_key)
        lbl.bind("<Button-1>", lambda e: (
            win.destroy() if n_pages == 1 else show_page(page_idx[0] + 1)
        ))

        win.after(150, lambda: show_page(0))

    def _apply_maximize(self, win: tk.Toplevel):
        """Maximize on the same monitor as the main window."""
        win.geometry(f"+{self.winfo_rootx()}+{self.winfo_rooty()}")
        win.update_idletasks()
        if sys.platform == "win32":
            win.state("zoomed")
        else:
            try:
                win.attributes("-zoomed", True)
            except tk.TclError:
                win.attributes("-fullscreen", True)

    def _apply_span(self, win: tk.Toplevel):
        """Cover the entire virtual desktop (all monitors combined)."""
        info = _get_virtual_screen()
        if info is None:
            # No multi-monitor info available; fall back to single-screen maximize
            self._apply_maximize(win)
            return
        vx, vy, vw, vh = info
        # overrideredirect removes the title bar so the window can span monitor boundaries
        # without each monitor's compositor clipping it to one screen.
        win.overrideredirect(True)
        win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        win.lift()
        win.focus_force()

    # ── save ────────────────────────────────────────────────────────────────

    def _save_page(self):
        if not self._pages:
            messagebox.showwarning("提示", "请先生成 QR 码")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"qrdb_page{self._current_page + 1}_{ts}.png"
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG 图片", "*.png")],
        )
        if path:
            self._pages[self._current_page].save(path)
            self._status_cb(f"已保存：{path}")

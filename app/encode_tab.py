import math
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from PIL import Image, ImageTk

from core.encoder import encode_text, make_qr_image, paginate, recommend_layout, get_max_payload
from core.utils import detect_encoding, gzip_compress
from app.widgets import QRCanvas


LAYOUTS = {
    "1×1": (1, 1),
    "2×1": (2, 1),
    "3×1": (3, 1),
    "2×2": (2, 2),
    "3×2": (3, 2),
    "4×2": (4, 2),
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


class EncodeTab(tk.Frame):
    def __init__(self, parent, status_cb=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._status_cb = status_cb or (lambda msg: None)
        self._pages: list[Image.Image] = []
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

        # Options row
        opts = tk.Frame(self)
        opts.pack(fill=tk.X, padx=6, pady=2)
        tk.Label(opts, text="布局:").pack(side=tk.LEFT)
        self._layout_var = tk.StringVar(value="2×1")
        self._layout_cb = ttk.Combobox(
            opts, textvariable=self._layout_var, values=list(LAYOUTS.keys()), width=6, state="readonly"
        )
        self._layout_cb.pack(side=tk.LEFT, padx=4)
        tk.Label(opts, text="纠错等级:").pack(side=tk.LEFT, padx=(12, 0))
        self._ec_var = tk.StringVar(value=EC_LEVELS[0])
        ec_cb = ttk.Combobox(opts, textvariable=self._ec_var, values=EC_LEVELS, width=22, state="readonly")
        ec_cb.pack(side=tk.LEFT, padx=4)
        ec_cb.bind("<<ComboboxSelected>>", self._schedule_capacity_update)

        # Generate button
        tk.Button(self, text="🔄 生成 QR 码", command=self._generate, height=2).pack(
            fill=tk.X, padx=6, pady=4
        )

        # QR display area
        self._canvas = QRCanvas(self)
        self._canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)

        # Paging controls
        page_frame = tk.Frame(self)
        page_frame.pack(fill=tk.X, padx=6, pady=2)
        tk.Button(page_frame, text="← 上一页", command=self._prev_page).pack(side=tk.LEFT)
        self._page_label = tk.Label(page_frame, text="第 - 页 / 共 - 页")
        self._page_label.pack(side=tk.LEFT, expand=True)
        tk.Button(page_frame, text="下一页 →", command=self._next_page).pack(side=tk.RIGHT)

        # Bottom buttons row
        btn_row = tk.Frame(self)
        btn_row.pack(fill=tk.X, padx=6, pady=(2, 6))
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

            rec_cols, rec_rows = recommend_layout(num_pkts)
            rec_key = next(
                (k for k, v in LAYOUTS.items() if v == (rec_cols, rec_rows)), "4×2"
            )
            self._layout_var.set(rec_key)

            cols, rows = LAYOUTS[self._layout_var.get()]
            qr_images = [make_qr_image(p, ec_level=ec) for p in packets]
            self._pages = paginate(qr_images, cols, rows)
            self._current_page = 0
            self._show_page()
            self._status_cb(
                f"生成完成：{len(text)} 字符 → 压缩后分 {num_pkts} 个QR码，共 {len(self._pages)} 页"
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
        if not self._pages:
            messagebox.showwarning("提示", "请先生成 QR 码")
            return
        img = self._pages[self._current_page]
        win = tk.Toplevel(self)
        win.title(f"QR 全屏预览 — 第 {self._current_page + 1} 页  [Esc / 点击 关闭]")
        win.configure(bg="black")
        win.bind("<Escape>", lambda e: win.destroy())

        if span:
            self._apply_span(win)
        else:
            self._apply_maximize(win)

        def _draw():
            sw, sh = win.winfo_width(), win.winfo_height()
            if sw < 100 or sh < 100:
                win.after(50, _draw)
                return
            ratio = min(sw / img.width, sh / img.height)
            new_w = max(1, int(img.width * ratio))
            new_h = max(1, int(img.height * ratio))
            resized = img.resize((new_w, new_h), Image.NEAREST)
            photo = ImageTk.PhotoImage(resized)
            lbl = tk.Label(win, image=photo, bg="black", cursor="hand2")
            lbl.image = photo
            lbl.pack(expand=True)
            lbl.bind("<Button-1>", lambda e: win.destroy())

        win.after(150, _draw)

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

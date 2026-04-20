import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import time
from PIL import Image, ImageTk

from core.decoder import preprocess_image, detect_and_decode_qrs, reassemble
from core.protocol import MissingPacketError, CRCError, ProtocolError


class DecodeTab(tk.Frame):
    def __init__(self, parent, status_cb=None, **kwargs):
        super().__init__(parent, **kwargs)
        self._status_cb = status_cb or (lambda msg: None)
        self._images: list[Image.Image] = []
        self._preview_photos: list = []
        self._preview_index: int = 0
        self._decode_start_time: float = 0.0
        self._build_ui()

    def _build_ui(self):
        # Toolbar
        toolbar = tk.Frame(self)
        toolbar.pack(fill=tk.X, padx=6, pady=(6, 0))
        tk.Button(toolbar, text="📋 粘贴截图 Ctrl+V", command=self._paste_image).pack(
            side=tk.LEFT, padx=2
        )
        tk.Button(toolbar, text="📂 加载图片", command=self._load_images).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="清空", command=self._clear).pack(side=tk.LEFT, padx=2)

        # Image queue info
        queue_frame = tk.Frame(self)
        queue_frame.pack(fill=tk.X, padx=6, pady=(2, 0))
        self._queue_var = tk.StringVar(value="未加载任何截图")
        tk.Label(queue_frame, textvariable=self._queue_var, anchor=tk.W, fg="blue").pack(
            side=tk.LEFT
        )

        # Preview area with navigation
        preview_frame = tk.LabelFrame(self, text="截图预览")
        preview_frame.pack(fill=tk.X, padx=6, pady=4)
        preview_frame.configure(height=200)
        preview_frame.pack_propagate(False)

        nav_frame = tk.Frame(preview_frame)
        nav_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self._prev_btn = tk.Button(nav_frame, text="←", width=3, command=self._preview_prev)
        self._prev_btn.pack(side=tk.LEFT)
        self._nav_var = tk.StringVar(value="")
        self._nav_label = tk.Label(nav_frame, textvariable=self._nav_var)
        self._nav_label.pack(side=tk.LEFT, expand=True)
        self._delete_btn = tk.Button(nav_frame, text="删除此张", command=self._delete_current_preview)
        self._delete_btn.pack(side=tk.LEFT)
        self._next_btn = tk.Button(nav_frame, text="→", width=3, command=self._preview_next)
        self._next_btn.pack(side=tk.RIGHT)

        self._preview_label = tk.Label(
            preview_frame, text="粘贴 Snipaste 截图或加载图片（可多次添加）", fg="gray"
        )
        self._preview_label.pack(expand=True, fill=tk.BOTH)

        # Decode button
        tk.Button(self, text="🔍 解码", command=self._decode, height=2).pack(
            fill=tk.X, padx=6, pady=4
        )

        # Progress + status
        prog_frame = tk.Frame(self)
        prog_frame.pack(fill=tk.X, padx=6, pady=2)
        self._progress = ttk.Progressbar(prog_frame, mode="determinate")
        self._progress.pack(fill=tk.X, pady=2)
        self._decode_status_var = tk.StringVar(value="")
        tk.Label(prog_frame, textvariable=self._decode_status_var, anchor=tk.W).pack(
            fill=tk.X
        )

        # Retry button (always present, starts disabled)
        self._retry_btn = tk.Button(
            self,
            text="⚠ 高对比度预处理后重试",
            command=self._retry_enhanced,
            fg="gray",
            state=tk.DISABLED,
        )
        self._retry_btn.pack(fill=tk.X, padx=6, pady=2)

        # Output area
        tk.Label(self, text="解码结果：", anchor=tk.W).pack(fill=tk.X, padx=6)
        self._output = scrolledtext.ScrolledText(self, height=10, wrap=tk.WORD, state=tk.DISABLED)
        self._output.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)

        # Action buttons
        action_frame = tk.Frame(self)
        action_frame.pack(fill=tk.X, padx=6, pady=(2, 6))
        tk.Button(action_frame, text="📋 复制全部", command=self._copy_all).pack(
            side=tk.LEFT, padx=2
        )
        tk.Button(action_frame, text="💾 保存为文件", command=self._save_file).pack(
            side=tk.LEFT, padx=2
        )

        self._update_nav_buttons()

    def _paste_image(self, event=None):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is None:
                messagebox.showinfo("提示", "请先用 Snipaste 截图（截图会自动进入剪贴板）")
                return
            if not isinstance(img, Image.Image):
                messagebox.showinfo("提示", "剪贴板中没有图像数据")
                return
            self._add_image(img)
        except Exception as e:
            messagebox.showerror("粘贴失败", str(e))

    def _load_images(self):
        paths = filedialog.askopenfilenames(
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp *.tiff"), ("所有文件", "*.*")]
        )
        if not paths:
            return
        loaded = 0
        for path in paths:
            try:
                img = Image.open(path)
                self._add_image(img, update_queue_label=False, update_nav=False)
                loaded += 1
            except Exception as e:
                messagebox.showerror("加载失败", f"{path}\n{e}")
        if loaded:
            self._update_queue_label()
            self._update_nav_buttons()
            self._status_cb(f"加载了 {loaded} 张图片，共 {len(self._images)} 张")

    def _add_image(self, img: Image.Image, update_queue_label: bool = True, update_nav: bool = True):
        converted = img.convert("RGB")
        self._images.append(converted)
        self._preview_index = len(self._images) - 1
        self._show_preview(converted)
        if update_queue_label:
            self._update_queue_label()
            self._status_cb(f"已添加截图，共 {len(self._images)} 张（{img.width}×{img.height} px）")
        if update_nav:
            self._update_nav_buttons()

    def _update_queue_label(self):
        n = len(self._images)
        if n == 0:
            self._queue_var.set("未加载任何截图")
        elif n == 1:
            self._queue_var.set("已加载 1 张截图（可继续粘贴/加载更多）")
        else:
            self._queue_var.set(f"已加载 {n} 张截图 — 将合并解码")

    def _update_nav_buttons(self):
        n = len(self._images)
        if n == 0:
            self._nav_var.set("")
            self._prev_btn.config(state=tk.DISABLED)
            self._next_btn.config(state=tk.DISABLED)
            self._delete_btn.config(state=tk.DISABLED)
            self._preview_label.config(
                image="", text="粘贴 Snipaste 截图或加载图片（可多次添加）", fg="gray"
            )
        else:
            idx = self._preview_index
            self._nav_var.set(f"第 {idx + 1} 张 / 共 {n} 张")
            self._prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
            self._next_btn.config(state=tk.NORMAL if idx < n - 1 else tk.DISABLED)
            self._delete_btn.config(state=tk.NORMAL)

    def _show_preview(self, img: Image.Image):
        max_w, max_h = 860, 170
        ratio = min(max_w / img.width, max_h / img.height, 1.0)
        w, h = int(img.width * ratio), int(img.height * ratio)
        thumb = img.resize((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(thumb)
        self._preview_photos = [photo]  # keep reference
        self._preview_label.config(image=photo, text="")

    def _preview_prev(self):
        if self._preview_index > 0:
            self._preview_index -= 1
            self._show_preview(self._images[self._preview_index])
            self._update_nav_buttons()

    def _preview_next(self):
        if self._preview_index < len(self._images) - 1:
            self._preview_index += 1
            self._show_preview(self._images[self._preview_index])
            self._update_nav_buttons()

    def _delete_current_preview(self):
        if not self._images:
            return
        idx = self._preview_index
        del self._images[idx]
        if self._images:
            self._preview_index = min(idx, len(self._images) - 1)
            self._show_preview(self._images[self._preview_index])
        else:
            self._preview_index = 0
        self._update_queue_label()
        self._update_nav_buttons()
        self._status_cb(f"已删除第 {idx + 1} 张截图，剩余 {len(self._images)} 张")

    def _clear(self):
        self._images.clear()
        self._preview_photos.clear()
        self._preview_index = 0
        self._progress["value"] = 0
        self._decode_status_var.set("")
        self._retry_btn.config(state=tk.DISABLED, fg="gray")
        self._clear_output()
        self._update_queue_label()
        self._update_nav_buttons()
        self._status_cb("已清空")

    def _clear_output(self):
        self._output.config(state=tk.NORMAL)
        self._output.delete("1.0", tk.END)
        self._output.config(state=tk.DISABLED)

    def _decode(self, enhance: bool = False):
        if not self._images:
            messagebox.showwarning("提示", "请先粘贴或加载截图")
            return
        self._status_cb(f"正在解码 {len(self._images)} 张截图...")
        self._decode_status_var.set("识别中...")
        self._progress["value"] = 0
        self._retry_btn.config(state=tk.DISABLED, fg="gray")
        self._clear_output()
        self.update_idletasks()

        self._decode_start_time = time.time()
        images_snapshot = list(self._images)
        threading.Thread(
            target=self._do_decode, args=(images_snapshot, enhance), daemon=True
        ).start()

    def _do_decode(self, images: list[Image.Image], enhance: bool):
        try:
            all_packets: list[dict] = []
            for i, img in enumerate(images):
                arr = preprocess_image(img, enhance=enhance)
                pkts = detect_and_decode_qrs(arr)
                all_packets.extend(pkts)
                pct = int((i + 1) / len(images) * 50)
                self.after(0, lambda p=pct: self._progress.configure(value=p))

            n = len(all_packets)
            if n == 0:
                self.after(0, self._on_decode_no_qr)
                return

            try:
                text = reassemble(all_packets)
                self.after(0, lambda t=text, _n=n: self._on_decode_success(t, _n))
            except MissingPacketError as e:
                _e = e
                self.after(0, lambda err=_e, _n=n: self._on_missing_packets(err, _n))
            except CRCError as e:
                _e = e
                self.after(0, lambda err=_e: self._on_crc_error(err))
            except ProtocolError as e:
                _e = e
                self.after(0, lambda err=_e: self._on_protocol_error(err))
        except Exception as e:
            _e = e
            self.after(0, lambda err=_e: self._on_decode_error(err))

    def _on_decode_success(self, text: str, n: int):
        self._progress["value"] = 100
        elapsed = time.time() - self._decode_start_time
        img_count = len(self._images)
        msg = (
            f"共 {img_count} 张截图，{n} 个QR码全部解码成功"
            f" — {len(text):,} 字符，耗时 {elapsed:.1f}s"
        )
        self._decode_status_var.set(msg)
        self._status_cb(f"解码完成：{len(text):,} 字符")
        self._retry_btn.config(state=tk.DISABLED, fg="gray")
        self._output.config(state=tk.NORMAL)
        self._output.delete("1.0", tk.END)
        self._output.insert("1.0", text)
        self._output.config(state=tk.DISABLED)

    def _on_decode_no_qr(self):
        self._progress["value"] = 0
        self._decode_status_var.set("未检测到 QR 码，请检查截图质量")
        self._status_cb("解码失败：未检测到 QR 码")
        self._retry_btn.config(state=tk.NORMAL, fg="orange")

    def _on_missing_packets(self, e: MissingPacketError, n: int):
        self._progress["value"] = int(n / (n + len(e.missing)) * 100)
        missing_labels = "、".join(f"第 {i + 1}" for i in e.missing)
        total_expected = n + len(e.missing)
        msg = (
            f"检测到 {n} / {total_expected} 个QR码，"
            f"{missing_labels} 个QR码未能识别，"
            f"请补截包含这些码的截图后重试"
        )
        self._decode_status_var.set(msg)
        self._status_cb(f"解码失败：缺失 {len(e.missing)} 个QR码")
        self._retry_btn.config(state=tk.NORMAL, fg="orange")

    def _on_crc_error(self, e: CRCError):
        self._decode_status_var.set("数据校验失败，请重新截图并解码")
        self._status_cb("解码失败：CRC 校验错误")
        self._retry_btn.config(state=tk.NORMAL, fg="orange")

    def _on_protocol_error(self, e: ProtocolError):
        self._decode_status_var.set(f"协议解析错误：{e}")
        self._status_cb("解码失败：协议错误")
        self._retry_btn.config(state=tk.NORMAL, fg="orange")

    def _on_decode_error(self, e: Exception):
        self._decode_status_var.set(f"解码出错：{e}")
        self._status_cb(f"解码出错：{e}")

    def _retry_enhanced(self):
        self._decode(enhance=True)

    def _copy_all(self):
        text = self._output.get("1.0", tk.END)
        if text.strip():
            self.clipboard_clear()
            self.clipboard_append(text)
            self._status_cb("已复制全部内容到剪贴板")
        else:
            messagebox.showinfo("提示", "没有可复制的内容")

    def _save_file(self):
        text = self._output.get("1.0", tk.END)
        if not text.strip():
            messagebox.showinfo("提示", "没有可保存的内容")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self._status_cb(f"已保存：{path}")

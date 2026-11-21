# Copyright (c) Opendatalab. All rights reserved.
"""
ah21 GUI：选择文件、method、lang，调用 demo_ah21.parse_doc。
开发：在仓库根目录用 .venv 运行  python gui_ah21.py
便携：由 RapidDoc_ah21.bat 启动。
"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from demo_ah21 import parse_doc

METHODS = ("auto", "txt", "ocr")
LANGS = ("ch", "chinese_cht", "en", "korean", "japan", "ta", "te", "ka")

FILE_TYPES = [
    ("文档 / 图片", "*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
    ("PDF", "*.pdf"),
    ("图片", "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp"),
    ("所有文件", "*.*"),
]


class Ah21App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RapidDoc ah21")
        self.minsize(560, 420)
        self.geometry("640x480")

        self._file_paths: list[Path] = []
        self._worker: threading.Thread | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()

        self._build_ui()
        self.after(200, self._drain_log_queue)

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)

        # 文件
        row0 = ttk.Frame(frm)
        row0.pack(fill=tk.X, **pad)
        ttk.Label(row0, text="输入文件").pack(side=tk.LEFT)
        ttk.Button(row0, text="清空", command=self._clear_files).pack(side=tk.RIGHT)
        ttk.Button(row0, text="选择…", command=self._pick_files).pack(side=tk.RIGHT, padx=(0, 6))

        self.files_var = tk.StringVar(value="（未选择）")
        ttk.Label(frm, textvariable=self.files_var, wraplength=600, justify=tk.LEFT).pack(
            fill=tk.X, **pad
        )

        # method / lang
        row1 = ttk.Frame(frm)
        row1.pack(fill=tk.X, **pad)
        ttk.Label(row1, text="method").pack(side=tk.LEFT)
        self.method_var = tk.StringVar(value="auto")
        ttk.Combobox(
            row1, textvariable=self.method_var, values=METHODS, state="readonly", width=12
        ).pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row1, text="lang").pack(side=tk.LEFT)
        self.lang_var = tk.StringVar(value="ch")
        ttk.Combobox(
            row1, textvariable=self.lang_var, values=LANGS, state="readonly", width=14
        ).pack(side=tk.LEFT, padx=(6, 0))

        # 输出目录
        row2 = ttk.Frame(frm)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="输出目录").pack(side=tk.LEFT)
        self.output_var = tk.StringVar()
        ttk.Entry(row2, textvariable=self.output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6
        )
        ttk.Button(row2, text="浏览…", command=self._pick_output).pack(side=tk.RIGHT)

        # 运行
        row3 = ttk.Frame(frm)
        row3.pack(fill=tk.X, **pad)
        self.run_btn = ttk.Button(row3, text="开始处理", command=self._start)
        self.run_btn.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(row3, textvariable=self.status_var).pack(side=tk.LEFT, padx=12)

        ttk.Label(
            frm,
            text="提示：首次运行需联网下载模型，可能较久，请耐心等待；之后会快很多。",
            wraplength=600,
            foreground="#555555",
        ).pack(fill=tk.X, **pad)

        # 日志
        ttk.Label(frm, text="日志").pack(anchor=tk.W, **pad)
        log_frame = ttk.Frame(frm)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=14, wrap=tk.WORD, state=tk.DISABLED)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.after(
            0,
            lambda: self._append_log(
                "提示：首次运行需联网下载模型，可能较久，请耐心等待；模型就绪后再次处理会快很多。"
            ),
        )

    def _append_log(self, msg: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg.rstrip() + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                msg = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log(msg)
        self.after(200, self._drain_log_queue)

    def _log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _pick_files(self) -> None:
        paths = filedialog.askopenfilenames(title="选择要解析的文件", filetypes=FILE_TYPES)
        if not paths:
            return
        self._file_paths = [Path(p) for p in paths]
        names = "；".join(p.name for p in self._file_paths)
        self.files_var.set(f"已选 {len(self._file_paths)} 个：{names}")
        if not self.output_var.get().strip():
            self.output_var.set(str(self._file_paths[0].parent))

    def _clear_files(self) -> None:
        self._file_paths = []
        self.files_var.set("（未选择）")

    def _pick_output(self) -> None:
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.output_var.set(d)

    def _start(self) -> None:
        if self._worker and self._worker.is_alive():
            messagebox.showinfo("提示", "正在处理中，请稍候。")
            return
        if not self._file_paths:
            messagebox.showwarning("提示", "请先选择输入文件。")
            return
        output_dir = self.output_var.get().strip()
        if not output_dir:
            messagebox.showwarning("提示", "请指定输出目录。")
            return
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        method = self.method_var.get()
        lang = self.lang_var.get()
        paths = list(self._file_paths)

        self.run_btn.configure(state=tk.DISABLED)
        self.status_var.set("处理中…")
        self._log("提示：若为首次运行，正在下载/加载模型时请耐心等待（需联网）。")
        self._log(f"开始：method={method} lang={lang} 文件数={len(paths)}")
        self._log(f"输出目录：{output_dir}")

        def work() -> None:
            t0 = time.time()
            ok = False
            try:
                parse_doc(paths, output_dir, method=method, lang=lang)
                ok = True
                self._log(f"完成，用时 {time.time() - t0:.1f} 秒")
            except Exception as e:
                self._log(f"失败：{e}")
            finally:
                self.after(0, lambda: self._on_done(ok))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _on_done(self, ok: bool) -> None:
        self.run_btn.configure(state=tk.NORMAL)
        self.status_var.set("完成" if ok else "失败")
        if ok:
            messagebox.showinfo("完成", "处理结束，请查看输出目录。")
        else:
            messagebox.showerror("失败", "处理失败，请查看日志。")


def main() -> None:
    app = Ah21App()
    app.mainloop()


if __name__ == "__main__":
    main()

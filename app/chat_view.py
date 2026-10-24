"""对话视图：流式输出、R1 思考过程折叠、参数生效、导出 Markdown。"""
from __future__ import annotations

import datetime as _dt
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

from . import sessions
from . import theme as th
from . import vision
from .i18n import t as T
from .widgets import PillButton, ScrollFrame


class Bubble(tk.Frame):
    """单条消息块：左侧色条 + 角色行 + 可选思考块 + 正文。"""

    def __init__(self, parent, role: str, title: str, color_key: str, accent: str,
                 on_copy=None, mono: bool = False):
        super().__init__(parent, bg=th.c(color_key), bd=0, highlightthickness=0)
        self.color_key = color_key
        self.role = role
        self._wrap = 600
        self._thinking_open = False

        bar = tk.Frame(self, bg=accent, width=4)
        bar.pack(side="left", fill="y")

        body = tk.Frame(self, bg=th.c(color_key), padx=14, pady=10)
        body.pack(side="left", fill="both", expand=True)
        self.body = body

        head = tk.Frame(body, bg=th.c(color_key))
        head.pack(fill="x")
        self.title_label = tk.Label(head, text=title, bg=th.c(color_key), fg=accent,
                                    font=th.F(10, "bold"), anchor="w")
        self.title_label.pack(side="left")
        self.meta_label = tk.Label(head, text="", bg=th.c(color_key), fg=th.c("text_faint"),
                                   font=th.F(8), anchor="w")
        self.meta_label.pack(side="left", padx=(8, 0))
        self.copy_btn = PillButton(head, T("chat.copy"), command=on_copy or (lambda: None),
                                   kind="ghost", height=24, radius=7, font=th.F(8), pad=10)
        self.copy_btn.pack(side="right")

        # ---- 思考块（仅助手消息使用）
        self.think_head = tk.Frame(body, bg=th.c(color_key))
        self.think_toggle = tk.Label(self.think_head, text="", bg=th.c(color_key),
                                     fg=th.c("think_text"), font=th.F(9, "bold"),
                                     cursor="hand2", anchor="w")
        self.think_toggle.pack(side="left")
        self.think_toggle.bind("<Button-1>", lambda _e: self.toggle_thinking())
        self.think_box = tk.Frame(body, bg=th.c("bubble_think"), padx=10, pady=8)
        self.think_label = tk.Label(self.think_box, text="", bg=th.c("bubble_think"),
                                    fg=th.c("think_text"), font=th.F(9), justify="left",
                                    anchor="w", wraplength=self._wrap)
        self.think_label.pack(fill="x")
        self._thinking_text = ""

        self.text_label = tk.Label(body, text="", bg=th.c(color_key), fg=th.c("text"),
                                   font=th.MONO(10) if mono else th.F(10), justify="left",
                                   anchor="w", wraplength=self._wrap)
        self.text_label.pack(fill="x", pady=(2, 0))
        self._text = ""

        # ---- 图片附件区（识图）
        self.images_row = tk.Frame(body, bg=th.c(color_key))
        self._images: list = []
        self._photos: list = []
        self.sources_head = tk.Frame(body, bg=th.c(color_key))
        self.sources_toggle = tk.Label(self.sources_head, text="", bg=th.c(color_key),
                                       fg=th.c("accent"), font=th.F(9, "bold"),
                                       cursor="hand2", anchor="w")
        self.sources_toggle.pack(side="left")
        self.sources_toggle.bind("<Button-1>", lambda _e: self.toggle_sources())
        self.sources_box = tk.Frame(body, bg=th.c("card_alt"), padx=10, pady=8)
        self._sources: list[dict] = []
        self._sources_open = False
        self._material = ""

    def set_material(self, text: str):
        """保存本次注入模型的完整资料（供“查看资料”按钮展示）。"""
        self._material = text or ""
        if self._sources:
            self.set_sources(self._sources)      # 重新渲染以带上按钮

    def _open_material(self):
        from .widgets import show_text

        show_text(self.winfo_toplevel(), T("material.title"), self._material,
                  T("material.hint"))

    # ------------------------------------------------ 参考来源
    def set_sources(self, sources: list):
        self._sources = list(sources or [])
        for child in self.sources_box.winfo_children():
            child.destroy()
        if not self._sources:
            self.sources_head.pack_forget()
            self.sources_box.pack_forget()
            return
        for idx, item in enumerate(self._sources, 1):
            url = item.get("url", "")
            row = tk.Frame(self.sources_box, bg=th.c("card_alt"))
            row.pack(fill="x", pady=1)
            title = tk.Label(row, text=f"[{idx}] {item.get('title') or url}",
                             bg=th.c("card_alt"), fg=th.c("accent"), font=th.F(9),
                             anchor="w", justify="left", cursor="hand2",
                             wraplength=max(220, self._wrap - 30))
            title.pack(fill="x")
            host = tk.Label(row, text=url, bg=th.c("card_alt"), fg=th.c("text_faint"),
                            font=th.F(7), anchor="w", justify="left", cursor="hand2",
                            wraplength=max(220, self._wrap - 30))
            host.pack(fill="x")
            for widget in (title, host):
                widget.bind("<Button-1>", lambda _e, u=url: self._open_link(u))
        tk.Label(self.sources_box, text=T("chat.sources_hint"), bg=th.c("card_alt"),
                 fg=th.c("text_faint"), font=th.F(7), anchor="w").pack(fill="x", pady=(6, 0))
        if self._material:
            row = tk.Frame(self.sources_box, bg=th.c("card_alt"))
            row.pack(fill="x", pady=(6, 0))
            PillButton(row, T("chat.view_material"), kind="ghost", height=26, radius=7,
                       font=th.F(8), bg=th.c("card_alt"),
                       command=self._open_material).pack(side="left")
        self._sync_sources_head()
        if self._sources_open:
            self.sources_box.pack(fill="x", pady=(4, 6))
        self.after(30, self._grow)

    @staticmethod
    def _open_link(url: str):
        if not url:
            return
        try:
            from .winopen import open_url
            open_url(url)
        except Exception:
            pass

    def _grow(self):
        """让父级滚动区域重新计算高度。"""
        try:
            self.master.event_generate("<Configure>")
        except Exception:
            pass


    def _sync_sources_head(self):
        if not self._sources:
            self.sources_head.pack_forget()
            return
        if not self.sources_head.winfo_ismapped():
            self.sources_head.pack(fill="x", pady=(8, 0))
        state = T("chat.collapse") if self._sources_open else T("chat.expand")
        self.sources_toggle.configure(
            text=f"◈ {T('chat.sources')} · {len(self._sources)} · {state}")

    def toggle_sources(self):
        self._sources_open = not self._sources_open
        if self._sources_open:
            self.sources_box.pack(fill="x", pady=(4, 6))
        else:
            self.sources_box.pack_forget()
        self._sync_sources_head()

    # ------------------------------------------------ 内容
    def set_text(self, text: str):
        self._text = text or ""
        self.text_label.configure(text=self._text)

    def append_text(self, chunk: str):
        self._text += chunk
        self.text_label.configure(text=self._text)

    def get_text(self) -> str:
        return self._text

    # ------------------------------------------------ 图片（识图）
    def set_images(self, thumbs: list):
        """在气泡内渲染图片缩略图（base64 列表）。"""
        self._images = list(thumbs or [])
        for child in self.images_row.winfo_children():
            child.destroy()
        self._photos.clear()
        if not self._images:
            self.images_row.pack_forget()
            return
        for b64 in self._images[:4]:
            photo = vision.photo_for(b64)
            if photo is None:
                continue
            self._photos.append(photo)
            tk.Label(self.images_row, image=photo, bd=0,
                     bg=th.c(self.color_key)).pack(side="left", padx=(0, 6), pady=(6, 0))
        if self._photos:
            self.images_row.pack(fill="x", anchor="w", before=self.text_label)


    def set_thinking(self, text: str):
        self._thinking_text = text
        self.think_label.configure(text=text)
        self._sync_think_head()

    def append_thinking(self, chunk: str):
        self._thinking_text += chunk
        self.think_label.configure(text=self._thinking_text)
        self._sync_think_head()


    def has_thinking(self) -> bool:
        return bool(self._thinking_text.strip())

    def _sync_think_head(self):
        if self.has_thinking():
            if not self.think_head.winfo_ismapped():
                self.think_head.pack(fill="x", pady=(6, 0), before=self.text_label)
            state = T("chat.collapse") if self._thinking_open else T("chat.expand")
            self.think_toggle.configure(text=f"◆ {T('chat.thinking')} · {state}")
        else:
            self.think_head.pack_forget()
            self.think_box.pack_forget()

    def toggle_thinking(self):
        self._thinking_open = not self._thinking_open
        if self._thinking_open:
            self.think_box.pack(fill="x", pady=(4, 6), before=self.text_label)
        else:
            self.think_box.pack_forget()
        self._sync_think_head()

    def set_meta(self, text: str):
        self.meta_label.configure(text=text)

    def set_wrap(self, width: int):
        self._wrap = max(200, width - 60)
        self.text_label.configure(wraplength=self._wrap)
        self.think_label.configure(wraplength=self._wrap)
        for row in self.sources_box.winfo_children():
            for child in row.winfo_children():
                try:
                    child.configure(wraplength=max(220, self._wrap - 30))
                except Exception:
                    pass

    def apply_theme(self):
        bg = th.c(self.color_key)
        self.configure(bg=bg)
        for widget in (self.body,):
            widget.configure(bg=bg)
        for child in self.body.winfo_children():
            if isinstance(child, tk.Frame) and child is not self.think_box:
                child.configure(bg=bg)
        self.title_label.configure(bg=bg)
        self.meta_label.configure(bg=bg)
        self.think_head.configure(bg=bg)
        self.think_toggle.configure(bg=bg, fg=th.c("think_text"))
        self.think_box.configure(bg=th.c("bubble_think"))
        self.think_label.configure(bg=th.c("bubble_think"), fg=th.c("think_text"))
        self.text_label.configure(bg=bg, fg=th.c("text"))
        self.sources_head.configure(bg=bg)
        self.sources_toggle.configure(bg=bg, fg=th.c("accent"))
        self.sources_box.configure(bg=th.c("card_alt"))
        for row in self.sources_box.winfo_children():
            try:
                row.configure(bg=th.c("card_alt"))
            except Exception:
                continue
            for child in row.winfo_children():
                try:
                    child.configure(bg=th.c("card_alt"))
                except Exception:
                    pass
        self.copy_btn.apply_theme(bg)
        accent = th.c("accent") if self.role == "assistant" else th.c("chip_text")
        self.title_label.configure(fg=accent)
        for child in self.winfo_children():
            if isinstance(child, tk.Frame) and child.cget("width") == 4:
                child.configure(bg=accent)


class ChatView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=th.c("card"), bd=0, highlightthickness=0)
        self.app = app
        self.records: list[dict] = []      # {role, content, thinking, meta, sources}
        self.bubbles: list[Bubble] = []
        self.generating = False
        self.queue: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._search_meta = ""
        self.session_id = ""
        self.session_title = ""
        self._save_job = None
        self.attachments: list[dict] = []      # 待发送的图片
        self._build()
        self._sync_web_btn()

    # ------------------------------------------------ 会话（保存/载入）
    def new_session(self, notify: bool = True):
        """开一段新对话（旧对话已自动保存）。"""
        if self.generating:
            self.cancel.set()
            self.generating = False
        self.records.clear()
        self.scroll.clear()
        self.bubbles.clear()
        self._show_empty(True)
        self._set_busy_title(None)
        self.send_btn.set_text(T("chat.send"))
        self.send_btn.set_kind("primary")
        self.session_id = sessions.new_id()
        self.session_title = ""
        self.app.on_session_changed(self.session_id)
        if notify:
            self.app.toast(T("sessions.new_started"))

    def load_session(self, session_id: str, notify: bool = True) -> bool:
        data = self.app.sessions.load(session_id)
        if not data:
            return False
        if self.generating:
            self.cancel.set()
            self.generating = False
            self.send_btn.set_text(T("chat.send"))
            self.send_btn.set_kind("primary")
        self.session_id = data.get("id") or session_id
        self.session_title = data.get("title") or ""
        self.records = [dict(m) for m in (data.get("messages") or [])]
        self._render_records()
        self.app.on_session_changed(self.session_id)
        if notify:
            self.app.toast(T("sessions.loaded", self.session_title or T("sessions.untitled")))
        return True

    def _render_records(self):
        """按 records 重建全部气泡（载入历史对话时使用）。"""
        self.scroll.clear()
        self.bubbles.clear()
        for rec in self.records:
            bubble = self._add_bubble(rec.get("role", "assistant"), "")
            if rec.get("thumbs"):
                bubble.set_images(rec["thumbs"])
            if rec.get("thinking"):
                bubble.set_thinking(rec["thinking"])
            bubble.set_text(rec.get("content") or "")
            if rec.get("sources"):
                bubble.set_sources(rec["sources"])
            if rec.get("meta"):
                bubble.set_meta(rec["meta"])
        self._show_empty(not self.records)
        self.after(60, self.scroll.scroll_bottom)

    def _autosave(self, delay: int = 1200):
        if self._save_job:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.after(delay, self.save_session)

    def save_session(self, notify: bool = False) -> bool:
        """把当前对话写入本地会话文件。"""
        self._save_job = None
        if not self.records:
            return False
        if not self.session_id:
            self.session_id = sessions.new_id()
        if not self.session_title:
            self.session_title = sessions.title_from(self.records) or T("sessions.untitled")
        payload = {
            "id": self.session_id,
            "title": self.session_title,
            "model": self.app.current_model,
            "messages": self.records,
        }
        self.app.sessions.save(payload)
        self.app.refresh_sessions()
        if notify:
            self.app.toast(T("sessions.saved"))
        return True

    # ------------------------------------------------ 构建
    def _build(self):
        head = tk.Frame(self, bg=th.c("card"))
        head.pack(fill="x", padx=18, pady=(16, 8))
        self.title = tk.Label(head, text=T("chat.title"), bg=th.c("card"), fg=th.c("text"),
                              font=th.F(15, "bold"))
        self.title.pack(side="left")
        self.export_btn = PillButton(head, T("chat.export"), command=self.export_markdown,
                                     kind="ghost", height=30, radius=9)
        self.export_btn.pack(side="right")
        self.clear_btn = PillButton(head, T("sessions.new"), command=self.new_chat,
                                    kind="ghost", height=30, radius=9)
        self.clear_btn.pack(side="right", padx=(0, 8))
        self.web_btn = PillButton(head, "", command=self.toggle_web_search,
                                  kind="ghost", height=30, radius=9)
        self.web_btn.pack(side="right", padx=(0, 8))

        self.scroll = ScrollFrame(self, bg_key="card", padding=0)
        self.scroll.pack(fill="both", expand=True, padx=10)
        self.scroll.inner.configure(padx=8)
        self.scroll.canvas.bind("<Configure>", self._on_scroll_resize, add="+")

        self.empty_label = tk.Label(self, text=T("chat.empty"), bg=th.c("card"),
                                    fg=th.c("text_faint"), font=th.F(10),
                                    justify="center", wraplength=460)
        self._show_empty(True)

        bottom = tk.Frame(self, bg=th.c("card"))
        bottom.pack(fill="x", padx=18, pady=(8, 16))
        self.bottom = bottom

        # 已附加图片的预览条
        self.attach_strip = tk.Frame(bottom, bg=th.c("card"))
        self.attach_photos: list = []

        holder = tk.Frame(bottom, bg=th.c("card_alt"), highlightthickness=1,
                          highlightbackground=th.c("border"), highlightcolor=th.c("accent"))
        holder.pack(fill="x")
        self.input = tk.Text(holder, height=3, wrap="word", bd=0, relief="flat",
                             bg=th.c("card_alt"), fg=th.c("text"),
                             insertbackground=th.c("accent"), font=th.F(10),
                             padx=12, pady=10, highlightthickness=0)
        self.input.pack(fill="x")
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Shift-Return>", lambda _e: None)
        self.input.bind("<Control-Return>", lambda _e: (self.send(), "break")[1])
        self.input.bind("<Control-v>", self._on_paste)
        self.input.bind("<Control-V>", self._on_paste)

        row = tk.Frame(bottom, bg=th.c("card"))
        row.pack(fill="x", pady=(8, 0))
        self.hint = tk.Label(row, text=T("chat.input_hint"), bg=th.c("card"),
                             fg=th.c("text_faint"), font=th.F(8))
        self.hint.pack(side="left")
        self.send_btn = PillButton(row, T("chat.send"), command=self.send, kind="primary",
                                   height=36, radius=10, min_width=108)
        self.send_btn.pack(side="right")
        self.image_btn = PillButton(row, T("vision.attach"), command=self.attach_image,
                                    kind="ghost", height=36, radius=10)
        self.image_btn.pack(side="right", padx=(0, 8))
        self.attach_hint = tk.Label(row, text=T("vision.attach_hint"), bg=th.c("card"),
                                    fg=th.c("text_faint"), font=th.F(7))
        self.attach_hint.pack(side="right", padx=(0, 10))

    def _on_scroll_resize(self, event):
        width = event.width
        for bubble in self.bubbles:
            bubble.set_wrap(width)

    def _show_empty(self, show: bool):
        if show:
            self.empty_label.place(relx=0.5, rely=0.42, anchor="center")
        else:
            self.empty_label.place_forget()

    # ------------------------------------------------ 联网搜索开关
    @property
    def search_mode(self) -> str:
        cfg = self.app.cfg.get("search") or {}
        mode = cfg.get("mode")
        if mode not in ("off", "quick", "deep"):
            mode = "quick" if cfg.get("enabled") else "off"
        return mode

    @property
    def web_enabled(self) -> bool:
        return self.search_mode != "off"

    def toggle_web_search(self):
        """三态循环：关 → 快（单查询） → 深（多查询/多引擎/批量抓正文）。"""
        order = ("off", "quick", "deep")
        nxt = order[(order.index(self.search_mode) + 1) % len(order)]
        search_cfg = self.app.cfg.setdefault("search", {})
        search_cfg["mode"] = nxt
        search_cfg["enabled"] = nxt != "off"
        self.app.save_cfg()
        self._sync_web_btn()
        self.app.toast(f"{T('chat.web_search')} · {self._mode_label(nxt)}")
        self.app.log_event("INFO", f"search mode -> {nxt}")

    @staticmethod
    def _mode_label(mode: str) -> str:
        return {"off": T("chat.off"), "quick": T("chat.mode_quick"),
                "deep": T("chat.mode_deep")}.get(mode, T("chat.off"))

    def _sync_web_btn(self):
        mode = self.search_mode
        self.web_btn.set_text(f"{T('chat.web_search')} · {self._mode_label(mode)}")
        self.web_btn.set_kind("primary" if mode != "off" else "ghost")

    # ------------------------------------------------ 图片附件（识图）
    MAX_IMAGES = 3

    def attach_image(self):
        if not vision.HAS_PIL:
            self.app.toast(T("vision.no_pillow"))
            return
        paths = filedialog.askopenfilenames(
            parent=self.winfo_toplevel(),
            title=T("vision.attach"),
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff"),
                       ("All files", "*.*")],
        )
        for path in paths or ():
            self._add_attachment(path)

    def _on_paste(self, _event=None):
        """Ctrl+V：输入框里若已有文字正常粘贴，否则尝试粘贴剪贴板图片。"""
        try:
            has_text = bool(self.clipboard_get())
        except Exception:
            has_text = False
        if has_text:
            return None
        data = vision.from_clipboard()
        if data:
            self._attach_data(data)
            return "break"
        return None

    def _add_attachment(self, path: str):
        try:
            data = vision.load_path(path)
        except Exception as exc:
            self.app.toast(T("vision.load_failed", exc))
            return
        self._attach_data(data)

    def _attach_data(self, data: dict):
        if len(self.attachments) >= self.MAX_IMAGES:
            self.app.toast(T("vision.too_many", self.MAX_IMAGES))
            return
        self.attachments.append(data)
        self._render_attachments()
        self.app.toast(T("vision.attached", len(self.attachments)))

    def _remove_attachment(self, index: int):
        if 0 <= index < len(self.attachments):
            self.attachments.pop(index)
        self._render_attachments()

    def _clear_attachments(self):
        self.attachments.clear()
        self._render_attachments()

    def _render_attachments(self):
        for child in self.attach_strip.winfo_children():
            child.destroy()
        self.attach_photos.clear()
        if not self.attachments:
            self.attach_strip.pack_forget()
            return
        self.attach_strip.pack(fill="x", pady=(0, 6), before=self.input.master)
        for idx, item in enumerate(self.attachments):
            holder = tk.Frame(self.attach_strip, bg=th.c("card_alt"), padx=4, pady=4)
            holder.pack(side="left", padx=(0, 8))
            photo = vision.photo_for(item.get("thumb", ""))
            if photo is not None:
                self.attach_photos.append(photo)
                tk.Label(holder, image=photo, bd=0, bg=th.c("card_alt")).pack()
            info = tk.Frame(holder, bg=th.c("card_alt"))
            info.pack(fill="x")
            tk.Label(info, text=f"{item.get('w')}×{item.get('h')}", bg=th.c("card_alt"),
                     fg=th.c("text_faint"), font=th.F(7)).pack(side="left")
            close = tk.Label(info, text="✕", bg=th.c("card_alt"), fg=th.c("err"),
                             font=th.F(8), cursor="hand2")
            close.pack(side="right", padx=(6, 0))
            close.bind("<Button-1>", lambda _e, i=idx: self._remove_attachment(i))

    # ------------------------------------------------ 视觉模型
    def views_models_open_downloader(self):
        """复用模型页的「下载模型…」入口（含打不开时的剪贴板兜底）。"""
        view = self.app.views.get("models")
        if view is not None and hasattr(view, "open_downloader"):
            view.open_downloader()
            return
        from .winopen import open_url

        open_url("https://github.com/a-j5611/AI-Downloader-for-Ollama")

    def _vision_ready(self) -> bool:
        """确认当前模型能识图；不能则尝试切换或引导下载。"""
        model = self.app.current_model
        cache = getattr(self.app, "_vision_cache", None)
        if cache is None:
            cache = self.app._vision_cache = {}
        if model not in cache:
            try:
                cache[model] = self.app.client.has_vision(model)
            except Exception:
                cache[model] = False
        if cache.get(model):
            return True
        # 本地是否已有其它视觉模型
        try:
            names = [m.get("name", "") for m in self.app.client.tags()]
        except Exception:
            names = []
        for name in names:
            if name == model:
                continue
            if name not in cache:
                try:
                    cache[name] = self.app.client.has_vision(name)
                except Exception:
                    cache[name] = False
            if cache[name]:
                self.app.set_model(name)
                self.app.toast(T("vision.ready", name))
                self.app.log_event("INFO", f"auto-switch to vision model {name}")
                return True
        # 都没有 → 引导下载
        action, chosen = vision.VisionDialog(self.winfo_toplevel(), model).result
        if action == "gallery":
            self.views_models_open_downloader()
        elif action == "download" and chosen:
            self._download_vision(chosen)
        return False


    def _on_return(self, event):
        if event.state & 0x0001:      # Shift
            return None
        self.send()
        return "break"

    def _ensure_model(self) -> str:
        """确认当前模型仍然存在；不存在时自动回退到本地任一模型。

        （用户可能在模型页删掉了正在使用的模型，此时若直接用旧名字请求
          Ollama 只会得到 404，看起来就像“发消息没反应”。）
        """
        model = self.app.current_model
        try:
            names = [m.get("name", "") for m in self.app.client.tags()]
        except Exception:
            return model                      # 服务不可用时照旧，让请求自己报错
        if model and model in names:
            return model
        if names:
            self.app.set_model(names[0])
            self.app.log_event("WARN", f"model {model!r} missing -> {names[0]!r}")
            self.app.toast(T("chat.model_gone", model or "-", names[0]))
            return names[0]
        self.app.toast(T("chat.model_missing", model or "-"))
        return ""

    def send(self):
        if self.generating:
            return "break"
        text = self.input.get("1.0", "end").strip()
        images = list(self.attachments)
        if not text and not images:
            return "break"
        model = self._ensure_model()
        if not model:
            self.app.toast(T("chat.need_model"))
            return "break"
        if images and not self._vision_ready():
            return "break"
        # 视觉检查可能已把模型切换到视觉模型，这里必须重新取一次当前模型，
        # 否则图片会被发往旧的纯文本模型（表现为 500 image input is not supported）
        model = self.app.current_model or model
        if not model:
            self.app.toast(T("chat.need_model"))
            return "break"

        self.input.delete("1.0", "end")
        self._show_empty(False)
        bubble = self._add_bubble("user", text)
        if images:
            bubble.set_images([img.get("thumb", "") for img in images])
        record = {"role": "user", "content": text, "thinking": "", "meta": "",
                  "sources": [], "images": [img.get("hist", "") for img in images],
                  "thumbs": [img.get("thumb", "") for img in images],
                  "images_meta": [{"name": img.get("name", ""), "w": img.get("w"),
                                   "h": img.get("h")} for img in images]}
        self.records.append(record)
        self._clear_attachments()
        self._start_stream(model, search_query=text if (self.web_enabled and text) else None)
        self._autosave(400)          # 先把标题/首条消息存下来
        return "break"

    def _add_bubble(self, role: str, text: str = "") -> Bubble:
        if role == "user":
            bubble = Bubble(self.scroll.inner, "user", T("chat.you"), "bubble_user",
                            th.c("chip_text"), on_copy=lambda b=None: None)
        else:
            bubble = Bubble(self.scroll.inner, "assistant", T("chat.ai"), "bubble_ai",
                            th.c("accent"), on_copy=lambda b=None: None)
        bubble.pack(fill="x", padx=4, pady=6)
        bubble.set_wrap(self.scroll.canvas.winfo_width())
        bubble.set_text(text)
        idx = len(self.bubbles)
        bubble.copy_btn._command = lambda i=idx: self._copy_bubble(i)
        self.bubbles.append(bubble)
        self.after(30, self.scroll.scroll_bottom)
        return bubble

    def _copy_bubble(self, index: int):
        if index >= len(self.bubbles):
            return
        self.clipboard_clear()
        self.clipboard_append(self.bubbles[index].get_text())
        self.app.toast(T("chat.copied"))

    def _start_stream(self, model: str, search_query: str | None = None):
        params = self.app.cfg.get("params", {})
        options = {
            "temperature": float(params.get("temperature", 0.6)),
            "top_p": float(params.get("top_p", 0.95)),
            "num_thread": int(params.get("num_thread", 14)),
            "num_ctx": int(params.get("num_ctx", 4096)),
            "num_predict": int(params.get("num_predict", -1)),
        }
        messages = []
        last_user = max((i for i, r in enumerate(self.records) if r["role"] == "user"),
                        default=-1)
        for idx, rec in enumerate(self.records):
            item = {"role": rec["role"], "content": rec["content"]}
            # 只在最后一轮用户消息里带上图片：历史图片会让 prompt 变得很长很慢
            if idx == last_user and rec.get("images"):
                item["images"] = list(rec["images"])
            messages.append(item)
        self._assistant_bubble = self._add_bubble("assistant", "")
        self._assistant_record = {"role": "assistant", "content": "", "thinking": "",
                                  "meta": "", "sources": []}
        self._search_meta = ""
        self.records.append(self._assistant_record)

        self.generating = True
        self.cancel.clear()
        self.send_btn.set_text(T("chat.stop"))
        self.send_btn.set_kind("danger")
        self._set_busy_title(T("chat.generating"))

        client = self.app.client
        q = self.queue
        cancel = self.cancel
        search_cfg = dict(self.app.cfg.get("search") or {})
        search_mode = self.search_mode

        def worker():
            payload = list(messages)
            options_run = dict(options)
            if search_query and search_mode != "off":
                q.put(("searching", search_mode))
                results: list = []
                try:
                    from . import websearch

                    if search_mode == "deep":
                        data = websearch.deep_search(
                            search_query, search_cfg, client=client, model=model,
                            progress=lambda step, info=None: q.put(("search_step", (step, info))))
                        results = data.get("results") or []
                        stats = data.get("stats") or {}
                        q.put(("sources", (results, f"deep/{stats.get('queries', 0)}q")))
                    else:
                        stats = {}
                        results, used = websearch.search(
                            search_query,
                            backend=search_cfg.get("backend", "auto"),
                            count=int(search_cfg.get("count", 6) or 6),
                        )
                        pages = int(search_cfg.get("pages", 0) or 0)
                        if pages != 0 and results:
                            websearch.enrich(
                                results,
                                want=(len(results) if pages < 0 else pages),
                                max_chars=int(search_cfg.get("page_chars", 2000) or 0),
                                timeout=12, max_try=len(results))
                        q.put(("sources", (results, used)))
                    if results and not cancel.is_set():
                        context = websearch.build_context(
                            results,
                            max_chars=int(search_cfg.get("context_chars", 2000) or 0))
                        # 资料很大时自动提升上下文，否则会被悄悄截断
                        need = (websearch.estimate_tokens(context)
                                + max(512, int(options_run.get("num_predict", -1) or 0)
                                      if int(options_run.get("num_predict", -1) or 0) > 0 else 1024)
                                + 256)
                        current = int(options_run.get("num_ctx", 4096) or 4096)
                        if search_cfg.get("auto_ctx", True) and need > current:
                            target = 1 << max(0, (need - 1).bit_length())
                            target = max(current, min(target,
                                                      int(search_cfg.get("max_ctx", 32768) or 32768)))
                            options_run["num_ctx"] = target
                            q.put(("ctx_raised", target))
                        q.put(("material", context))
                        q.put(("search_stats", (stats, len(context))))
                        payload = [{"role": "system",
                                    "content": websearch.SEARCH_SYSTEM_PROMPT.format(context=context)}] + payload
                except Exception as exc:
                    q.put(("search_error", str(exc)))
                    if results:
                        q.put(("sources", (results, "")))
            if cancel.is_set():
                q.put(("done", None))
                return
            # 先把模型加载好，避免刚切换模型时出现一次性 500
            got_any = False
            has_images = any(m.get("images") for m in payload)
            # 文本模型可以先预热，避免刚切换模型时的一次性 500
            warmable = not has_images
            if warmable:
                try:
                    warmable = not self.app.client.has_vision(model)
                except Exception:
                    warmable = False

            last_error = ""
            for attempt in (1, 2, 3):
                try:
                    if warmable and attempt == 1:
                        client.warmup(model)
                    for chunk in client.chat_stream(model, payload, options_run):
                        if cancel.is_set():
                            break
                        got_any = True
                        q.put(("chunk", chunk))
                    last_error = ""
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if cancel.is_set() or got_any:
                        break
                    low = last_error.lower()
                    if attempt < 3 and ("mmproj" in low or "image input" in low):
                        # 视觉模型刚下载完时首次加载可能拿不到投影层；
                        # 先用文本方式把它加载好，再重试图片请求。
                        client.warmup(model)
                        time.sleep(1.2)
                        continue
                    if attempt == 1:
                        time.sleep(1.5)          # 常见的切换竞态，退避后重试
                        continue
                    break
            if last_error and not got_any:
                q.put(("error", last_error))
            q.put(("done", None))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()
        self.after(40, self._poll)

    def _poll(self):
        if not self._alive():
            return
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        if self.generating and self._alive():
            self.after(40, self._poll)

    def _alive(self) -> bool:
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _handle_event(self, kind: str, payload):
        if kind == "searching":
            mode = payload if isinstance(payload, str) else "quick"
            self._assistant_bubble.set_meta(
                T("chat.search_expanding") if mode == "deep" else T("chat.searching"))
        elif kind == "search_step":
            step, info = payload if isinstance(payload, tuple) else (payload, None)
            text = {"expand": T("chat.search_expanding"),
                    "search": T("chat.search_queries", info or 0),
                    "fetch": T("chat.search_fetching", info or 0)}.get(step, T("chat.searching"))
            self._assistant_bubble.set_meta(text)
        elif kind == "material":
            self._assistant_bubble.set_material(payload)
        elif kind == "search_stats":
            stats, chars = payload if isinstance(payload, tuple) else (payload, 0)
            if stats:
                self._search_meta = T("chat.search_stats", stats.get("queries", 0),
                                      stats.get("merged", 0), stats.get("pages", 0),
                                      (chars or 0) / 1000.0)
                self._assistant_bubble.set_meta(self._search_meta)
                self.app.log_event("INFO", f"deep search: {stats}")
        elif kind == "ctx_raised":
            self.app.log_event("INFO", f"num_ctx auto -> {payload}")
            self.app.toast(T("chat.ctx_raised", payload))
        elif kind == "sources":
            self._on_sources(payload)
        elif kind == "search_error":
            self.app.log_event("ERROR", f"websearch: {payload}")
            self.app.toast(T("chat.search_failed", payload))
        elif kind == "chunk":
            self._on_chunk(payload)
        elif kind == "error":
            self.app.log_event("ERROR", f"chat: {payload}")
            self.app.toast(T("chat.error", payload))
            self._finish_stream()
        elif kind == "done":
            self._finish_stream()

    def _on_sources(self, payload):
        results, used = payload
        self._assistant_record["sources"] = list(results or [])
        self._assistant_bubble.set_sources(results or [])
        if results:
            self._search_meta = T("chat.sources_n", len(results))
            self._assistant_bubble.set_meta(self._search_meta)
            self.app.log_event("INFO", f"websearch: {len(results)} results via {used or '-'}")
        else:
            self._search_meta = T("chat.no_result")
            self._assistant_bubble.set_meta(self._search_meta)

    def _on_chunk(self, chunk: dict):
        stay = self.scroll.at_bottom()
        message = chunk.get("message") or {}
        thinking = message.get("thinking") or ""
        content = message.get("content") or ""
        if thinking:
            self._assistant_bubble.append_thinking(thinking)
            self._assistant_record["thinking"] += thinking
        if content:
            self._assistant_bubble.append_text(content)
            self._assistant_record["content"] += content
        if chunk.get("done"):
            count = chunk.get("eval_count") or 0
            dur = chunk.get("eval_duration") or 0
            token_meta = T("chat.meta", n=count, tps=round(count / (dur / 1e9), 2)) if (count and dur) else ""
            parts = [p for p in (getattr(self, "_search_meta", ""), token_meta) if p]
            meta = " · ".join(parts)
            self._assistant_bubble.set_meta(meta)
            self._assistant_record["meta"] = meta
        if stay:
            self.scroll.scroll_bottom()
        else:
            self.scroll.canvas.update_idletasks()

    def _finish_stream(self):
        self.generating = False
        self.send_btn.set_text(T("chat.send"))
        self.send_btn.set_kind("primary")
        self._set_busy_title(None)
        if self.cancel.is_set() and not self._assistant_record["content"]:
            self._assistant_bubble.set_text(T("chat.stopped"))
        self._autosave(600)          # 回答完成后落盘

    def _set_busy_title(self, text: str | None):
        self.title.configure(text=text or T("chat.title"), fg=th.c("warn") if text else th.c("text"))

    def stop(self):
        if self.generating:
            self.cancel.set()
            self.app.toast(T("chat.stopped"))

    def new_chat(self):
        """新建对话（当前对话会自动保存到左侧列表）。"""
        if self.records:
            self.save_session()
        self.new_session()

    # 兼容旧调用名
    clear_chat = new_chat

    # ------------------------------------------------ 导出
    def export_markdown(self):
        if not self.records:
            self.app.toast(T("chat.export_empty"))
            return
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        initial_dir = self.app.cfg.get("export_dir") or os.path.expanduser("~")
        path = filedialog.asksaveasfilename(
            parent=self.winfo_toplevel(),
            title=T("chat.export_title"),
            initialdir=initial_dir,
            initialfile=f"ai-chat-{stamp}.md",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        self.app.cfg["export_dir"] = os.path.dirname(path)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._to_markdown())
        except Exception as exc:
            self.app.toast(T("chat.error", exc))
            return
        self.app.log_event("INFO", f"export -> {path}")
        self.app.toast(T("chat.export_done", path))

    def _to_markdown(self) -> str:
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "# AI Chat 对话记录 / Conversation",
            "",
            f"- 模型 Model: `{self.app.current_model}`",
            f"- 导出时间 Exported: {now}",
            f"- 消息数 Messages: {len(self.records)}",
            "",
            "---",
            "",
        ]
        for rec in self.records:
            who = T("chat.you") if rec["role"] == "user" else T("chat.ai")
            lines.append(f"## {who}")
            lines.append("")
            metas = rec.get("images_meta") or []
            if metas:
                names = ", ".join(f"{m.get('name','image')} ({m.get('w')}×{m.get('h')})"
                                  for m in metas)
                lines.append(f"> [{T('vision.attach')}] {names}")
                lines.append("")
            if rec.get("thinking"):
                lines.append("<details>")
                lines.append(f"<summary>{T('chat.thinking')} ({len(rec['thinking'])} chars)</summary>")
                lines.append("")
                lines.append(rec["thinking"].strip())
                lines.append("")
                lines.append("</details>")
                lines.append("")
            lines.append((rec.get("content") or "").strip())
            lines.append("")
            sources = rec.get("sources") or []
            if sources:
                lines.append(f"**{T('chat.sources')} / Sources**")
                lines.append("")
                for idx, item in enumerate(sources, 1):
                    title = (item.get("title") or "").replace("]", ")")
                    lines.append(f"{idx}. [{title}]({item.get('url','')})")
                lines.append("")
            if rec.get("meta"):
                lines.append(f"*{rec['meta']}*")
                lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------ 主题 / 语言
    def apply_theme(self):
        self.configure(bg=th.c("card"))
        for frame in (self.scroll,):
            frame.apply_theme("card")
        for bubble in self.bubbles:
            bubble.apply_theme()
        self.title.configure(bg=th.c("card"), fg=th.c("text"))
        self.empty_label.configure(bg=th.c("card"), fg=th.c("text_faint"))
        for btn in (self.export_btn, self.clear_btn, self.send_btn, self.web_btn,
                    self.image_btn):
            btn.apply_theme(th.c("card"))
        self.bottom.configure(bg=th.c("card"))
        self.attach_strip.configure(bg=th.c("card"))
        self.attach_hint.configure(bg=th.c("card"), fg=th.c("text_faint"))
        bottom = self.input.master.master
        bottom.configure(bg=th.c("card"))
        holder = self.input.master
        holder.configure(bg=th.c("card_alt"), highlightbackground=th.c("border"),
                         highlightcolor=th.c("accent"))
        self.input.configure(bg=th.c("card_alt"), fg=th.c("text"),
                             insertbackground=th.c("accent"))
        for child in bottom.winfo_children():
            if isinstance(child, tk.Frame) and child is not holder:
                child.configure(bg=th.c("card"))
        self.hint.configure(bg=th.c("card"), fg=th.c("text_faint"))

    def apply_texts(self):
        self.title.configure(text=T("chat.title"))
        self.clear_btn.set_text(T("sessions.new"))
        self.export_btn.set_text(T("chat.export"))
        self.hint.configure(text=T("chat.input_hint"))
        self.attach_hint.configure(text=T("vision.attach_hint"))
        self.image_btn.set_text(T("vision.attach"))
        self.empty_label.configure(text=T("chat.empty"))
        self.send_btn.set_text(T("chat.stop") if self.generating else T("chat.send"))
        for bubble in self.bubbles:
            bubble.copy_btn.set_text(T("chat.copy"))
            bubble.title_label.configure(
                text=T("chat.you") if bubble.role == "user" else T("chat.ai"))
            bubble._sync_think_head()
            bubble._sync_sources_head()
        self._sync_web_btn()

    def on_show(self):
        self._show_empty(not self.records)

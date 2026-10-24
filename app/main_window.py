"""主窗口：背景画布 + 圆角卡片布局 + 侧边导航 + 顶栏 + 视图切换 + 状态轮询。"""
from __future__ import annotations

import datetime as _dt
import os
import queue
import sys
import threading
import tkinter as tk

from . import APP_NAME, __version__
from . import config as cfgmod
from . import theme as th
from .backgrounds import BackgroundManager, HAS_PIL
from .chat_view import ChatView
from . import i18n
from .i18n import set_lang, t as T
from .ollama_api import OllamaClient, ServiceManager
from .panels import LogsView, ModelsView, ServiceView, SettingsView
from . import sessions as sessions_mod
from .sessions import store as session_store
from .widgets import (PillButton, ScrollFrame, StatusDot, round_rect, soft_round_rect,
                      style_scrollbar, text_width)

M = 22          # 外边距（留出背景可见区域）
GAP = 14        # 卡片间距
NAV_W = 238     # 侧栏宽度
TOP_H = 64      # 顶栏高度
PAD = 7         # 内容与卡片边缘的间隙（露出圆角）
RADIUS = 8      # Windows 11 卡片圆角


# ============================================================ 事件日志
class EventLog:
    def __init__(self, cap: int = 800):
        self.cap = cap
        self.items: list[str] = []

    def add(self, level: str, message: str) -> None:
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        self.items.append(f"[{stamp}] {level:<5} {message}")
        if len(self.items) > self.cap:
            self.items = self.items[-self.cap:]

    def text(self) -> str:
        return "\n".join(self.items)

    def clear(self) -> None:
        self.items.clear()


# ============================================================ 图标
def draw_icon(cv: tk.Canvas, kind: str, cx: float, cy: float, color: str, s: float = 16) -> None:
    w = 2
    if kind == "chat":
        cv.create_rectangle(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 6,
                            outline=color, width=w)
        cv.create_line(cx - s / 6, cy + s / 6, cx - s / 6, cy + s / 2, fill=color, width=w)
        cv.create_line(cx - s / 6, cy + s / 2, cx + s / 8, cy + s / 6, fill=color, width=w)
    elif kind == "models":
        for i in range(3):
            top = cy - s / 2 + i * (s / 3)
            cv.create_rectangle(cx - s / 2, top, cx + s / 2, top + s / 5,
                                outline=color, width=w)
    elif kind == "service":
        cv.create_arc(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2, start=35, extent=290,
                      style="arc", outline=color, width=w)
        cv.create_line(cx, cy - s / 2 - 1, cx, cy, fill=color, width=w)
    elif kind == "settings":
        for i, frac in enumerate((0.3, 0.65, 0.45)):
            y = cy - s / 2 + i * (s / 2.4)
            cv.create_line(cx - s / 2, y, cx + s / 2, y, fill=color, width=w)
            cv.create_oval(cx - s / 2 + frac * s - 2.5, y - 2.5,
                           cx - s / 2 + frac * s + 2.5, y + 2.5, fill=color, outline="")
    elif kind == "logs":
        for i, frac in enumerate((1.0, 0.7, 0.85, 0.5)):
            y = cy - s / 2 + i * (s / 3.2)
            cv.create_line(cx - s / 2, y, cx - s / 2 + s * frac, y, fill=color, width=w)


# ============================================================ 侧栏导航项
class NavItem(tk.Canvas):
    def __init__(self, parent, key: str, icon: str, text: str, command=None,
                 width: int = NAV_W - 2 * PAD - 8, height: int = 44):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0,
                         bg=th.c("card"))
        self.key = key
        self.icon = icon
        self._text = text
        self._command = command
        self._active = False
        self._hover = False
        self._cw, self._ch = width, height
        self.bind("<Button-1>", lambda _e: self._command and self._command(self.key))
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._redraw()

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def set_active(self, active: bool):
        if active != self._active:
            self._active = active
            self._redraw()

    def set_text(self, text: str):
        self._text = text
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w, h = self._cw, self._ch
        if self._active:
            soft_round_rect(self, 0, 2, w, h - 2, 7, fill=th.c("nav_active"),
                            bg=th.c("card"), soften=0.55)
            round_rect(self, 3, h / 2 - 8, 6, h / 2 + 8, 2, fill=th.c("accent"), outline="")
        elif self._hover:
            round_rect(self, 0, 2, w, h - 2, 10, fill=th.c("card_hover"), outline="")
        color = th.c("accent") if self._active else (
            th.c("text") if self._hover else th.c("text_muted"))
        draw_icon(self, self.icon, 24, h / 2, color, 15)
        self.create_text(48, h / 2 + 1, text=self._text, anchor="w", fill=color,
                         font=th.F(10, "bold" if self._active else "normal"))

    def apply_theme(self, bg: str):
        self.configure(bg=bg)
        self._redraw()


# ============================================================ 状态轮询
class StatusPoller(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            host = self.app.cfg.get("host", "http://127.0.0.1:11434")
            client = OllamaClient(host)
            try:
                info = client.version(timeout=2.5)
                self.app.status = "ok"
                self.app.server_version = info.get("version", "")
            except Exception:
                self.app.status = "err"
                self.app.server_version = ""
            self._stop.wait(3.0)


# ============================================================ 主窗口
class MainWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = cfgmod.load()
        set_lang(self.cfg.get("lang", "zh"))
        th.apply(self.cfg.get("theme", "auto"), self.cfg.get("accent", "auto"))

        self.event_log = EventLog()
        self.bg = BackgroundManager(self.cfg)
        self.svc = ServiceManager(self.cfg)
        self.status = "busy"
        self.server_version = ""
        self.current_view_key = "chat"
        self._results: queue.Queue = queue.Queue()
        self._galleries: list = []
        self.sessions_store = session_store()
        self.current_session_id = ""
        self._bg_photo = None
        self._card_rects: list = []

        self.title(APP_NAME)
        self.configure(bg=th.c("root"))
        self.minsize(980, 660)
        self._setup_geometry()
        th.init_fonts(self)
        style_scrollbar(self._style())

        self._build_widgets()
        self._bind_events()
        self._apply_all_theme()
        self.show_view("chat")

        self.run_async(self._probe_status, None)
        self._poller = StatusPoller(self)
        self._poller.start()
        self.after(120, self._pump)
        self.after(1000, self._tick)
        self.after(260, self._restore_last_session)
        self.after(1600, self.validate_model)
        self.after(60, self._apply_win11_frame)
        self.event_log.add("INFO", f"{APP_NAME} {__version__} started")
        self.event_log.add("INFO", f"theme={th.current()} accent={th.accent_name()}")
        self.event_log.add("INFO", f"models dir: {self.cfg.get('models_dir')}")

    # ------------------------------------------------ 初始化
    def _style(self):
        from tkinter import ttk

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        return style

    def _setup_geometry(self):
        win = self.cfg.get("window", {})
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(win.get("w") or 1360), sw - 60)
        h = min(int(win.get("h") or 860), sh - 80)
        x = win.get("x")
        y = win.get("y")
        if x is None or y is None:
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 3)
        else:
            # 位置保护：窗口被拖到屏幕外时（多显示器拔掉、坐标异常）重新摆回可见区域
            vx, vy = self.winfo_vrootx(), self.winfo_vrooty()
            vw, vh = self.winfo_vrootwidth(), self.winfo_vrootheight()
            x = max(vx - w + 140, min(int(x), vx + vw - 140))
            y = max(vy, min(int(y), vy + vh - 90))
        self.geometry(f"{w}x{h}+{int(x)}+{int(y)}")
        self._apply_icon()

    def _apply_icon(self):
        if not HAS_PIL:
            return
        try:
            from PIL import Image, ImageDraw, ImageTk

            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle((2, 2, 62, 62), radius=16, fill="#2f6feb")
            draw.ellipse((20, 16, 44, 40), fill="#ffffff")
            draw.rectangle((28, 34, 36, 50), fill="#ffffff")
            self._icon_photo = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    def _build_widgets(self):
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=th.c("root"))
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)

        self.nav_frame = tk.Frame(self, bg=th.c("card"), bd=0, highlightthickness=0)
        self.top_frame = tk.Frame(self, bg=th.c("card"), bd=0, highlightthickness=0)
        self.content = tk.Frame(self, bg=th.c("card"), bd=0, highlightthickness=0)

        # ---- 侧栏
        head = tk.Frame(self.nav_frame, bg=th.c("card"))
        head.pack(fill="x", padx=8, pady=(14, 10))
        self.app_title = tk.Label(head, text=APP_NAME, bg=th.c("card"), fg=th.c("text"),
                                  font=th.F(11, "bold"), anchor="w")
        self.app_title.pack(fill="x")
        self.app_sub = tk.Label(head, text=T("app.subtitle"), bg=th.c("card"),
                                fg=th.c("text_faint"), font=th.F(8), anchor="w")
        self.app_sub.pack(fill="x", pady=(2, 0))

        self.nav_items: dict[str, NavItem] = {}
        for key, icon in (("chat", "chat"), ("models", "models"), ("service", "service"),
                          ("settings", "settings"), ("logs", "logs")):
            item = NavItem(self.nav_frame, key, icon, T(f"nav.{key}"), command=self.show_view)
            item.pack(fill="x", padx=4, pady=2)
            self.nav_items[key] = item

        self.nav_footer = tk.Frame(self.nav_frame, bg=th.c("card"))
        self.nav_footer.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.nav_dot = StatusDot(self.nav_footer, "busy", 10, bg=th.c("card"))
        self.nav_dot.pack(side="left", padx=(0, 6))
        self.nav_status = tk.Label(self.nav_footer, text=T("top.offline"), bg=th.c("card"),
                                   fg=th.c("text_faint"), font=th.F(8), anchor="w")
        self.nav_status.pack(side="left")
        self.ver_label = tk.Label(self.nav_footer, text=f"v{__version__}", bg=th.c("card"),
                                  fg=th.c("text_faint"), font=th.F(8))
        self.ver_label.pack(side="right")

        # ---- 对话记录（左侧列表）
        self.sessions_panel = tk.Frame(self.nav_frame, bg=th.c("card"))
        self.sessions_panel.pack(fill="both", expand=True, padx=4, pady=(14, 4))
        s_head = tk.Frame(self.sessions_panel, bg=th.c("card"))
        s_head.pack(fill="x", padx=4, pady=(0, 4))
        self.sessions_title = tk.Label(s_head, text=T("sessions.title"), bg=th.c("card"),
                                       fg=th.c("text_muted"), font=th.F(9, "bold"), anchor="w")
        self.sessions_title.pack(side="left")
        self.sessions_new_btn = PillButton(s_head, "＋", command=self.new_session, kind="ghost",
                                           height=24, radius=7, font=th.F(10), pad=9,
                                           bg=th.c("card"))
        self.sessions_new_btn.pack(side="right")
        self.sessions_scroll = ScrollFrame(self.sessions_panel, bg_key="card")
        self.sessions_scroll.pack(fill="both", expand=True)

        # ---- 顶栏
        self.view_title = tk.Label(self.top_frame, text="", bg=th.c("card"), fg=th.c("text"),
                                   font=th.F(15, "bold"))
        self.view_title.pack(side="left", padx=(4, 14))
        self.model_chip = PillButton(self.top_frame, "", command=lambda: self.show_view("models"),
                                     kind="ghost", height=32, radius=9, font=th.F(9))
        self.model_chip.pack(side="left")

        self.theme_btn = PillButton(self.top_frame, "", command=self.toggle_theme, kind="ghost",
                                    height=32, radius=9, min_width=64)
        self.theme_btn.pack(side="right")
        self.lang_btn = PillButton(self.top_frame, "", command=self.toggle_lang, kind="ghost",
                                   height=32, radius=9, min_width=64)
        self.lang_btn.pack(side="right", padx=(0, 8))
        self.bg_btn = PillButton(self.top_frame, "", command=self._quick_background, kind="ghost",
                                 height=32, radius=9)
        self.bg_btn.pack(side="right", padx=(0, 8))
        self.dot = StatusDot(self.top_frame, "busy", 12, bg=th.c("card"))
        self.dot.pack(side="right", padx=(0, 10))
        self.status_label = tk.Label(self.top_frame, text=T("top.offline"), bg=th.c("card"),
                                     fg=th.c("text_muted"), font=th.F(9))
        self.status_label.pack(side="right")

        # ---- 内容区
        self.views: dict[str, tk.Frame] = {}
        self.views["chat"] = ChatView(self.content, self)
        self.views["models"] = ModelsView(self.content, self)
        self.views["service"] = ServiceView(self.content, self)
        self.views["settings"] = SettingsView(self.content, self)
        self.views["logs"] = LogsView(self.content, self)

        self.toast_label = tk.Label(self.content, text="", bg=th.c("card_alt"), fg=th.c("text"),
                                    font=th.F(9), padx=14, pady=8)

    def _bind_events(self):
        self.bind("<Configure>", self._on_configure)
        self.bind_all("<MouseWheel>", self._on_wheel)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._relayout_job = None

    # ------------------------------------------------ 布局
    def _on_configure(self, event):
        if event.widget is not self:
            return
        if self._relayout_job:
            self.after_cancel(self._relayout_job)
        self._relayout_job = self.after(60, self.relayout)

    def relayout(self):
        self._relayout_job = None
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 50 or h < 50:
            return
        left = M + NAV_W + GAP
        self._card_rects = [
            (M, M, M + NAV_W, h - M),
            (left, M, w - M, M + TOP_H),
            (left, M + TOP_H + GAP, w - M, h - M),
        ]
        self._render_background()
        self._draw_cards()

        self.nav_frame.place(x=M + PAD, y=M + PAD,
                             width=NAV_W - 2 * PAD, height=h - 2 * M - 2 * PAD)
        self.top_frame.place(x=left + PAD, y=M + PAD,
                             width=w - M - left - 2 * PAD, height=TOP_H - 2 * PAD)
        self.content.place(x=left + PAD, y=M + TOP_H + GAP + PAD,
                           width=w - M - left - 2 * PAD,
                           height=h - M - (M + TOP_H + GAP) - 2 * PAD)

    def _render_background(self):
        size = (self.winfo_width(), self.winfo_height())
        if (getattr(self.bg, "preset", "") == "auto") and not getattr(self.bg, "source", ""):
            photo = None          # 跟随主题的 Win11 纯色底
        else:
            photo = self.bg.render(size)
        self.canvas.delete("bgimg")
        if photo is not None:
            self._bg_photo = photo
            self.canvas.create_image(0, 0, image=photo, anchor="nw", tags="bgimg")
            self.canvas.tag_lower("bgimg")
            self._bg_warned = None
        else:
            self._bg_photo = None
            self.canvas.configure(bg=th.c("root"))
            # 背景图读取失败时给出一次提示（否则界面只是静默变成纯色）
            src = self.bg.source
            if src and size[0] > 40 and size[1] > 40 and getattr(self, "_bg_warned", None) != src:
                self._bg_warned = src
                self.event_log.add("WARN", f"background image could not be loaded: {src}")
                self.toast(T("set.bg_load_failed", src))

    def _draw_cards(self):
        self.canvas.delete("card")
        for (x1, y1, x2, y2) in self._card_rects:
            round_rect(self.canvas, x1, y1, x2, y2, RADIUS,
                       fill=th.c("card"), outline=th.c("border"), width=1, tags="card")
        # 背景图在 _render_background 里已置于最底层；
        # 若再执行 tag_lower("card", "bgimg") 反而会把卡片压到壁纸下面，
        # 使卡片描边那一圈露出壁纸（看似杂散笔画）。
        if self.canvas.find_withtag("bgimg"):
            self.canvas.tag_raise("card", "bgimg")

    def _on_wheel(self, event):
        widget = None
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return None
        while widget is not None:
            if getattr(widget, "_is_scroll_area", False):
                widget.scroll_by(-1 if event.delta > 0 else 1)
                return "break"
            widget = getattr(widget, "master", None)
        return None

    # ------------------------------------------------ 视图
    def show_view(self, key: str):
        if key not in self.views:
            return
        for view in self.views.values():
            view.pack_forget()
        view = self.views[key]
        view.pack(fill="both", expand=True)
        self.current_view_key = key
        for nav_key, item in self.nav_items.items():
            item.set_active(nav_key == key)
        self.view_title.configure(text=T(f"nav.{key}"))
        if hasattr(view, "on_show"):
            try:
                view.on_show()
            except Exception as exc:
                self.event_log.add("ERROR", f"on_show {key}: {exc}")
        self.event_log.add("INFO", f"view -> {key}")

    def _quick_background(self):
        self.show_view("settings")

    # ------------------------------------------------ 对话记录（会话）
    def refresh_sessions(self):
        """重建左侧会话列表。"""
        if not hasattr(self, "sessions_scroll"):
            return
        self.sessions_scroll.clear()
        items = self.sessions_store.list()
        if not items:
            tk.Label(self.sessions_scroll.inner, text=T("sessions.empty"), bg=th.c("card"),
                     fg=th.c("text_faint"), font=th.F(8), wraplength=170,
                     justify="left").pack(anchor="w", padx=6, pady=8)
            return
        font = th.F(9)
        for meta in items:
            self._session_row(meta, font)

    @staticmethod
    def _elide(text: str, font, max_px: int) -> str:
        text = text or ""
        if text_width(text, font) <= max_px:
            return text
        while text and text_width(text + "…", font) > max_px:
            text = text[:-1]
        return (text + "…") if text else "…"

    def _session_row(self, meta: dict, font):
        sid = meta.get("id", "")
        active = sid == self.current_session_id
        bg = th.c("chip") if active else th.c("card")
        title_text = meta.get("title") or T("sessions.untitled")

        row = tk.Frame(self.sessions_scroll.inner, bg=bg, padx=6, pady=4, cursor="hand2")
        row.pack(fill="x", pady=1)
        top = tk.Frame(row, bg=bg)
        top.pack(fill="x")
        label = tk.Label(top, text=self._elide(title_text, font, 150), bg=bg,
                         fg=th.c("accent") if active else th.c("text"), font=font, anchor="w")
        label.pack(side="left", fill="x", expand=True)
        close = tk.Label(top, text="✕", bg=bg, fg=th.c("text_faint"), font=th.F(8),
                         cursor="hand2")
        close.pack(side="right")
        when = tk.Label(row, text=sessions_mod.rel_time(meta.get("updated", "")), bg=bg,
                        fg=th.c("text_faint"), font=th.F(7), anchor="w")
        when.pack(fill="x")

        for widget in (row, top, label, when):
            widget.bind("<Button-1>", lambda _e, s=sid: self.load_session(s))
            widget.bind("<Button-3>", lambda _e, s=sid, t=title_text: self.rename_session(s, t))
        close.bind("<Button-1>", lambda _e, s=sid, t=title_text: self.delete_session(s, t))

    def new_session(self):
        self.show_view("chat")
        self.views["chat"].new_session()

    def load_session(self, session_id: str):
        self.show_view("chat")
        if self.views["chat"].load_session(session_id):
            self.refresh_sessions()

    def delete_session(self, session_id: str, title: str):
        from .widgets import confirm

        if not confirm(self, T("sessions.delete_confirm", title or T("sessions.untitled"))):
            return
        was_active = session_id == self.current_session_id
        self.sessions_store.delete(session_id)
        self.event_log.add("INFO", f"session deleted: {session_id}")
        self.toast(T("sessions.deleted"))
        if was_active:
            self.views["chat"].new_session(notify=False)
        else:
            self.refresh_sessions()

    def rename_session(self, session_id: str, title: str):
        from .widgets import ask_text

        new_title = ask_text(self, T("sessions.rename_title"), "", title)
        if not new_title:
            return
        self.sessions_store.rename(session_id, new_title)
        chat = self.views.get("chat")
        if chat is not None and session_id == self.current_session_id:
            chat.session_title = new_title
        self.refresh_sessions()

    def on_session_changed(self, session_id: str):
        """对话视图切换会话时回调：记录并刷新高亮。"""
        self.current_session_id = session_id
        self.cfg["last_session"] = session_id
        self.save_cfg()
        self.refresh_sessions()

    def _restore_last_session(self):
        """启动时恢复上次会话；没有可恢复的就开一段新的。"""
        last = self.cfg.get("last_session") or ""
        if last and self.sessions_store.load(last):
            self.views["chat"].load_session(last, notify=False)
        else:
            self.views["chat"].new_session(notify=False)
        self.refresh_sessions()

    # ------------------------------------------------ 模型库
    def open_gallery(self):
        """打开「模型库」窗口（自动拉取在线模型列表并下载）。"""
        from .gallery import ModelGallery

        try:
            win = ModelGallery(self, self)
        except Exception as exc:
            self.event_log.add("ERROR", f"gallery: {exc}")
            self.toast(str(exc))
            return None
        self._galleries.append(win)

        def on_destroy(event=None):
            # <Destroy> 会因子控件销毁而冒泡上来，只处理窗口自身
            if event is not None and getattr(event, "widget", None) is not win:
                return
            if win in self._galleries:
                self._galleries.remove(win)

        win.bind("<Destroy>", on_destroy, add="+")
        self.after(250, lambda: win.apply_theme() if win.winfo_exists() else None)
        return win

    def refresh_models_view(self):
        view = self.views.get("models")
        if view is not None and hasattr(view, "refresh"):
            try:
                view.refresh()
            except Exception:
                pass

    def validate_model(self, auto_switch: bool = True):
        """启动时检查配置里的模型是否还在，避免每次对话 404。"""
        def work():
            try:
                return [m.get("name", "") for m in self.client.tags()]
            except Exception:
                return None

        def done(names, error):
            if not names:
                return
            current = self.current_model
            if current in names:
                return
            if auto_switch:
                self.set_model(names[0])
                self.event_log.add("WARN",
                                   f"model {current!r} not found -> switched to {names[0]!r}")
                self.toast(T("chat.model_gone", current or "-", names[0]))
            else:
                self.event_log.add("WARN", f"model {current!r} not found")

        self.run_async(work, done)

    # ------------------------------------------------ 配置 / 异常
    def save_cfg(self):
        """把内存中的配置写回磁盘（按钮回调里大量调用）。"""
        try:
            cfgmod.save(self.cfg)
        except Exception as exc:
            self.event_log.add("ERROR", f"save config: {exc}")

    def report_callback_exception(self, exc, val, tb):
        """Tk 控件回调里的异常默认被静默吞掉（pythonw 无控制台），
        这里改为写入事件日志 + error.log 并弹提示，避免再出现“点了没反应”。"""
        import traceback

        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            self.event_log.add("ERROR", f"UI callback: {val}")
        except Exception:
            pass
        try:
            cfgmod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(cfgmod.CONFIG_DIR / "error.log", "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except Exception:
            pass
        try:
            self.toast(f"内部错误 / Internal error: {val}")
        except Exception:
            pass
        try:
            print(text, file=sys.stderr)
        except Exception:
            pass

    # ------------------------------------------------ 主题 / 语言
    def toggle_theme(self):
        mode = th.toggle()
        self.cfg["theme"] = mode
        self._apply_all_theme()
        self.save_cfg()

    def toggle_lang(self):
        from . import i18n

        new = "en" if i18n.current() == "zh" else "zh"
        i18n.set_lang(new)
        self.cfg["lang"] = new
        self.apply_texts()
        self.save_cfg()

    def save_config_and_refresh(self):
        self.apply_texts()
        self.save_cfg()

    def _apply_win11_frame(self):
        try:
            th.set_win11_frame(self)
        except Exception:
            pass

    def _apply_all_theme(self):
        style_scrollbar(self._style())
        self.configure(bg=th.c("root"))
        self.canvas.configure(bg=th.c("root"))
        for frame in (self.nav_frame, self.top_frame, self.content):
            frame.configure(bg=th.c("card"))
        self.app_title.configure(bg=th.c("card"), fg=th.c("text"))
        self.app_sub.configure(bg=th.c("card"), fg=th.c("text_faint"))
        self.nav_footer.configure(bg=th.c("card"))
        self.nav_status.configure(bg=th.c("card"), fg=th.c("text_faint"))
        self.ver_label.configure(bg=th.c("card"), fg=th.c("text_faint"))
        self.nav_dot.apply_theme(th.c("card"))
        for item in self.nav_items.values():
            item.apply_theme(th.c("card"))
        self.sessions_panel.configure(bg=th.c("card"))
        self.sessions_title.configure(bg=th.c("card"), fg=th.c("text_muted"))
        self.sessions_new_btn.apply_theme(th.c("card"))
        self.sessions_scroll.apply_theme("card")
        self.refresh_sessions()
        self.view_title.configure(bg=th.c("card"), fg=th.c("text"))
        self.status_label.configure(bg=th.c("card"), fg=th.c("text_muted"))
        self.dot.apply_theme(th.c("card"))
        for btn in (self.model_chip, self.theme_btn, self.lang_btn, self.bg_btn):
            btn.apply_theme(th.c("card"))
        self.toast_label.configure(bg=th.c("card_alt"), fg=th.c("text"))
        for view in self.views.values():
            try:
                view.apply_theme()
            except Exception as exc:
                self.event_log.add("ERROR", f"theme: {exc}")
        for win in list(self._galleries):
            try:
                if win.winfo_exists():
                    win.apply_theme()
            except Exception as exc:
                self.event_log.add("ERROR", f"gallery theme: {exc}")
        self.apply_texts()
        # 兜底：把深层容器里残留的旧主题颜色统一迁移到当前主题
        try:
            fixed = th.migrate_colors(self)
            if fixed:
                self.event_log.add("INFO", f"theme colors migrated: {fixed}")
        except Exception as exc:
            self.event_log.add("ERROR", f"migrate: {exc}")
        self._render_background()
        self._draw_cards()
        self._apply_win11_frame()

    def apply_texts(self):
        self.app_sub.configure(text=T("app.subtitle"))
        for key, item in self.nav_items.items():
            item.set_text(T(f"nav.{key}"))
        self.sessions_title.configure(text=T("sessions.title"))
        self.refresh_sessions()
        self.view_title.configure(text=T(f"nav.{self.current_view_key}"))
        self.model_chip.set_text(self._model_chip_text())
        self.theme_btn.set_text(T("set.theme_light") if th.is_dark() else T("set.theme_dark"))
        self.lang_btn.set_text("EN" if self.cfg.get("lang") == "zh" else "中文")
        self.bg_btn.set_text(T("top.bg"))
        for view in self.views.values():
            try:
                view.apply_texts()
            except Exception as exc:
                self.event_log.add("ERROR", f"texts: {exc}")
        for win in list(self._galleries):
            try:
                if win.winfo_exists():
                    win.apply_texts()
            except Exception as exc:
                self.event_log.add("ERROR", f"gallery texts: {exc}")
        # 兜底：重译所有带 _i18n_key 标记的深层控件
        try:
            i18n.retranslate(self)
        except Exception as exc:
            self.event_log.add("ERROR", f"retranslate: {exc}")

    def _model_chip_text(self) -> str:
        model = self.current_model
        if not model:
            return T("top.no_model")
        if len(model) > 24:                     # 顶栏空间有限，过长的名字做省略
            model = model[:23] + "…"
        return f"{T('top.model')}: {model}"

    # ------------------------------------------------ 背景
    def apply_background(self):
        self._render_background()
        self._draw_cards()

    # ------------------------------------------------ 状态
    @property
    def client(self) -> OllamaClient:
        return OllamaClient(self.cfg.get("host", "http://127.0.0.1:11434"))

    @property
    def sessions(self):
        """会话存储（ChatView 通过 app.sessions 访问）。"""
        return self.sessions_store

    @property
    def current_model(self) -> str:
        return self.cfg.get("model", "")

    def set_model(self, name: str):
        self.cfg["model"] = name
        self.save_cfg()
        self.model_chip.set_text(self._model_chip_text())
        self.event_log.add("INFO", f"model -> {name}")
        self.toast(f"{T('models.in_use')}: {name}")

    def _probe_status(self):
        try:
            info = self.client.version(timeout=3)
            return info.get("version", "")
        except Exception:
            return None

    def refresh_status_now(self):
        self.status = "busy"
        self.run_async(self._probe_status, lambda res, err: self._update_status_ui())

    def _tick(self):
        self._update_status_ui()
        view = self.views.get(self.current_view_key)
        if isinstance(view, ServiceView):
            try:
                view.tick()
            except Exception:
                pass
        self.after(1500, self._tick)

    def _update_status_ui(self):
        state = self.status
        if state == "ok":
            self.dot.set_state("ok")
            self.nav_dot.set_state("ok")
            self.status_label.configure(text=T("top.online"), fg=th.c("ok"))
            self.nav_status.configure(text=T("top.online"), fg=th.c("ok"))
        elif state == "err":
            self.dot.set_state("err")
            self.nav_dot.set_state("err")
            self.status_label.configure(text=T("top.offline"), fg=th.c("err"))
            self.nav_status.configure(text=T("top.offline"), fg=th.c("err"))
        else:
            self.dot.set_state("busy")
            self.nav_dot.set_state("busy")
            self.status_label.configure(text=T("svc.checking"), fg=th.c("text_muted"))
            self.nav_status.configure(text=T("svc.checking"), fg=th.c("text_faint"))
        self.model_chip.set_text(self._model_chip_text())

    # ------------------------------------------------ 异步任务
    def run_async(self, fn, callback=None):
        def worker():
            try:
                result = fn()
                error = None
            except Exception as exc:
                result, error = None, exc
            self._results.put((callback, result, error))

        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                callback, result, error = self._results.get_nowait()
                if callback is not None:
                    try:
                        callback(result, error)
                    except Exception as exc:
                        self.event_log.add("ERROR", f"callback: {exc}")
        except queue.Empty:
            pass
        self.after(120, self._pump)

    # ------------------------------------------------ 提示 / 日志
    def toast(self, message: str, ms: int = 2600):
        self.toast_label.configure(text=message)
        self.toast_label.place(relx=0.5, rely=1.0, anchor="s", y=-18)
        self.toast_label.lift()
        if getattr(self, "_toast_job", None):
            try:
                self.after_cancel(self._toast_job)
            except Exception:
                pass
        self._toast_job = self.after(ms, self.toast_label.place_forget)

    def log_event(self, level: str, message: str):
        self.event_log.add(level, message)

    # ------------------------------------------------ 关闭
    def on_close(self):
        try:
            self._poller.stop()
        except Exception:
            pass
        try:
            self.views["chat"].save_session()      # 退出前落盘当前对话
        except Exception:
            pass
        self.cfg["window"] = {
            "w": self.winfo_width(), "h": self.winfo_height(),
            "x": self.winfo_x(), "y": self.winfo_y(),
        }
        self.cfg["theme"] = th.current()
        save = cfgmod.save
        save(self.cfg)
        self.destroy()


def run():
    app = MainWindow()
    app.mainloop()

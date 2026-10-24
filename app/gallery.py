"""模型库：自动获取在线模型列表、查看可用版本与体积、一键下载。

数据来源（均为 ollama.com 公开接口）：
  * 模型列表   https://ollama.com/search?q=<关键词>
  * 版本列表   https://ollama.com/library/<模型>/tags
  * 精确体积   https://registry.ollama.ai/v2/library/<模型>/manifests/<版本>
"""
from __future__ import annotations

import html as _html
import json
import queue
import re
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request

from . import theme as th
from .i18n import t as T
from .ollama_api import RateMeter, human_size
from .widgets import PillButton, ProgressBar, ScrollFrame, confirm  # noqa: F401

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIChat/1.1"
SEARCH_URL = "https://ollama.com/search?q={}"
TAGS_URL = "https://ollama.com/library/{}/tags"
MANIFEST_URL = "https://registry.ollama.ai/v2/library/{}/manifests/{}"
FEATURED_URL = "https://ollama.com/api/tags"
RECOMMEND_URL = "https://ollama.com/api/experimental/model-recommendations"

# 网络不可用时的兜底列表
FALLBACK_MODELS = [
    {"name": "deepseek-r1", "description": "DeepSeek-R1 reasoning model family (1.5b / 7b / 8b / 14b / 32b / 70b / 671b).",
     "tags": ["1.5b", "7b", "8b", "14b", "32b", "70b", "671b"], "caps": ["thinking"]},
    {"name": "qwen3", "description": "Qwen3 dense and MoE models with thinking mode.",
     "tags": ["0.6b", "1.7b", "4b", "8b", "14b", "30b", "32b"], "caps": ["tools", "thinking"]},
    {"name": "llama3.2", "description": "Meta Llama 3.2 small models, 1B and 3B.",
     "tags": ["1b", "3b"], "caps": ["tools"]},
    {"name": "gemma3", "description": "Google Gemma 3 lightweight multimodal models.",
     "tags": ["1b", "4b", "12b", "27b"], "caps": ["vision"]},
    {"name": "mistral", "description": "Mistral 7B instruct model.",
     "tags": ["latest", "7b"], "caps": ["tools"]},
    {"name": "phi4", "description": "Microsoft Phi-4 14B reasoning model.",
     "tags": ["latest", "14b"], "caps": []},
    {"name": "deepseek-coder-v2", "description": "Code-focused DeepSeek V2 models.",
     "tags": ["16b", "236b"], "caps": []},
]


# ============================================================ 网络
def _get(url: str, timeout: float = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _strip_tags(text: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def parse_search(html: str) -> list[dict]:
    """从搜索页解析模型条目。"""
    items: list[dict] = []
    seen: set[str] = set()
    for match in re.finditer(r'href="/library/([A-Za-z0-9._\-]+)"', html):
        name = match.group(1)
        if ":" in name or name in seen:
            continue
        seen.add(name)
        chunk = html[match.end(): match.end() + 3000]
        desc = ""
        dm = re.search(r'<p class="[^"]*break-words[^"]*">(.*?)</p>', chunk, re.S)
        if dm:
            desc = _strip_tags(dm.group(1))
        um = re.search(r"(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago)", chunk)
        caps = sorted(set(re.findall(r">\s*(tools|vision|thinking|embedding|audio|cloud)\s*<", chunk)))
        items.append({
            "name": name,
            "description": desc,
            "updated": um.group(1) if um else "",
            "caps": caps,
        })
    return items


def parse_tags(html: str, model: str) -> list[str]:
    """从版本页解析该模型的全部版本标签。"""
    tags: list[str] = []
    for match in re.finditer(r'href="/library/([A-Za-z0-9._\-]+):([A-Za-z0-9._\-]+)"', html):
        if match.group(1) != model:
            continue
        tag = match.group(2)
        if tag not in tags:
            tags.append(tag)
    if "latest" in tags:
        tags.remove("latest")
        tags.insert(0, "latest")
    return tags


def fetch_models(query: str = "") -> list[dict]:
    """获取模型列表；query 为空时返回首页推荐列表。"""
    url = SEARCH_URL.format(urllib.parse.quote(query)) if query.strip() else "https://ollama.com/search"
    items = parse_search(_get(url))
    if not items and not query.strip():
        # 退路：官方“最新模型”接口
        data = json.loads(_get(FEATURED_URL))
        for model in data.get("models", []):
            details = model.get("details") or {}
            items.append({
                "name": model.get("name", ""),
                "description": details.get("parameter_size", "") or "",
                "updated": "",
                "caps": [],
            })
    return items


def fetch_tags(model: str) -> list[str]:
    return parse_tags(_get(TAGS_URL.format(model)), model)


def fetch_tag_size(model: str, tag: str) -> int:
    """通过 registry manifest 计算该版本的总下载体积（字节）。"""
    try:
        data = json.loads(_get(MANIFEST_URL.format(model, tag), timeout=20))
        return int(sum(layer.get("size", 0) for layer in data.get("layers", [])))
    except Exception:
        return 0


# ============================================================ 窗口
class ModelGallery(tk.Toplevel):
    """模型库窗口：搜索 -> 选模型 -> 选版本 -> 下载。"""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title(T("gallery.title"))
        self.configure(bg=th.c("card"))
        self.transient(parent)
        self.minsize(760, 520)
        self.geometry("880x640")
        self._center(parent)

        self.models: list[dict] = []
        self.tags: list[str] = []
        self.sizes: dict[str, int] = {}
        self.selected: str = ""
        self.installed: set[str] = set()
        self.queue: queue.Queue = queue.Queue()
        self.pulling = False
        self.cancel = threading.Event()
        self._row_widgets: dict[str, tk.Frame] = {}
        self._tag_widgets: dict[str, tk.Frame] = {}
        self._closed = False

        self._build()
        self._pump()
        self.after(60, self.reload_installed)
        self.after(120, lambda: self.search(""))

    # ------------------------------------------------ 生命周期
    def _alive(self) -> bool:
        try:
            return (not self._closed) and bool(self.winfo_exists())
        except Exception:
            return False

    def destroy(self):
        self._closed = True
        self.cancel.set()
        try:
            super().destroy()
        except Exception:
            pass

    # ------------------------------------------------ 布局
    def _center(self, parent):
        try:
            parent.update_idletasks()
            x = parent.winfo_rootx() + max(0, (parent.winfo_width() - 880) // 2)
            y = parent.winfo_rooty() + max(0, (parent.winfo_height() - 640) // 3)
            self.geometry(f"880x640+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass

    def _build(self):
        head = tk.Frame(self, bg=th.c("card"))
        head.pack(fill="x", padx=16, pady=(14, 8))
        self.title_label = tk.Label(head, text=T("gallery.title"), bg=th.c("card"),
                                    fg=th.c("text"), font=th.F(14, "bold"))
        self.title_label.pack(side="left")

        bar = tk.Frame(self, bg=th.c("card"))
        bar.pack(fill="x", padx=16)
        self.search_entry = tk.Entry(bar, bd=0, relief="flat", bg=th.c("card_alt"),
                                     fg=th.c("text"), insertbackground=th.c("accent"),
                                     font=th.F(10), highlightthickness=1,
                                     highlightbackground=th.c("border"),
                                     highlightcolor=th.c("accent"))
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self.search_entry.bind("<Return>", lambda _e: self.search(self.search_entry.get()))
        self.refresh_btn = PillButton(bar, T("gallery.refresh"), command=self.reload,
                                      kind="ghost", height=36, radius=9)
        self.refresh_btn.pack(side="left", padx=(8, 0))
        self.search_btn = PillButton(bar, T("gallery.search"),
                                     command=lambda: self.search(self.search_entry.get()),
                                     kind="primary", height=36, radius=9, min_width=84)
        self.search_btn.pack(side="left", padx=(8, 0))

        self.hint = tk.Label(self, text=T("gallery.source_hint"), bg=th.c("card"),
                             fg=th.c("text_faint"), font=th.F(8), anchor="w")
        self.hint.pack(fill="x", padx=18, pady=(6, 6))

        body = tk.Frame(self, bg=th.c("card"))
        body.pack(fill="both", expand=True, padx=16)

        self.list_scroll = ScrollFrame(body, bg_key="card")
        self.list_scroll.pack(side="left", fill="both", expand=True)
        self.list_scroll.canvas.configure(width=330)

        divider = tk.Frame(body, bg=th.c("border"), width=1)
        divider.pack(side="left", fill="y", padx=10)

        self.detail = tk.Frame(body, bg=th.c("card"))
        self.detail.pack(side="left", fill="both", expand=True)
        self.detail_name = tk.Label(self.detail, text=T("gallery.desc_ph"), bg=th.c("card"),
                                    fg=th.c("text"), font=th.F(12, "bold"), anchor="w")
        self.detail_name.pack(fill="x")
        self.detail_desc = tk.Label(self.detail, text="", bg=th.c("card"), fg=th.c("text_muted"),
                                    font=th.F(9), anchor="w", justify="left", wraplength=460)
        self.detail_desc.pack(fill="x", pady=(6, 4))
        self.detail_meta = tk.Label(self.detail, text="", bg=th.c("card"), fg=th.c("text_faint"),
                                    font=th.F(8), anchor="w")
        self.detail_meta.pack(fill="x")
        self.ver_title = tk.Label(self.detail, text="", bg=th.c("card"), fg=th.c("text_muted"),
                                  font=th.F(9, "bold"), anchor="w")
        self.ver_title.pack(fill="x", pady=(12, 4))
        self.tag_scroll = ScrollFrame(self.detail, bg_key="card")

        # 底部：进度
        self.footer = tk.Frame(self, bg=th.c("card"))
        self.footer.pack(fill="x", padx=16, pady=(8, 14))
        self.progress = ProgressBar(self.footer, height=8, bg=th.c("card"))
        self.progress.pack(fill="x")
        row = tk.Frame(self.footer, bg=th.c("card"))
        row.pack(fill="x", pady=(6, 0))
        self.progress_label = tk.Label(row, text=T("app.ready"), bg=th.c("card"),
                                       fg=th.c("text_muted"), font=th.F(8), anchor="w")
        self.progress_label.pack(side="left")
        self.close_btn = PillButton(row, T("close"), command=self.destroy, kind="ghost",
                                    height=30, radius=9)
        self.close_btn.pack(side="right")

    # ------------------------------------------------ 数据加载
    def reload_installed(self):
        def work():
            try:
                return {m.get("name", "") for m in self.app.client.tags()}
            except Exception:
                return set()

        self.app.run_async(work, lambda res, err: self._set_installed(res or set()))

    def _set_installed(self, names: set):
        if not self._alive():
            return
        self.installed = set(names)
        if self.selected:
            self._render_tags()

    def search(self, query: str = ""):
        self.progress_label.configure(text=T("gallery.loading"))
        self._clear_list()

        def work():
            try:
                return {"models": fetch_models(query), "offline": False}
            except Exception as exc:
                return {"models": list(FALLBACK_MODELS), "offline": True, "error": str(exc)}

        def done(result, error):
            if not self._alive():
                return
            if error or not result:
                self.progress_label.configure(text=T("gallery.load_failed", error))
                return
            self.models = result["models"]
            if result.get("offline"):
                self.progress_label.configure(text=T("gallery.offline_hint"))
                self.app.log_event("WARN", f"gallery offline: {result.get('error')}")
            else:
                self.progress_label.configure(text=T("gallery.loaded_n", len(self.models)))
            self._render_list()

        self.app.run_async(work, done)

    def reload(self):
        self.search(self.search_entry.get())

    def _clear_list(self):
        self.list_scroll.clear()
        self._row_widgets.clear()

    def _render_list(self):
        if not self._alive():
            return
        self._clear_list()
        if not self.models:
            tk.Label(self.list_scroll.inner, text=T("gallery.no_result"), bg=th.c("card"),
                     fg=th.c("text_faint"), font=th.F(9)).pack(padx=10, pady=20, anchor="w")
            return
        for model in self.models:
            name = model.get("name", "")
            card = tk.Frame(self.list_scroll.inner, bg=th.c("card"), padx=10, pady=8,
                            cursor="hand2")
            card.pack(fill="x", padx=4, pady=2)
            title = tk.Label(card, text=name, bg=th.c("card"), fg=th.c("text"),
                             font=th.F(10, "bold"), anchor="w")
            title.pack(fill="x")
            desc = (model.get("description") or "").strip()
            if desc:
                tk.Label(card, text=desc[:110] + ("…" if len(desc) > 110 else ""),
                         bg=th.c("card"), fg=th.c("text_faint"), font=th.F(8), anchor="w",
                         justify="left", wraplength=290).pack(fill="x", pady=(2, 0))
            for widget in (card, title) + tuple(card.winfo_children()):
                widget.bind("<Button-1>", lambda _e, n=name: self.select_model(n))
            self._row_widgets[name] = card
        self._highlight()

    def select_model(self, name: str):
        self.selected = name
        self._highlight()
        info = next((m for m in self.models if m.get("name") == name), {})
        self.detail_name.configure(text=name)
        self.detail_desc.configure(text=info.get("description") or "")
        caps = info.get("caps") or []
        meta = []
        if info.get("updated"):
            meta.append(f"{T('gallery.updated')} {info['updated']}")
        if caps:
            meta.append(f"{T('gallery.capabilities')}: {', '.join(caps)}")
        self.detail_meta.configure(text="    ".join(meta))
        self.tags = []
        self.sizes = {}
        self.ver_title.configure(text=T("gallery.loading"))
        self._render_tags()
        self._load_tags(name)

    def _load_tags(self, model: str):
        fallback = next((m.get("tags", []) for m in FALLBACK_MODELS if m.get("name") == model), [])

        def work():
            try:
                tags = fetch_tags(model)
            except Exception:
                tags = list(fallback)
            return tags

        def done(tags, error):
            if self.selected != model:
                return
            self.tags = tags or list(fallback)
            self.ver_title.configure(
                text=f"{T('gallery.versions')} · {len(self.tags)}" if self.tags
                else T("gallery.no_version"))
            self._render_tags()
            threading.Thread(target=self._load_sizes, args=(model, list(self.tags)),
                             daemon=True).start()

        self.app.run_async(work, done)

    def _load_sizes(self, model: str, tags: list):
        """并发获取各版本体积（单个请求较慢，串行会拖很久）。"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        targets = tags[:14]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch_tag_size, model, tag): tag for tag in targets}
            for future in as_completed(futures):
                tag = futures[future]
                try:
                    size = future.result()
                except Exception:
                    size = 0
                if size:
                    self.queue.put(("size", (model, tag, size)))

    # ------------------------------------------------ 版本渲染
    def _render_tags(self):
        if not self._alive():
            return
        # 注意：滚动容器的直接子控件是 canvas 与滚动条，内容在 .inner 里
        self.tag_scroll.clear()
        self._tag_widgets.clear()
        if not self.tags:
            return
        if not self.tag_scroll.winfo_ismapped():
            self.tag_scroll.pack(fill="both", expand=True)
        for tag in self.tags:
            full = f"{self.selected}:{tag}"
            row = tk.Frame(self.tag_scroll.inner, bg=th.c("card_alt"), padx=12, pady=8)
            row.pack(fill="x", pady=3)
            left = tk.Frame(row, bg=th.c("card_alt"))
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=full, bg=th.c("card_alt"), fg=th.c("text"),
                     font=th.F(10, "bold"), anchor="w").pack(fill="x")
            size = self.sizes.get(tag)
            size_text = human_size(size) if size else T("gallery.size_unknown")
            tk.Label(left, text=f"{T('gallery.size')} {size_text}", bg=th.c("card_alt"),
                     fg=th.c("text_muted"), font=th.F(8), anchor="w").pack(fill="x", pady=(2, 0))
            if full in self.installed:
                tk.Label(row, text=T("gallery.installed"), bg=th.c("chip"),
                         fg=th.c("chip_text"), font=th.F(8, "bold"), padx=8, pady=2).pack(side="right")
            else:
                PillButton(row, T("gallery.download"), kind="primary", height=30, radius=8,
                           font=th.F(9), bg=th.c("card_alt"),
                           command=lambda t=tag: self.download(t)).pack(side="right")
            self._tag_widgets[tag] = row

    def _highlight(self):
        for name, card in self._row_widgets.items():
            active = name == self.selected
            color = th.c("chip") if active else th.c("card")
            card.configure(bg=color)
            for child in card.winfo_children():
                child.configure(bg=color)

    # ------------------------------------------------ 下载
    def download(self, tag: str):
        if self.pulling:
            return
        full = f"{self.selected}:{tag}"
        if not self.selected:
            self.progress_label.configure(text=T("gallery.choose_version"))
            return
        self.pulling = True
        self.cancel.clear()
        self.pull_meter = RateMeter()
        self.progress.set_value(0.0)
        self.progress_label.configure(text=T("gallery.downloading", full))
        self.app.log_event("INFO", f"gallery pull {full}")

        client = self.app.client
        q = self.queue
        cancel = self.cancel
        started = time.time()

        def worker():
            try:
                for chunk in client.pull_stream(full):
                    if cancel.is_set():
                        break
                    q.put(("pull", chunk))
                ok = not cancel.is_set()
            except Exception as exc:
                ok = False
                q.put(("pull_error", str(exc)))
            q.put(("pull_done", (full, ok)))

        threading.Thread(target=worker, daemon=True).start()
        self._pull_started = started

    # ------------------------------------------------ 事件循环
    def _pump(self):
        if not self._alive():
            return
        try:
            while True:
                try:
                    kind, payload = self.queue.get_nowait()
                    self._handle(kind, payload)
                except queue.Empty:
                    break
                except Exception as exc:            # 单条消息出错不影响后续
                    self.app.log_event("ERROR", f"gallery msg {kind}: {exc}")
        finally:
            if self._alive():
                self.after(120, self._pump)

    def _handle(self, kind: str, payload):
        if kind == "size":
            model, tag, size = payload
            if model == self.selected:
                self.sizes[tag] = size
                self._render_tags()
        elif kind == "pull":
            total = payload.get("total") or 0
            done = payload.get("completed") or 0
            status = payload.get("status") or ""
            if total:
                self.progress.set_value(done / total)
                rate = self.pull_meter.update(done, payload.get("digest") or "")
                text = f"{status}  {human_size(done)} / {human_size(total)}"
                if rate > 0:
                    text += f"  {human_size(rate)}/s"
            else:
                text = status
            if payload.get("error"):
                text = f"{T('error')}: {payload['error']}"
            self.progress_label.configure(text=text)
        elif kind == "pull_error":
            self.pulling = False
            self.pull_error = str(payload)
            self.progress_label.configure(text=T("chat.error", payload))
            self.app.log_event("ERROR", f"gallery pull: {payload}")
        elif kind == "pull_done":
            self.pulling = False
            name, ok = payload if isinstance(payload, tuple) else (payload, True)
            if ok:
                # 核实服务端真的装上了（分块账本损坏时会"返回成功但没装"）
                try:
                    names = [m.get("name") for m in (self.app.client.tags() or [])]
                    installed = name in names
                except Exception:
                    installed = False
                if not installed:
                    ok = False
                    self.pull_error = T("download.not_installed")
                    self.app.log_event(
                        "ERROR", f"gallery pull finished but {name} is not installed")
            if ok:
                self.progress.set_value(1.0)
                self.progress_label.configure(text=T("gallery.done", name))
                self.app.toast(T("gallery.done", name))
                self.app.log_event("INFO", f"gallery pull ok: {name}")
            else:
                # 失败：分片保留，可再次点击「下载」续传；模型页也会出现继续入口
                reason = getattr(self, "pull_error", "") or T("vision.interrupted")
                self.progress_label.configure(text=T("vision.failed_keep", name, reason))
                self.app.log_event("WARN", f"gallery pull incomplete: {name} ({reason})")
            self.reload_installed()
            self.app.refresh_models_view()

    # ------------------------------------------------ 主题 / 语言
    def apply_theme(self):
        self.configure(bg=th.c("card"))
        self.title_label.configure(bg=th.c("card"), fg=th.c("text"))
        self.hint.configure(bg=th.c("card"), fg=th.c("text_faint"))
        for frame in (self.list_scroll, self.tag_scroll):
            frame.apply_theme("card")
        self.detail.configure(bg=th.c("card"))
        for widget in (self.detail_name, self.detail_desc, self.detail_meta, self.ver_title):
            widget.configure(bg=th.c("card"))
        self.detail_name.configure(fg=th.c("text"))
        self.detail_desc.configure(fg=th.c("text_muted"))
        self.detail_meta.configure(fg=th.c("text_faint"))
        self.ver_title.configure(fg=th.c("text_muted"))
        self.footer.configure(bg=th.c("card"))
        self.progress.apply_theme(th.c("card"))
        self.progress_label.configure(bg=th.c("card"), fg=th.c("text_muted"))
        self.progress_label.master.configure(bg=th.c("card"))
        self.search_entry.configure(bg=th.c("card_alt"), fg=th.c("text"),
                                    insertbackground=th.c("accent"),
                                    highlightbackground=th.c("border"),
                                    highlightcolor=th.c("accent"))
        self.search_entry.master.configure(bg=th.c("card"))
        for btn in (self.search_btn, self.refresh_btn, self.close_btn):
            btn.apply_theme(th.c("card"))
        self._render_list()
        self._render_tags()
        try:
            th.migrate_colors(self)
        except Exception:
            pass

    def apply_texts(self):
        self.title(T("gallery.title"))
        self.title_label.configure(text=T("gallery.title"))
        self.hint.configure(text=T("gallery.source_hint"))
        self.search_btn.set_text(T("gallery.search"))
        self.refresh_btn.set_text(T("gallery.refresh"))
        self.close_btn.set_text(T("close"))
        self.ver_title.configure(text=f"{T('gallery.versions')} · {len(self.tags)}")
        self._render_tags()

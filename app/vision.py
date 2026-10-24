"""识图支持：图片读取/缩放/编码、剪贴板粘贴、视觉模型推荐与下载引导。"""
from __future__ import annotations

import base64
import io
import os
import tkinter as tk

from . import i18n
from . import theme as th
from .i18n import t as T
from .widgets import PillButton, Segmented

try:
    from PIL import Image, ImageGrab, ImageOps, ImageTk

    HAS_PIL = True
except Exception:  # pragma: no cover
    Image = ImageGrab = ImageOps = ImageTk = None
    HAS_PIL = False

# 发给模型的图片长边上限（太大在 CPU 上编码很慢）
MAX_SIDE = 1024
# 存进会话文件的历史图（控制体积）
HISTORY_SIDE = 640
# 界面缩略图
THUMB_SIDE = 200

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")

# 推荐的视觉模型（体积为实测值）
VISION_MODELS = [
    {"name": "qwen3-vl:2b", "size": "1.8 GB",
     "zh": "最快，CPU 上也流畅", "en": "Fastest, smooth on CPU"},
    {"name": "qwen2.5vl:3b", "size": "3.0 GB",
     "zh": "速度与识别效果均衡", "en": "Balanced speed and quality"},
    {"name": "gemma3:4b", "size": "3.1 GB",
     "zh": "通用对话 + 识图", "en": "General chat plus vision"},
]


def _fit(img, max_side: int):
    if max(img.width, img.height) <= max_side:
        return img
    ratio = max_side / float(max(img.width, img.height))
    return img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
                      Image.LANCZOS)


def _encode(img, quality: int = 88) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def process_image(image, name: str = "", path: str = "") -> dict:
    """把 PIL 图片加工成 {b64(发模型), hist(存会话), thumb(显示), w, h, name, path}。"""
    if ImageOps is not None:
        try:
            image = ImageOps.exif_transpose(image)     # 手机照片方向
        except Exception:
            pass
    image = image.convert("RGB")
    width, height = image.size
    big = _fit(image, MAX_SIDE)
    hist = _fit(image, HISTORY_SIDE)
    thumb = _fit(image, THUMB_SIDE)
    return {
        "b64": _encode(big, 88),
        "hist": _encode(hist, 82),
        "thumb": _encode(thumb, 78),
        "w": width,
        "h": height,
        "name": name or (os.path.basename(path) if path else "image"),
        "path": path,
    }


def load_path(path: str) -> dict:
    if not HAS_PIL:
        raise RuntimeError("Pillow not available")
    with Image.open(path) as img:
        img.load()
        return process_image(img, os.path.basename(path), path)


def from_clipboard() -> dict | None:
    """从剪贴板取图片；没有图片返回 None。"""
    if not HAS_PIL:
        return None
    try:
        data = ImageGrab.grabclipboard()
    except Exception:
        return None
    if data is None:
        return None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, str) and os.path.exists(first):
            low = first.lower()
            if low.endswith(IMAGE_EXTS):
                return load_path(first)
        return None
    try:
        return process_image(data, T("vision.clipboard"))
    except Exception:
        return None


def photo_for(b64: str):
    """把 base64 缩略图转成 Tk 图片对象。"""
    if not HAS_PIL or not b64:
        return None
    try:
        raw = base64.b64decode(b64)
        img = Image.open(io.BytesIO(raw))
        img.load()
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


class VisionDialog(tk.Toplevel):
    """当前模型不支持识图时的引导弹窗。

    result = ("download", 模型名) | ("gallery", None) | (None, None)
    """

    def __init__(self, parent, model: str):
        super().__init__(parent)
        self.result: tuple = (None, None)
        self.withdraw()
        self.title(T("vision.title"))
        self.configure(bg=th.c("card"))
        self.resizable(False, False)
        self.transient(parent)

        body = tk.Frame(self, bg=th.c("card"), padx=22, pady=18)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=T("vision.title"), bg=th.c("card"), fg=th.c("text"),
                 font=th.F(12, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, text=T("vision.body", model), bg=th.c("card"), fg=th.c("text_muted"),
                 font=th.F(9), justify="left", wraplength=420, anchor="w").pack(
            fill="x", pady=(10, 4))

        lang = 0 if i18n.current() == "zh" else 1
        options = []
        for item in VISION_MODELS:
            label = f"{item['name'].split(':')[-1]} · {item['size']}"
            options.append((item["name"], label))
        self.seg = Segmented(body, options, height=34, radius=9, seg_width=150,
                             bg=th.c("card"))
        self.seg.pack(pady=(10, 4))
        self.seg.set_value(VISION_MODELS[0]["name"])

        self.desc = tk.Label(body, text="", bg=th.c("card"), fg=th.c("text_faint"),
                             font=th.F(8), anchor="w")
        self.desc.pack(fill="x", pady=(2, 14))

        def sync(_value=None):
            name = self.seg.get_value()
            info = next((m for m in VISION_MODELS if m["name"] == name), {})
            self.desc.configure(text=f"{info.get('name','')} · {info.get('size','')} · "
                                     f"{info.get(lang) or info.get('zh','')}")

        self.seg._command = sync
        sync()

        row = tk.Frame(body, bg=th.c("card"))
        row.pack(fill="x")
        PillButton(row, T("cancel"), command=self._cancel, kind="ghost",
                   bg=th.c("card")).pack(side="right")
        PillButton(row, T("vision.gallery"), command=self._gallery, kind="ghost",
                   bg=th.c("card")).pack(side="right", padx=(0, 8))
        PillButton(row, T("vision.download"), command=self._download, kind="primary",
                   bg=th.c("card")).pack(side="right", padx=(0, 8))

        self.update_idletasks()
        try:
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            self.geometry(f"+{px + max(0, (pw - self.winfo_width()) // 2)}"
                          f"+{py + max(0, (ph - self.winfo_height()) // 3)}")
        except Exception:
            pass
        self.deiconify()
        self.grab_set()
        self.bind("<Escape>", lambda _e: self._cancel())
        self.wait_window(self)

    def _download(self):
        self.result = ("download", self.seg.get_value())
        self.destroy()

    def _gallery(self):
        self.result = ("gallery", None)
        self.destroy()

    def _cancel(self):
        self.result = (None, None)
        self.destroy()

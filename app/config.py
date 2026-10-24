"""配置读写：JSON 持久化到 %APPDATA%\\DeepSeekController\\config.json"""
from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

APP_DIR_NAME = "AIChat"
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP_DIR_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    "theme": "auto",
    "accent": "auto",            # auto（跟随 Windows）| blue/teal/green/...              # dark | light
    "lang": "zh",                 # zh | en
    "model": "deepseek-r1:7b",
    "host": "http://127.0.0.1:11434",
    "ollama_dir": r"D:\Ollama",
    "models_dir": r"D:\Ollama\models",
    "export_dir": "",
    "background": {
        "source": "",             # 本地图片绝对路径，空则使用内置渐变
        "preset": "auto",     # 内置渐变 id
        "blur": 0,                # 0-40 高斯模糊
        "dim": 35,                # 0-85 压暗百分比
        "library": [],            # 背景库（图片路径列表）
    },
    "params": {
        "temperature": 0.6,
        "top_p": 0.95,
        "num_thread": 14,
        "num_ctx": 4096,
        "num_predict": -1,        # -1 = 不限
    },
    "search": {
        "mode": "off",            # off | quick | deep（deep=多查询+多引擎+批量正文）
        "backend": "auto",        # auto | bing | bing_html | so360 | baidu
        "count": 10,               # 每个查询取多少条结果
        "pages": 2,
        "skip_definitions": True,   # 纯字词释义不联网（专业术语除外）               # >0 抓前 N 篇正文；0 只用摘要；-1 全部抓
        "page_chars": 1200,       # 每篇正文最多取多少字符（0 = 不限）
        "context_chars": 3000,    # 注入模型的总上下文上限（0 = 不限）
        "sub_queries": 5,         # 深度模式：把问题展开成几个查询
        "multi_engine": True,     # 深度模式：合并 Bing/360/百度
        "auto_ctx": True,         # 上下文不够时自动提升 num_ctx
        "max_ctx": 32768,         # 自动提升的上限
        "enabled": False,         # 兼容旧版本配置
    },
    "window": {"w": 1360, "h": 860, "x": None, "y": None},
    "last_session": "",           # 上次打开的会话 id（启动时自动恢复）
    "download": {
        "pending_model": "",      # 上次未下载完的模型（中断后可续传）
    },
}


def _migrate_legacy() -> None:
    """首次运行时，把旧版 DeepSeekController 的配置与会话搬过来。

    只在新目录为空时执行，之后不再覆盖（避免把新设置改回去）。
    """
    legacy = CONFIG_DIR.parent / "DeepSeekController"
    if not legacy.exists() or CONFIG_DIR.exists():
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        old_cfg = legacy / "config.json"
        if old_cfg.exists():
            shutil.copy2(old_cfg, CONFIG_FILE)
        old_s = legacy / "sessions"
        if old_s.exists():
            shutil.copytree(old_s, CONFIG_DIR / "sessions")
    except Exception:
        pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    """读取配置，缺失字段用默认值补齐。"""
    _migrate_legacy()
    data = {}
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return _merge(DEFAULTS, data if isinstance(data, dict) else {})


def save(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def ollama_exe(cfg: dict) -> str:
    return str(Path(cfg.get("ollama_dir", r"D:\Ollama")) / "ollama.exe")

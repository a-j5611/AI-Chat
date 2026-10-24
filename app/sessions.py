"""会话存储：把对话按「会话」为单位保存在本地，供左侧列表加载/删除。

目录结构：
    %APPDATA%\\DeepSeekController\\sessions\\
        index.json          会话元信息列表（标题/时间/条数），避免逐个读大文件
        <session_id>.json   单个会话的完整消息（含思考过程与参考来源）
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import time
import uuid
from pathlib import Path

from . import config as cfgmod

SESSIONS_DIR = cfgmod.CONFIG_DIR / "sessions"
INDEX_FILE = SESSIONS_DIR / "index.json"
MAX_TITLE = 40


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def title_from(messages: list) -> str:
    """用第一条用户消息生成标题。"""
    for msg in messages or []:
        if msg.get("role") == "user":
            text = re.sub(r"\s+", " ", (msg.get("content") or "")).strip()
            if text:
                return text[:MAX_TITLE] + ("…" if len(text) > MAX_TITLE else "")
    return ""


def rel_time(stamp: str) -> str:
    """把 ISO 时间转成「刚刚 / 12:30 / 昨 12:30 / 03-15」这种简短形式。"""
    from .i18n import t as T

    try:
        when = _dt.datetime.fromisoformat(stamp)
    except Exception:
        return ""
    now = _dt.datetime.now()
    delta = now - when
    if delta.total_seconds() < 60:
        return T("time.just_now")
    if when.date() == now.date():
        return when.strftime("%H:%M")
    if (now.date() - when.date()).days == 1:
        return T("time.yesterday") + " " + when.strftime("%H:%M")
    if when.year == now.year:
        return when.strftime("%m-%d %H:%M")
    return when.strftime("%Y-%m-%d")


class SessionStore:
    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory or SESSIONS_DIR)

    # -------------------------------------------------- 基础
    def _ensure(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _path(self, session_id: str) -> Path:
        safe = re.sub(r"[^0-9A-Za-z._-]", "_", session_id or "x")
        return self.dir / f"{safe}.json"

    def _index_path(self) -> Path:
        return self.dir / "index.json"

    # -------------------------------------------------- 索引
    def _read_index(self) -> list[dict]:
        self._ensure()
        try:
            data = json.loads(self._index_path().read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("id")]
        except Exception:
            pass
        return self._rebuild_index()

    def _write_index(self, items: list[dict]) -> None:
        self._ensure()
        try:
            self._index_path().write_text(json.dumps(items, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        except Exception:
            pass

    def _rebuild_index(self) -> list[dict]:
        """索引丢失时扫描目录重建。"""
        items: list[dict] = []
        try:
            for path in self.dir.glob("*.json"):
                if path.name == "index.json":
                    continue
                meta = self._meta_of(path)
                if meta:
                    items.append(meta)
        except Exception:
            pass
        items.sort(key=lambda d: d.get("updated", ""), reverse=True)
        self._write_index(items)
        return items

    def _meta_of(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        messages = data.get("messages") or []
        return {
            "id": data.get("id") or path.stem,
            "title": data.get("title") or title_from(messages) or "",
            "created": data.get("created", ""),
            "updated": data.get("updated", ""),
            "count": len(messages),
            "model": data.get("model", ""),
        }

    # -------------------------------------------------- 对外 API
    def list(self) -> list[dict]:
        items = self._read_index()
        items.sort(key=lambda d: d.get("updated", ""), reverse=True)
        return items

    def load(self, session_id: str) -> dict | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        data.setdefault("id", session_id)
        data.setdefault("messages", [])
        return data

    def save(self, session: dict) -> None:
        """写入单个会话并刷新索引。"""
        if not session:
            return
        self._ensure()
        session = dict(session)
        session["id"] = session.get("id") or new_id()
        session["updated"] = _now()
        session.setdefault("created", session["updated"])
        messages = session.get("messages") or []
        if not session.get("title"):
            session["title"] = title_from(messages) or ""
        try:
            self._path(session["id"]).write_text(
                json.dumps(session, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return
        items = [d for d in self._read_index() if d.get("id") != session["id"]]
        items.append({
            "id": session["id"],
            "title": session.get("title", ""),
            "created": session.get("created", ""),
            "updated": session["updated"],
            "count": len(messages),
            "model": session.get("model", ""),
        })
        items.sort(key=lambda d: d.get("updated", ""), reverse=True)
        self._write_index(items)

    def delete(self, session_id: str) -> None:
        try:
            self._path(session_id).unlink(missing_ok=True)
        except Exception:
            pass
        items = [d for d in self._read_index() if d.get("id") != session_id]
        self._write_index(items)

    def rename(self, session_id: str, title: str) -> None:
        data = self.load(session_id)
        if not data:
            return
        data["title"] = (title or "").strip()[:MAX_TITLE]
        self.save(data)


_store: SessionStore | None = None


def store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


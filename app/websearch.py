"""联网搜索：抓取搜索结果并抽取正文，供本地模型做检索增强（RAG）。

设计要点
  * 不依赖任何 API Key，直接解析公开搜索页；
  * Bing 的 RSS 出口最快最干净（约 0.3s / 6KB），作为主源；
    失败时依次回退 Bing HTML -> 360 -> 百度；
  * DuckDuckGo / Wikipedia / Searx 在部分网络（如国内）不可达，故不作主源。

注意：这些站点可能随时调整结构，解析函数都做了“拿不到结果就换下一个源”的容错。
"""
from __future__ import annotations

import html as _html
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

BACKENDS = ("auto", "bing", "bing_html", "so360", "sogou", "baidu")
BACKEND_LABELS = {
    "auto": ("自动", "Auto"),
    "bing": ("Bing", "Bing"),
    "bing_html": ("Bing 网页", "Bing HTML"),
    "so360": ("360", "360"),
    "sogou": ("搜狗", "Sogou"),
    "baidu": ("百度", "Baidu"),
}
# 自动回退顺序（百度现在经常返回“安全验证”页，放最后）
AUTO_ORDER = ("bing", "bing_html", "so360", "sogou", "baidu")
# 多引擎合并时使用的引擎（顺序即优先级）
MERGE_ENGINES = ("bing", "so360", "sogou")
MODES = ("off", "quick", "deep")


class WebSearchError(Exception):
    pass


# ============================================================ 基础请求
def _get(url: str, timeout: float = 15) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _clean(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _valid(url: str) -> bool:
    return bool(url) and url.startswith("http") and "bing.com/search" not in url


# ============================================================ 各搜索引擎解析
def _parse_bing_rss(xml: str, count: int) -> list[dict]:
    out: list[dict] = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def pick(tag: str) -> str:
            m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S)
            if not m:
                return ""
            value = m.group(1)
            value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", value, flags=re.S)
            return _html.unescape(value).strip()

        url = pick("link")
        if not _valid(url):
            continue
        out.append({"title": _clean(pick("title")) or url, "url": url,
                    "snippet": _clean(pick("description"))})
        if len(out) >= count:
            break
    return out


def _parse_bing_html(page: str, count: int) -> list[dict]:
    out: list[dict] = []
    for block in re.findall(r'(?is)<li class="b_algo".*?</li>', page):
        m = re.search(r'(?is)<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not m:
            continue
        url, title = m.group(1), _clean(m.group(2))
        if not _valid(url):
            continue
        sm = re.search(r"(?is)<p[^>]*>(.*?)</p>", block)
        out.append({"title": title or url, "url": url,
                    "snippet": _clean(sm.group(1)) if sm else ""})
        if len(out) >= count:
            break
    return out


def _parse_so360(page: str, count: int) -> list[dict]:
    out: list[dict] = []
    for block in re.findall(r'(?is)<li class="res-list.*?</li>', page):
        m = re.search(r'(?is)<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block)
        if not m:
            continue
        url, title = m.group(1), _clean(m.group(2))
        if not _valid(url):
            continue
        sm = re.search(r'(?is)<p class="res-desc"[^>]*>(.*?)</p>', block) or \
            re.search(r'(?is)<div class="res-rich[^"]*"[^>]*>(.*?)</div>', block)
        out.append({"title": title or url, "url": url,
                    "snippet": _clean(sm.group(1)) if sm else ""})
        if len(out) >= count:
            break
    return out


def _parse_baidu(page: str, count: int) -> list[dict]:
    out: list[dict] = []
    for block in re.findall(r'(?is)<div[^>]+class="result[^"]*c-container[^"]*".*?</div>\s*</div>', page):
        m = re.search(r'(?is)<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', block)
        if not m:
            continue
        url, title = m.group(1), _clean(m.group(2))
        if not _valid(url) or not title:
            continue
        am = re.search(r'(?is)<span[^>]*class="[^"]*content-right[^"]*"[^>]*>(.*?)</span>', block) or \
            re.search(r'(?is)<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', block)
        out.append({"title": title, "url": url,
                    "snippet": _clean(am.group(1)) if am else ""})
        if len(out) >= count:
            break
    return out


def _parse_sogou(page: str, count: int) -> list[dict]:
    """搜狗：结果块 class=vrwrap，标题在 h3.vr-title>a，链接是站内跳转。"""
    out: list[dict] = []
    pattern = re.compile(
        r'(?is)<h3[^>]*class="[^"]*vr-title[^"]*"[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>')
    for match in pattern.finditer(page):
        href = _html.unescape(match.group(1))
        title = _clean(match.group(2))
        if not title:
            continue
        url = href if href.startswith("http") else "https://www.sogou.com" + href
        if not _valid(url):
            continue
        chunk = page[match.end(): match.end() + 1600]
        sm = (re.search(r'(?is)<div class="text-layout">(.*?)</div>', chunk)
              or re.search(r"(?is)<p[^>]*>(.*?)</p>", chunk))
        out.append({"title": title, "url": url,
                    "snippet": _clean(sm.group(1)) if sm else ""})
        if len(out) >= count:
            break
    return out


_PARSERS = {
    "bing": ("https://cn.bing.com/search?q={}&format=rss", _parse_bing_rss),
    "bing_html": ("https://cn.bing.com/search?q={}", _parse_bing_html),
    "so360": ("https://www.so.com/s?q={}", _parse_so360),
    "sogou": ("https://www.sogou.com/web?query={}", _parse_sogou),
    "baidu": ("https://www.baidu.com/s?wd={}", _parse_baidu),
}


# ============================================================ 对外接口
def _search_one(name: str, query: str, count: int, timeout: float) -> list[dict]:
    template, parser = _PARSERS[name]
    url = template.format(urllib.parse.quote(query))
    page = _get(url, timeout=timeout)
    results = parser(page, count)
    return [r for r in results if r.get("url")]


def search(query: str, backend: str = "auto", count: int = 10,
           timeout: float = 8) -> tuple[list[dict], str]:
    """返回 (结果列表, 实际使用的引擎)。全部失败时抛 WebSearchError。

    多引擎**并发竞速**：谁先给出结果就用谁，其余不再等待。
    （旧实现是串行 + 每个 15s，遇到慢引擎会把整次搜索拖到几十秒）
    """
    query = (query or "").strip()
    if not query:
        return [], ""

    cache_key = f"{backend}|{count}|{query}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    order = [n for n in (AUTO_ORDER if backend in ("auto", "", None) else (backend,))
             if n in _PARSERS]
    if not order:
        raise WebSearchError("no backend available")

    errors: list[str] = []
    # 只对前 3 个引擎竞速：再多意义不大，反而增加请求量
    race = order[:3]
    with ThreadPoolExecutor(max_workers=len(race)) as pool:
        futures = {pool.submit(_search_one, name, query, count, timeout): name
                   for name in race}
        try:
            for future in as_completed(futures, timeout=timeout + 2):
                name = futures[future]
                try:
                    results = future.result()
                except Exception as exc:
                    errors.append(f"{name}: {type(exc).__name__}")
                    continue
                if results:
                    results, dropped = filter_definitions(results, query)
                    if results:
                        _cache_put(cache_key, results, name)
                        return results, name
                    errors.append(f"{name}: only definitions ({dropped})")
                else:
                    errors.append(f"{name}: empty")
        except TimeoutError:
            errors.append("race: timeout")

    # 竞速超时的兜底：剩下的引擎再试一次（仍然并发）
    rest = order[len(race):]
    if rest:
        with ThreadPoolExecutor(max_workers=len(rest)) as pool:
            futures = {pool.submit(_search_one, name, query, count, timeout): name
                       for name in rest}
            for future in as_completed(futures, timeout=timeout + 2):
                name = futures[future]
                try:
                    results = future.result()
                except Exception as exc:
                    errors.append(f"{name}: {type(exc).__name__}")
                    continue
                if results:
                    results, _ = filter_definitions(results, query)
                    if results:
                        _cache_put(cache_key, results, name)
                        return results, name
    raise WebSearchError("; ".join(errors) or "no backend available")


# ---------------------------------------------------------------- 字词释义过滤
# 词典 / 释义站点：查"某词什么意思"时它们是噪音，直接丢弃
DEFINITION_HOSTS = (
    "zdic.net",              # 汉典
    "hanyu.baidu.com",       # 百度汉语
    "dict.baidu.com", "fanyi.baidu.com",
    "youdao.com", "dict.youdao.com",
    "iciba.com",
    "dict.cn",
    "chazidian.com", "cidianwang.com", "hanyuzidian.org", "911chazi.com",
    "hydcd.com",             # 汉语大词典
    "chengyu.t086.com",
    "wiktionary.org", "dictionary.com", "merriam-webster.com",
    "collinsdictionary.com", "thefreedictionary.com", "vocabulary.com",
    "wordreference.com", "thesaurus.com", "linguee.com", "linguee.cn",
    "translate.google.com", "jisho.org", "weblio.jp", "en.dict.naver.com",
)

# 标题里出现这些，多半是释义/字词类页面
DEFINITION_TITLE_HINTS = (
    "是什么意思", "的意思", "的解释", "的含义", "的读音", "的拼音", "怎么读",
    "近义词", "反义词", "造句", "释义", "词典", "字典", "汉语词典",
    "meaning of", "definition of", "what does", "synonyms", "antonyms",
    "translation of", "how to pronounce",
)

# "这个词什么意思"这类提问特征
_WORD_LOOKUP_PATTERNS = (
    r"是什么意思", r"什么意思", r"的含义", r"含义是", r"释义", r"的词义",
    r"怎么读", r"读音", r"拼音", r"怎么念", r"念什么",
    r"近义词", r"反义词", r"同义词", r"造句", r"怎么拼",
    r"翻译成", r"英文怎么说", r"中文意思", r"用英语怎么说",
    r"what does .{1,40} mean", r"meaning of", r"definition of",
    r"how to pronounce", r"translate .{1,40} into", r"synonym",
)

# 专业技术词表：命中说明是"专业术语"，允许查释义/百科
TECH_TERMS = (
    "算法", "协议", "框架", "模型", "编译器", "解释器", "内核", "并发", "并行",
    "内存", "缓存", "线程", "进程", "协程", "锁", "事务", "索引", "数据库",
    "容器", "虚拟化", "部署", "接口", "类型系统", "垃圾回收", "加密", "哈希",
    "网络", "带宽", "延迟", "吞吐", "序列化", "反序列化", "中间件", "微服务",
    "架构", "重构", "依赖注入", "设计模式", "状态机", "正则", "指针", "地址空间",
    "编译", "链接", "调度", "心跳", "压测", "推理", "训练", "梯度", "量化",
    "注意力机制", "神经网络", "分词", "向量", "嵌入", "检索", "召回", "排序",
    "多模态", "提示词", "上下文", "令牌", "分布式", "一致性", "负载均衡",
    "api", "sdk", "http", "tcp", "udp", "tls", "ssl", "dns", "cpu", "gpu",
    "ram", "ssd", "orm", "sql", "json", "yaml", "html", "css", "js", "ts",
    "rust", "golang", "python", "java", "kotlin", "swift", "linux", "windows",
    "docker", "k8s", "kubernetes", "git", "redis", "kafka", "nginx", "grpc",
    "llm", "gpt", "bert", "transformer", "rag", "embedding", "token",
    "quantization", "fine-tune", "moe", "cuda", "tensor", "kernel",
)


def is_word_lookup(text: str) -> bool:
    """问题是不是在问"某个词是什么意思"。"""
    low = (text or "").strip().lower()
    if not low or len(low) > 80:          # 长问题通常不是单纯查词
        return False
    return any(re.search(pat, low) for pat in _WORD_LOOKUP_PATTERNS)


def is_technical(text: str) -> bool:
    """是不是专业/技术性内容（专业术语允许查释义）。"""
    low = (text or "").lower()
    if not low:
        return False
    if re.search(r"[a-z][a-z0-9+#._-]{1,}", low):     # 含拉丁词/缩写/版本号
        return True
    if re.search(r"[A-Z]{2,}", text or ""):           # 全大写缩写
        return True
    return any(term in low for term in TECH_TERMS)


def is_definition_result(result: dict) -> bool:
    """这条结果是不是词典/释义类页面。"""
    url = (result.get("url") or "").lower()
    title = (result.get("title") or "").lower()
    for host in DEFINITION_HOSTS:
        if host in url:
            return True
    for hint in DEFINITION_TITLE_HINTS:
        if hint in title:
            return True
    return False


def filter_definitions(results: list[dict], query: str) -> tuple[list[dict], int]:
    """丢掉释义类结果（除非查的是专业术语）。返回 (保留的结果, 丢弃数)。"""
    if is_technical(query):
        return results, 0
    kept, dropped = [], 0
    for item in results:
        if is_definition_result(item):
            dropped += 1
        else:
            kept.append(item)
    return kept, dropped


def should_skip_search(question: str) -> bool:
    """纯字词释义问题（且非专业术语）→ 不联网，直接让模型回答。"""
    return is_word_lookup(question) and not is_technical(question)


# ---------------------------------------------------------------- 结果缓存
_CACHE: dict[str, tuple[float, list[dict], str]] = {}
_CACHE_TTL = 600.0
_CACHE_MAX = 128


def _cache_get(key: str):
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, results, engine = hit
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return [dict(r) for r in results], engine


def _cache_put(key: str, results: list[dict], engine: str) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        for old_key, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:32]:
            _CACHE.pop(old_key, None)
    _CACHE[key] = (time.time(), [dict(r) for r in results], engine)


# 这些站点要么 JS 重渲染、要么在本网络下极慢，直接跳过不浪费时间
SKIP_HOSTS = (
    "github.com", "githubusercontent.com", "huggingface.co", "youtube.com",
    "youtu.be", "twitter.com", "x.com", "facebook.com", "instagram.com",
    "apps.apple.com", "play.google.com", "zhihu.com",
)


def _maybe_redirect(page: str) -> str:
    """从 meta refresh / JS location 跳转页里取出真实地址。"""
    match = re.search(r'(?is)<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*url=([^"\'>\s]+)',
                      page)
    if not match:
        match = re.search(
            r'(?is)(?:location\.(?:replace|assign)\s*\(\s*|location\.href\s*=\s*'
            r'|window\.location\s*=\s*)["\']([^"\']+)["\']', page)
    if not match:
        return ""
    target = _html.unescape(match.group(1)).strip()
    return target if target.startswith("http") else ""


def _extract_main(page: str) -> str:
    """尽量定位网页正文容器，去掉导航/页脚/脚本等噪声。"""
    cleaned = re.sub(
        r"(?is)<(script|style|noscript|svg|iframe|form|button|select|input|head)"
        r"[^>]*>.*?</\1>", " ", page)
    for tag in ("article", "main"):
        match = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", cleaned)
        if match and len(match.group(1)) > 800:
            return match.group(1)
    match = re.search(
        r'(?is)<div[^>]+(?:id|class)="[^"]*(?:article|content|post|entry|main|detail)'
        r'[^"]*"[^>]*>(.*)', cleaned)
    if match and len(match.group(1)) > 800:
        return match.group(1)
    return cleaned


def fetch_page_text(url: str, max_chars: int = 2000, timeout: float = 12) -> str:
    """抓取网页并抽取可读正文（尽力而为，失败或内容过少返回空串）。"""
    host = urllib.parse.urlparse(url).netloc.lower()
    if any(skip in host for skip in SKIP_HOSTS):
        return ""
    try:
        page = _get(url, timeout=timeout)
    except Exception:
        return ""
    text = _to_text(page, max_chars)
    if len(text) < 40:
        # 可能是跳转中转页（360/搜狗的结果链接常见），跟随一次真实地址
        target = _maybe_redirect(page)
        if target and target != url:
            try:
                text = _to_text(_get(target, timeout=timeout), max_chars)
            except Exception:
                text = ""
    return text if len(text) >= 40 else ""


def _to_text(page: str, max_chars: int = 2000) -> str:
    if not page:
        return ""
    body = _extract_main(page)
    body = re.sub(r"(?is)<(nav|footer|aside|header)[^>]*>.*?</\1>", " ", body)
    body = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>", "\n", body)
    text = _html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
    text = re.sub(r"[ \t\xa0\u3000]+", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if len(ln) > 12]          # 丢掉导航碎片
    text = "\n".join(lines)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) < 40 and page:                            # 主容器没内容就退回整页
        whole = _html.unescape(re.sub(r"(?s)<[^>]+>", "\n", page))
        whole = re.sub(r"[ \t\xa0\u3000]+", " ", whole)
        lines = [ln.strip() for ln in whole.split("\n") if len(ln.strip()) > 12]
        text = re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
    return text[:max_chars] if max_chars and max_chars > 0 else text


def enrich(results: list[dict], want: int = 2, max_chars: int = 2000,
           timeout: float = 15, max_try: int = 5, workers: int = 6) -> list[dict]:
    """并发给结果补充网页正文，直到 want 条拿到正文（最多尝试 max_try 个）。

    want <= 0 表示不限制，尽量把所有结果都抓下来（深度检索用）。
    """
    want = len(results) if want is None or want <= 0 else min(want, len(results))
    # 多试一些候选：部分页面是 JS 渲染或跳转链接，抓不到正文，需要往后补
    span = min(len(results), max(want + 6, int(want * 1.6) + 3))
    targets = results[:span]
    if not targets:
        return results
    got = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(fetch_page_text, item["url"], max_chars, timeout): item
                   for item in targets}
        for future in as_completed(futures):
            item = futures[future]
            try:
                text = future.result()
            except Exception:
                text = ""
            if text:
                item["text"] = text
                got += 1
    return results


def build_context(results: list[dict], max_chars: int = 2600,
                  snippet_chars: int = 180) -> str:
    """把结果拼成给模型看的资料块。

    max_chars <= 0 表示不限制长度（“无限制”模式）。
    """
    blocks: list[str] = []
    total = 0
    unlimited = not max_chars or max_chars <= 0
    for idx, item in enumerate(results, 1):
        lines = [f"[{idx}] {item.get('title', '')}", f"URL: {item.get('url', '')}"]
        snippet = (item.get("snippet") or "").strip()
        if snippet:
            lines.append(f"摘要: {snippet[:snippet_chars]}")
        if item.get("text"):
            lines.append(f"正文: {item['text']}")
        block = "\n".join(lines)
        if not unlimited and total + len(block) > max_chars:
            remain = max_chars - total
            if remain > 200:
                blocks.append(block[:remain])
            break
        blocks.append(block)
        total += len(block) + 2
    return "\n\n".join(blocks)


# ============================================================ 多查询 / 多引擎
def _norm_url(url: str) -> str:
    url = (url or "").strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    url = url.split("#")[0].rstrip("/")
    url = re.sub(r"[?&](utm_[^&]+|spm=[^&]+|from=[^&]+)", "", url)
    return url


def _norm_title(title: str) -> str:
    return re.sub(r"[\s\-_|·，。,.!?！？:：]+", "", (title or "").lower())[:24]


def merge_results(groups: list[list[dict]], limit: int = 0) -> list[dict]:
    """合并多组检索结果并按 URL / 标题去重。"""
    merged: list[dict] = []
    seen_url: set[str] = set()
    seen_title: set[str] = set()
    for group in groups:
        for item in group or []:
            key_url = _norm_url(item.get("url", ""))
            key_title = _norm_title(item.get("title", ""))
            if not key_url:
                continue
            if key_url in seen_url or (key_title and key_title in seen_title):
                # 已存在则只补充更长的摘要
                for exist in merged:
                    if _norm_url(exist.get("url", "")) == key_url:
                        if len(item.get("snippet") or "") > len(exist.get("snippet") or ""):
                            exist["snippet"] = item.get("snippet", "")
                        break
                continue
            seen_url.add(key_url)
            if key_title:
                seen_title.add(key_title)
            merged.append(dict(item))
            if limit and len(merged) >= limit:
                return merged
    return merged


def search_many(queries: list[str], backend: str = "auto", count: int = 10,
                engines: tuple = (), timeout: float = 8,
                workers: int = 8) -> tuple[list[dict], dict]:
    """对多个查询（可选多个引擎）并发检索并合并去重。

    返回 (合并后的结果, 统计信息)
    """
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    if not queries:
        return [], {"queries": 0, "engines": 0, "raw": 0, "elapsed": 0.0}
    engine_list = list(engines) if engines else (["auto"] if backend in ("auto", "", None)
                                                 else [backend])
    started = time.time()
    jobs = [(q, eng) for q in queries for eng in engine_list]
    groups: list[list[dict]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(jobs)))) as pool:
        futures = {pool.submit(search, q, eng, count, timeout): (q, eng) for q, eng in jobs}
        for future in as_completed(futures):
            query, engine = futures[future]
            try:
                results, _used = future.result()
                groups.append(results)
            except Exception as exc:
                errors.append(f"{engine}:{query[:12]}:{type(exc).__name__}")
    merged = merge_results(groups, limit=48)
    # 丢掉释义类结果（专业术语除外）
    merged, dropped = filter_definitions(merged, " ".join(queries))
    stats = {
        "dropped_definitions": dropped,
        "queries": len(queries),
        "engines": len(engine_list),
        "jobs": len(jobs),
        "raw": sum(len(g) for g in groups),
        "merged": len(merged),
        "errors": errors,
        "elapsed": time.time() - started,
    }
    return merged, stats


EXPAND_PROMPT = """你是搜索助手。把下面的问题拆成 {n} 个**不同角度**的中文搜索关键词，用于检索资料。
只输出一个 JSON 字符串数组，不要任何解释、不要 markdown 代码块。
示例：["关键词一","关键词二","关键词三"]

问题：{q}
"""


# 中文疑问词/虚词：抽核心词时去掉，避免生成同质化查询
_STOPWORDS = (
    "什么", "需要", "如何", "怎么", "怎样", "多少", "是否", "可以", "吗", "呢",
    "请问", "介绍", "一下", "哪些", "哪个", "为什么", "以及", "并且", "的话",
    "我该", "想要", "想", "能", "不能", "有没有", "推荐", "最好", "应该",
)


def heuristic_queries(question: str, n: int = 4) -> list[str]:
    """不依赖模型的关键词扩展：抽取核心词并生成几个不同角度的查询。"""
    base = re.sub(r"\s+", " ", (question or "").strip())
    core = base
    for word in _STOPWORDS:
        core = core.replace(word, " ")
    core = re.sub(r"[?？。！!，,、；;：:\"'“”（）()\[\]{}]", " ", core)
    core = re.sub(r"\s+", " ", core).strip()
    candidates = [base]
    if core and core != base:
        candidates.append(core)
    if core:
        candidates.append(core + " 教程")
        candidates.append(core + " 要求")
        candidates.append(core + " 参数 配置")
    candidates.append(base + " 详细说明")
    out: list[str] = []
    for q in candidates:
        q = re.sub(r"\s+", " ", q).strip()
        if len(q) > 2 and q not in out:
            out.append(q)
    return out[:max(1, n)]


def parse_query_list(text: str, limit: int = 6) -> list[str]:
    """从模型输出里解析出查询列表（容忍 JSON / 行列表 / 引号列表）。"""
    if not text:
        return []
    out: list[str] = []
    # 去掉思考块（部分推理模型会带  thinking）
    text = re.sub(r"(?is) thinking.*?<｜end▁of▁thinking｜>", " ", text)
    try:
        import json as _json

        match = re.search(r"\[.*?\]", text, re.S)
        if match:
            data = _json.loads(match.group(0))
            if isinstance(data, list):
                out = [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        out = []
    if not out:
        for line in text.splitlines():
            line = re.sub(r"^\s*[\d\-\*\.\)、]+\s*", "", line).strip()
            line = line.strip("\"'“”[]{} ").strip()
            if 1 < len(line) <= 60:
                out.append(line)
    cleaned: list[str] = []
    for q in out:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in cleaned:
            cleaned.append(q)
    return cleaned[:limit]


def expand_queries(question: str, n: int = 4, client=None, model: str = "",
                   timeout: float = 90) -> list[str]:
    """把问题拆成多个检索词。

    推理模型（capabilities 含 thinking）会把内容全放在 thinking 里、content 为空，
    用它拆词既慢又容易失败，因此这类模型直接用启发式规则（毫秒级）；
    普通模型才走一次模型拆解。
    """
    question = (question or "").strip()
    if len(question) < 6 or client is None or not model:
        return heuristic_queries(question, n)
    try:
        caps = client.capabilities(model)
    except Exception:
        caps = []
    if "thinking" in caps:
        return heuristic_queries(question, n)
    try:
        prompt = EXPAND_PROMPT.format(n=max(2, n), q=question[:500])
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.3, "num_predict": 220, "num_ctx": 2048},
        }
        data = client._json("/api/chat", method="POST", payload=payload, timeout=timeout) or {}
        msg = data.get("message") or {}
        text = (msg.get("content") or "") + "\n" + (msg.get("thinking") or "")
        queries = parse_query_list(text, limit=n)
        if len(queries) >= 2:
            return ([question] + [q for q in queries if q != question])[: max(2, n)]
    except Exception:
        pass
    return heuristic_queries(question, n)


SEARCH_SYSTEM_PROMPT = """你是一个可以使用联网搜索结果的助手。下面是刚刚检索到的网页资料：

{context}

要求：
1. 优先依据上述资料回答，不要编造资料中不存在的事实；
2. 引用资料时在句末标注来源编号，例如 [1]、[2]；
3. 如果资料不足以回答问题，请明确说明"资料中没有找到相关内容"，再给出你自己的判断；
4. 用与用户提问相同的语言回答。
"""


def format_sources(results: list[dict]) -> str:
    """给界面/导出用的来源列表（纯文本）。"""
    return "\n".join(f"[{i}] {r.get('title','')}\n    {r.get('url','')}"
                     for i, r in enumerate(results, 1))


def deep_search(question: str, cfg: dict, client=None, model: str = "",
                progress=None) -> dict:
    """深度检索：多查询展开 + 多引擎并发 + 批量抓正文。

    cfg 字段：
      sub_queries  展开成几个查询（含原问题）
      count        每个查询取多少条
      pages        >0 抓前 N 篇正文；0 只用摘要；-1 全部抓
      page_chars   每篇正文最多多少字符（0=不限）
      multi_engine 是否合并多个引擎
    progress(step, info) 用于回报进度
    """
    def note(step, info=None):
        if progress:
            try:
                progress(step, info)
            except Exception:
                pass

    question = (question or "").strip()
    if not question:
        return {"results": [], "queries": [], "stats": {}}

    # 纯"某词什么意思"（且不是专业术语）→ 不联网，模型自己就能答
    if cfg.get("skip_definitions", True) and should_skip_search(question):
        note("skip", T_SKIP_DEFINITION if "T_SKIP_DEFINITION" in globals() else "definition")
        return {"results": [], "queries": [], "skipped": "definition",
                "stats": {"skipped": "definition", "elapsed": 0.0}}

    n = max(2, int(cfg.get("sub_queries", 5) or 5))
    count = max(1, int(cfg.get("count", 10) or 10))
    pages = int(cfg.get("pages", 2) if cfg.get("pages") is not None else 2)
    page_chars = int(cfg.get("page_chars", 2000) or 0)
    engines = MERGE_ENGINES if cfg.get("multi_engine") else ()

    note("expand")
    queries = expand_queries(question, n, client=client, model=model)

    note("search", len(queries))
    results, stats = search_many(queries, backend=cfg.get("backend", "auto"),
                                 count=count, engines=engines, workers=8)

    if pages != 0 and results:
        want = len(results) if pages < 0 else pages
        note("fetch", min(want, len(results)))
        enrich(results, want=want, max_chars=page_chars, workers=8, max_try=len(results))
    stats["queries_list"] = queries
    stats["pages"] = sum(1 for r in results if r.get("text"))
    stats["chars"] = sum(len(r.get("text") or "") + len(r.get("snippet") or "")
                         for r in results)
    note("done", stats)
    return {"results": results, "queries": queries, "stats": stats}


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1 字 1 token，英文约 4 字符 1 token）。"""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other = len(text) - ascii_chars
    return int(ascii_chars / 4 + other * 1.05) + 8


def test_connection(query: str = "DeepSeek", backend: str = "auto",
                    count: int = 3) -> dict:
    """设置页的“测试搜索”。"""
    started = time.time()
    try:
        results, used = search(query, backend=backend, count=count)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed": time.time() - started}
    return {"ok": True, "backend": used, "count": len(results),
            "sample": results[0]["title"] if results else "",
            "elapsed": time.time() - started}

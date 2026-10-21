from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from downloader.platform_auth import (
    browser_cookie_spec,
    resolve_authorized_cookie_file,
)
from infrastructure.cancellation import yt_dlp_cancel_hook

_WBI_KEY_CACHE: dict[str, Any] = {}
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def bilibili_headers(referer: str = "https://www.bilibili.com/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://www.bilibili.com",
        "Referer": referer,
    }


def apply_yt_dlp_auth_options(opts: dict[str, Any], settings: Settings = SETTINGS) -> None:
    opts.setdefault("http_headers", bilibili_headers())
    progress_hooks = list(opts.get("progress_hooks") or [])
    if yt_dlp_cancel_hook not in progress_hooks:
        progress_hooks.append(yt_dlp_cancel_hook)
    opts["progress_hooks"] = progress_hooks
    opts.setdefault("retries", max(0, settings.bilibili_download_retries))
    opts.setdefault("fragment_retries", max(0, settings.bilibili_fragment_retries))
    opts.setdefault("extractor_retries", 3)
    opts.setdefault("file_access_retries", 3)
    opts.setdefault("socket_timeout", max(5, settings.bilibili_socket_timeout))
    opts.setdefault("continuedl", True)
    opts.setdefault("concurrent_fragment_downloads", 1)
    if settings.bilibili_http_chunk_size > 0:
        opts.setdefault("http_chunk_size", settings.bilibili_http_chunk_size)
    if settings.ffmpeg_path:
        opts.setdefault("ffmpeg_location", settings.ffmpeg_path)
    cookie_path = resolve_authorized_cookie_file("bilibili", settings)
    if cookie_path:
        opts["cookiefile"] = str(cookie_path)
    else:
        browser = browser_cookie_spec("bilibili", settings)
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
    if settings.yt_dlp_proxy:
        opts["proxy"] = settings.yt_dlp_proxy


def load_bilibili_cookie_dict(settings: Settings = SETTINGS) -> dict[str, str]:
    cookie_path = resolve_authorized_cookie_file("bilibili", settings)
    if not cookie_path:
        return {}
    jar = MozillaCookieJar(str(cookie_path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return {}
    return {
        cookie.name: cookie.value
        for cookie in jar
        if "bilibili.com" in cookie.domain
    }


def create_bilibili_session(settings: Settings = SETTINGS, referer: str = "https://www.bilibili.com/"):
    import requests

    session = requests.Session()
    session.headers.update(bilibili_headers(referer))
    session.cookies.update(load_bilibili_cookie_dict(settings))
    if "buvid3" not in session.cookies:
        try:
            session.get("https://www.bilibili.com/", timeout=15)
        except Exception:
            pass
    if referer and referer != "https://www.bilibili.com/":
        try:
            session.get(referer, timeout=15)
        except Exception:
            pass
    return session


def sign_wbi_params(session, params: dict[str, Any], settings: Settings = SETTINGS) -> dict[str, Any]:
    params = dict(params)
    params["wts"] = round(time.time())
    params = {
        key: "".join(char for char in str(value) if char not in "!'()*")
        for key, value in sorted(params.items())
    }
    query = urllib.parse.urlencode(params)
    params["w_rid"] = hashlib.md5(f"{query}{get_wbi_key(session, settings)}".encode()).hexdigest()
    return params


def get_wbi_key(session, settings: Settings = SETTINGS) -> str:
    now = time.time()
    if now < _WBI_KEY_CACHE.get("ts", 0) + 3600 and _WBI_KEY_CACHE.get("key"):
        return str(_WBI_KEY_CACHE["key"])
    response = session.get("https://api.bilibili.com/x/web-interface/nav", timeout=15)
    response.raise_for_status()
    payload = response.json()
    wbi_img = ((payload.get("data") or {}).get("wbi_img")) or {}
    img_key = Path(str(wbi_img.get("img_url", "")).split("?")[0]).stem
    sub_key = Path(str(wbi_img.get("sub_url", "")).split("?")[0]).stem
    lookup = img_key + sub_key
    if len(lookup) < 64:
        raise RuntimeError("Cannot obtain Bilibili WBI key")
    key = "".join(lookup[index] for index in _MIXIN_KEY_ENC_TAB)[:32]
    _WBI_KEY_CACHE.update({"key": key, "ts": now})
    return key


def humanize_bilibili_error(exc: Exception) -> str:
    message = ANSI_ESCAPE_RE.sub("", str(exc)).strip()
    lowered = message.lower()
    if "ffmpeg is not installed" in message or "requested merging of multiple formats" in message:
        return (
            "yt-dlp could not find ffmpeg while merging downloaded video/audio streams. "
            "Set FFMPEG_PATH in .env to a valid ffmpeg executable and restart the Web UI."
        )
    if (
        "geo restriction" in lowered
        or "not available from your location" in lowered
        or "geo-restricted" in lowered
    ):
        return (
            "B站电影/番剧播放接口没有向下载器返回媒体流，并报告了地区或播放限制。"
            "这不代表你的大会员失效：网页或客户端可能使用yt-dlp无法读取的受保护"
            "播放链路。工具不会绕过平台保护；可以改用该作品的官方字幕、普通BV视频，"
            "或导入你有权使用的本地视频文件。"
        )
    if "premium members" in lowered or "premium member" in lowered:
        return (
            "该B站内容需要当前账号具备相应的会员或购买权限。"
            "请确认网页登录使用的是有播放权限的账号，然后重新登录B站。"
        )
    if "412" in message or "Precondition Failed" in message:
        return (
            "B站拒绝了当前请求（HTTP 412）。通常是缺少登录 Cookie、请求太频繁，"
            "或当前网络被风控。建议稍后重试；如果仍失败，请回到网页主界面"
            "点击“重新登录B站”刷新本地会话。"
        )
    if "failed to load cookies" in message or "cookies database" in message:
        return (
            "无法读取浏览器 Cookie。请回到网页主界面点击“重新登录B站”"
            "刷新本地会话。"
        )
    if is_transient_bilibili_error(exc):
        return (
            "B站媒体连接在下载过程中被中断，程序已执行自动重试并保留断点文件。"
            "请稍后重新运行同一任务，下载会从已有 .part 文件继续；如果连续失败，"
            "请在主界面点击“重新登录B站”刷新会话，并检查当前网络或代理设置。"
        )
    return message


def is_transient_bilibili_error(exc: Exception) -> bool:
    message = ANSI_ESCAPE_RE.sub("", str(exc)).lower()
    return any(
        term in message
        for term in (
            "connectionreseterror",
            "connection reset",
            "connection broken",
            "remote end closed",
            "read timed out",
            "timed out",
            "timeout",
            "http error 502",
            "http error 503",
            "http error 504",
            "unable to download video data",
        )
    )

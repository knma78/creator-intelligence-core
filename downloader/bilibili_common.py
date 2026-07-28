from __future__ import annotations

import hashlib
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

_WBI_KEY_CACHE: dict[str, Any] = {}
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
    message = str(exc)
    if "ffmpeg is not installed" in message or "requested merging of multiple formats" in message:
        return (
            "yt-dlp could not find ffmpeg while merging downloaded video/audio streams. "
            "Set FFMPEG_PATH in .env to a valid ffmpeg executable and restart the Web UI."
        )
    if "412" in message or "Precondition Failed" in message:
        return (
            "B站拒绝了当前请求（HTTP 412）。通常是缺少登录 Cookie、请求太频繁，"
            "或当前网络被风控。建议稍后重试；如果仍失败，请导出 B站 cookies.txt 后"
            "配置 BILIBILI_COOKIE_FILE，再重启 Web UI。"
        )
    if "failed to load cookies" in message or "cookies database" in message:
        return (
            "无法读取浏览器 Cookie。请清空 BILIBILI_COOKIES_FROM_BROWSER，"
            "或导出 B站 cookies.txt 后配置 BILIBILI_COOKIE_FILE。"
        )
    return message

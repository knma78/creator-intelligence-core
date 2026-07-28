from __future__ import annotations

import argparse
from time import monotonic, sleep
from typing import Any

from config import SETTINGS, Settings, ensure_directories
from downloader.browser_login import launch_login_context
from downloader.platform_auth import (
    LOGIN_COOKIE_NAMES,
    PLATFORM_DOMAINS,
    PLATFORM_LABELS,
    import_platform_cookies,
    platform_auth_dir,
    write_platform_auth_status,
)


LOGIN_URLS = {
    "bilibili": "https://passport.bilibili.com/login",
    "youtube": "https://www.youtube.com/",
}

COOKIE_URLS = {
    "bilibili": [
        "https://www.bilibili.com/",
        "https://passport.bilibili.com/",
    ],
    "youtube": [
        "https://www.youtube.com/",
        "https://accounts.google.com/",
    ],
}


def capture_platform_login(
    platform: str,
    settings: Settings = SETTINGS,
    timeout_seconds: int = 600,
) -> None:
    platform = str(platform or "").strip().lower()
    if platform not in LOGIN_URLS:
        raise ValueError(f"不支持的平台授权类型：{platform}")
    ensure_directories(settings)
    label = PLATFORM_LABELS[platform]
    write_platform_auth_status(
        platform,
        "running",
        f"请在已打开的窗口中完成{label}登录，程序正在等待登录结果。",
        settings,
        source="web_login",
    )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        write_platform_auth_status(
            platform,
            "failed",
            f"缺少 Playwright，无法打开{label}登录窗口。",
            settings,
            source="web_login",
        )
        raise RuntimeError("Playwright is required for platform login") from exc

    profile_dir = platform_auth_dir(settings) / f"{platform}_browser_profile"
    deadline = monotonic() + max(60, timeout_seconds)
    try:
        with sync_playwright() as playwright:
            context = launch_login_context(playwright, profile_dir)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(
                    LOGIN_URLS[platform],
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
            except Exception:
                pass

            while monotonic() < deadline:
                try:
                    browser_cookies = context.cookies(COOKIE_URLS[platform])
                except Exception:
                    write_platform_auth_status(
                        platform,
                        "failed",
                        f"{label}登录窗口已关闭，尚未取得完整登录信息。",
                        settings,
                        source="web_login",
                    )
                    return

                platform_cookies = _platform_cookie_items(platform, browser_cookies)
                if _has_login_marker(platform, platform_cookies):
                    if platform == "youtube":
                        try:
                            page.goto(
                                "https://www.youtube.com/",
                                wait_until="domcontentloaded",
                                timeout=30_000,
                            )
                            sleep(2)
                            platform_cookies = _platform_cookie_items(
                                platform,
                                context.cookies(COOKIE_URLS[platform]),
                            )
                        except Exception:
                            pass
                    content = serialize_netscape_cookies(platform_cookies)
                    import_platform_cookies(platform, content, settings)
                    write_platform_auth_status(
                        platform,
                        "ready",
                        f"{label}登录成功。现在可以直接提交该平台的视频或频道任务。",
                        settings,
                        source="web_login",
                        cookie_count=len(platform_cookies),
                    )
                    sleep(1)
                    context.close()
                    return
                sleep(2)

            write_platform_auth_status(
                platform,
                "failed",
                f"等待{label}登录超时。请重新点击“登录{label}”再试。",
                settings,
                source="web_login",
            )
            context.close()
    except Exception as exc:
        write_platform_auth_status(
            platform,
            "failed",
            f"无法完成{label}登录：{type(exc).__name__}。",
            settings,
            source="web_login",
        )
        raise


def serialize_netscape_cookies(cookies: list[dict[str, Any]]) -> str:
    lines = ["# Netscape HTTP Cookie File"]
    for cookie in sorted(
        cookies,
        key=lambda item: (
            str(item.get("domain") or ""),
            str(item.get("path") or "/"),
            str(item.get("name") or ""),
        ),
    ):
        domain = str(cookie.get("domain") or "").strip()
        name = str(cookie.get("name") or "").replace("\t", "")
        value = str(cookie.get("value") or "").replace("\t", "").replace("\n", "")
        if not domain or not name:
            continue
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        output_domain = (
            f"#HttpOnly_{domain}"
            if cookie.get("httpOnly")
            else domain
        )
        path = str(cookie.get("path") or "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = cookie.get("expires")
        try:
            expiry = max(0, int(float(expires or 0)))
        except (TypeError, ValueError):
            expiry = 0
        lines.append(
            "\t".join(
                [
                    output_domain,
                    include_subdomains,
                    path,
                    secure,
                    str(expiry),
                    name,
                    value,
                ]
            )
        )
    return "\n".join(lines) + "\n"


def _platform_cookie_items(
    platform: str,
    cookies: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    domains = PLATFORM_DOMAINS[platform]
    return [
        cookie
        for cookie in cookies
        if any(
            expected in str(cookie.get("domain") or "").lower()
            for expected in domains
        )
        and cookie.get("name")
    ]


def _has_login_marker(
    platform: str,
    cookies: list[dict[str, Any]],
) -> bool:
    names = {str(cookie.get("name") or "") for cookie in cookies}
    return bool(LOGIN_COOKIE_NAMES[platform] & names)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a local Bilibili or YouTube login session."
    )
    parser.add_argument("--platform", choices=sorted(LOGIN_URLS), required=True)
    parser.add_argument("--timeout", type=int, default=600)
    arguments = parser.parse_args()
    capture_platform_login(
        arguments.platform,
        timeout_seconds=arguments.timeout,
    )


if __name__ == "__main__":
    main()

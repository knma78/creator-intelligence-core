from __future__ import annotations

from pathlib import Path
from typing import Any


def launch_login_context(playwright: Any, profile_dir: Path):
    profile_dir.mkdir(parents=True, exist_ok=True)
    launch_options = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "locale": "zh-CN",
        "viewport": {"width": 1440, "height": 900},
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        return playwright.chromium.launch_persistent_context(
            channel="chrome",
            **launch_options,
        )
    except Exception:
        chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        if not chrome.is_file():
            raise
        return playwright.chromium.launch_persistent_context(
            executable_path=str(chrome),
            **launch_options,
        )

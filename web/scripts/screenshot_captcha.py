#!/usr/bin/env python3
"""Headless screenshot pipeline for the local Captcha component.

Produces 3 PNGs in web/screenshots/:
  - captcha-initial.png: fresh canvas with random chars + interference
  - captcha-wrong.png:   after submitting a deliberately wrong code
  - captcha-correct.png: after submitting the actual code read from the
                          window.__captchaCode dev hook exposed by Captcha.tsx
"""
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "screenshots"
OUTDIR.mkdir(exist_ok=True)


def main() -> int:
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(4)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            page.goto("http://localhost:5173/register", wait_until="networkidle")
            page.wait_for_selector("canvas", timeout=10000)
            page.wait_for_timeout(400)

            page.screenshot(path=str(OUTDIR / "captcha-initial.png"))
            print("[shot] initial")

            page.fill("input[placeholder*='验证码']", "XXXXX")
            page.click("button:has-text('验证')")
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUTDIR / "captcha-wrong.png"))
            print("[shot] wrong")

            # 刷新拿到稳定的新 code, 然后从 window.__captchaCode 读取
            page.click("button[aria-label='刷新验证码']")
            page.wait_for_timeout(400)
            code = page.evaluate(
                "() => (window).__captchaCode ? (window).__captchaCode() : null"
            )
            if not code:
                print("未捕获到验证码, 跳过正确状态截图", file=sys.stderr)
                return 1
            page.fill("input[placeholder*='验证码']", code)
            page.click("button:has-text('验证')")
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUTDIR / "captcha-correct.png"))
            print(f"[shot] correct (code={code!r})")

            browser.close()
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
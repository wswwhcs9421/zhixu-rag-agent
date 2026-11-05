r"""Optional real-browser smoke test. Uses an isolated real app with NO model mocks.

Run: .venv\Scripts\python.exe -m tests.browser_smoke
Requires: pip install playwright; Microsoft Edge installed on Windows.
"""
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

from rag_agent.app import create_app
from rag_agent.config import ROOT, Settings


def main():
    artifacts = ROOT / "test-results"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rag-ui-") as task_dir:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        app = create_app(Settings(data_dir=Path(task_dir), admin_password="Browser-test-12345"))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Browser test server failed to start")
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="msedge", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}")
                expect(page.locator("#login-view")).to_be_visible()
                page.locator("#username").fill("admin")
                page.locator("#password").fill("Browser-test-12345")
                page.locator(".login-submit").click()
                expect(page.get_by_role("heading", name="知识概览", exact=True)).to_be_visible()
                with page.expect_file_chooser() as chooser:
                    page.locator('[data-action="upload"]').first.click()
                chooser.value.set_files({"name": "policy.md", "mimeType": "text/markdown", "buffer": "# 测试差旅制度\n\n上海住宿上限为500元，报销需要发票。".encode()})
                page.locator('[data-nav="documents"]').click()
                expect(page.locator(".doc-title")).to_have_text("测试差旅制度", timeout=15000)
                expect(page.get_by_text("已解析 · 待向量化", exact=True)).to_be_visible()
                page.locator('[data-action="chunks"]').click()
                expect(page.locator(".chunk-content")).to_contain_text("500元")
                page.locator('[data-action="edit-chunk"]').click()
                page.locator("#chunk-text").fill("上海住宿上限现为600元，报销需要发票。<script>window.BAD=1</script>")
                page.locator('#chunk-form button[type="submit"]').click()
                expect(page.locator(".chunk-content")).to_contain_text("600元")
                assert page.evaluate("window.BAD") is None
                page.locator('[data-action="close-modal"]').click()
                page.locator('[data-nav="users"]').click()
                page.locator('[data-action="new-user"]').click()
                page.locator("#new-username").fill("browser-reader")
                page.locator("#new-password").fill("Browser-reader-12345")
                page.locator('#user-form button[type="submit"]').click()
                expect(page.get_by_text("browser-reader", exact=True)).to_be_visible()
                page.locator('[data-nav="overview"]').click()
                expect(page.get_by_role("heading", name="知识概览", exact=True)).to_be_visible()
                page.screenshot(path=str(artifacts / "overview-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile page overflows horizontally"
                page.screenshot(path=str(artifacts / "overview-mobile.png"), full_page=True)
                reader_context = browser.new_context(viewport={"width": 1280, "height": 900})
                member = reader_context.new_page()
                member.on("pageerror", lambda error: errors.append(str(error)))
                member.goto(f"http://127.0.0.1:{port}")
                member.locator("#username").fill("browser-reader")
                member.locator("#password").fill("Browser-reader-12345")
                member.locator(".login-submit").click()
                expect(member.get_by_role("heading", name="知识概览", exact=True)).to_be_visible()
                expect(member.locator('[data-action="upload"]')).to_have_count(0)
                expect(member.locator('[data-nav="users"]')).to_be_hidden()
                assert member.request.get(f"http://127.0.0.1:{port}/api/users").status == 403
                member.locator('[data-nav="chat"]').click()
                member.locator("#question").fill("上海住宿上限是多少？")
                member.locator("#send-button").click()
                expect(member.locator(".message.error")).to_contain_text("尚未配置 DeepSeek", timeout=15000)
                assert errors == [], errors
                reader_context.close()
                context.close()
                browser.close()
                print("Browser smoke passed: login, upload, parsing, chunk edits, XSS escaping, user creation, read-only UI/API, missing-model errors, desktop/mobile layout.")
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            if thread.is_alive():
                raise RuntimeError("Browser test server did not stop")


if __name__ == "__main__":
    main()

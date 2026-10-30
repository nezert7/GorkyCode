import os
import sys
import threading
import time


def get_base_path() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


from dotenv import load_dotenv
load_dotenv(os.path.join(get_base_path(), ".env"), override=True)

import uvicorn
import webview
import httpx
from main import app

if sys.platform == "darwin":
    try:
        import objc
        from webview.platforms import cocoa

        @objc.typedSelector(b"v@:@@@q@?")
        def webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_(
            self, webview_instance, origin, frame, capture_type, decision_handler
        ):
            decision_handler(1)

        delegate_cls = getattr(cocoa, "UIWebUIDelegate", None) or getattr(
            getattr(cocoa, "BrowserView", None), "UIDelegate", None
        )
        if delegate_cls is not None:
            delegate_cls.webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_ = (
                webView_requestMediaCapturePermissionForOrigin_initiatedByFrame_type_decisionHandler_
            )
    except Exception:
        pass


def run_server():
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")


def wait_for_server(url: str, timeout: int = 15) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            res = httpx.get(f"{url}/docs", timeout=2.0)
            if res.status_code == 200:
                return True
        except httpx.HTTPError:
            time.sleep(0.2)
    return False


def main():
    remote_url = (os.getenv("VORONA_SERVER_URL") or "").strip().rstrip("/")

    if remote_url:
        target_url = remote_url
    else:
        server_url = "http://localhost:8000" if sys.platform == "darwin" else "http://127.0.0.1:8000"
        check_url = "http://127.0.0.1:8000"

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        if not wait_for_server(check_url):
            return

        frontend_index = os.path.join(get_base_path(), "static_frontend", "index.html")
        target_url = server_url if os.path.exists(frontend_index) else f"{server_url}/docs"

    webview.create_window(
        title="Ворона — Голосовой ассистент задач и встреч",
        url=target_url,
        width=1100,
        height=750,
        resizable=True,
        min_size=(800, 600)
    )

    webview.start(debug=False)


if __name__ == "__main__":
    main()

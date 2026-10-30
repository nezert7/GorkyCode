import os
import sys
import threading
import time
import uvicorn
import webview
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

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
            print("[*] WebKit: доступ к микрофону автоматически разрешён.")
    except Exception:
        pass


def run_server():
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="warning")


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
        print(f"[*] Подключение к единому удалённому серверу Вороны: {remote_url}")
        target_url = remote_url
    else:
        server_url = "http://localhost:8000" if sys.platform == "darwin" else "http://127.0.0.1:8000"
        check_url = "http://127.0.0.1:8000"

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        print("[*] Запуск локального сервера FastAPI (порт 8000)...")
        if not wait_for_server(check_url):
            print("[!] Сервер не ответил вовремя. Проверьте порт 8000.")
            return

        frontend_index = os.path.join(os.path.dirname(__file__), "static_frontend", "index.html")
        target_url = server_url if os.path.exists(frontend_index) else f"{server_url}/docs"

    print(f"[*] Открытие окна ({target_url})...")

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

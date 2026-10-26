import os
import threading
import time
import uvicorn
import webview
import requests


def run_server():
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")


def wait_for_server(url: str, timeout: int = 15) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            res = requests.get(f"{url}/docs", timeout=2)
            if res.status_code == 200:
                return True
        except requests.RequestException:
            time.sleep(0.2)
    return False


def main():
    server_url = "http://127.0.0.1:8000"

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    print("[*] Запуск локального сервера FastAPI...")
    if not wait_for_server(server_url):
        print("[!] Сервер не ответил вовремя. Проверьте порт 8000.")
        return

    # Если React-фронтенд еще не собран в static_frontend/index.html,
    # открываем интерактивную панель /docs, чтобы тестировать API в окне
    frontend_index = os.path.join(os.path.dirname(__file__), "static_frontend", "index.html")
    target_url = server_url if os.path.exists(frontend_index) else f"{server_url}/docs"

    print(f"[*] Сервер запущен. Открытие окна ({target_url})...")

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

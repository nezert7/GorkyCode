import threading
import time
import uvicorn
import webview
import requests


def run_server():
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")


def wait_for_server(url: str, timeout: int = 15):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            res = requests.get(f"{url}/docs")
            if res.status_code == 200:
                return True
        except requests.ConnectionError:
            time.sleep(0.2)
    return False


def main():
    server_url = "http://127.0.0.1:8000"

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    print("[*] Запуск локального сервера...")
    wait_for_server(server_url)
    print("[*] Сервер запущен. Открытие окна...")

    webview.create_window(
        title="Голосовой ассистент задач и встреч",
        url=server_url,
        width=1100,
        height=750,
        resizable=True,
        min_size=(800, 600)
    )

    webview.start(debug=False)


if __name__ == "__main__":
    main()

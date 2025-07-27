import os
import requests
import json
from flask import Flask
from app.routes import main
from app.scheduler import start_scheduler

def fetch_default_config():
    config_path = '/config/config.json'
    if not os.path.exists(config_path):
        print("[Artillery] Config not found. Downloading default config...")

        try:
            url = "https://raw.githubusercontent.com/mikf/gallery-dl/master/docs/gallery-dl.conf"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                raw_text = response.text

                try:
                    config_data = json.loads(raw_text)
                    config_data["base-directory"] = "/downloads"
                    config_data.setdefault("extractor", {})["base-directory"] = "/downloads"

                    with open(config_path, 'w', encoding='utf-8') as f:
                        json.dump(config_data, f, indent=4)

                    print("[Artillery] Default config downloaded and patched.")
                except json.JSONDecodeError:
                    print("[Artillery] Error parsing JSON. Saving raw file as-is.")
                    with open(config_path, 'w', encoding='utf-8') as f:
                        f.write(raw_text)
            else:
                print(f"[Artillery] Failed to fetch config: HTTP {response.status_code}")
        except Exception as e:
            print(f"[Artillery] Exception while downloading config: {e}")

from flask import Flask
from app.routes import main  # or whatever your blueprint is

def create_app():
    app = Flask(__name__)
    app.secret_key = "something_secure"

    app.register_blueprint(main)

    # ❌ Do NOT start scheduler or load tasks here anymore

    return app

"""
Development server (with Socket.IO). Production runs gunicorn; see gunicorn.conf.py.

Settings come from the environment, or a local .env file in development:
PORT (default 5000), HOST (default 127.0.0.1), FLASK_ENV (default development).
"""

import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app  # noqa: E402  (after .env is loaded)
from sockets import socketio  # noqa: E402

if __name__ == "__main__":
    app = create_app(os.getenv("FLASK_ENV", "development"))
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    print(f"Ruff dev server on http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=app.config.get("DEBUG", False))

"""
Entry point for running the Ruff application.

Load environment variables and start the Flask development server.
"""

import os
import socket
from dotenv import load_dotenv
from app import create_app


def find_free_port(start_port=5000, max_attempts=10):
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.close()
            return port
        except OSError:
            continue
    return start_port  # Return default if all ports busy


if __name__ == "__main__":
    # Load environment variables from .env file
    load_dotenv()
    
    # Create application
    app = create_app(os.getenv("FLASK_ENV", "development"))
    
    # Find available port
    port = find_free_port(5000)
    
    # Run the application
    print(f"Starting Ruff app on http://127.0.0.1:{port}")
    app.run(
        host="127.0.0.1",
        port=port,
        debug=app.config.get("DEBUG", False),
    )

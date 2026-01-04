"""
Ruff - A Flask-based text stashing application.

A simple and elegant way to save, organize, and manage text snippets.
"""

import json
import logging
import logging.handlers
import os
import uuid
from flask import Flask, render_template, g, request, has_request_context

from config import get_config
from routes import bp, csrf
from models import db


def create_app(config_name: str = None) -> Flask:
    """
    Application factory function.

    Args:
        config_name: Configuration name (development, production, testing)
        
    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)
    
    # Load configuration
    config = get_config(config_name)
    app.config.from_object(config)
    
    # Initialize database
    db.init_app(app)
    
    # Initialize CSRF protection
    csrf.init_app(app)
    
    # Register blueprints
    app.register_blueprint(bp)
    
    # Request ID + structured logging context
    @app.before_request
    def add_request_id():
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_id = req_id
        # Attach to WSGI environ for access logs if desired
        request.environ["request_id"] = req_id

    @app.after_request
    def inject_request_id(response):
        if hasattr(g, "request_id"):
            response.headers["X-Request-ID"] = g.request_id
        return response
    
    # Setup logging
    setup_logging(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # NOTE: schema creation is handled via migrations (Alembic) and should not
    # run automatically on startup to avoid production drift. Ensure migrations
    # are applied as part of your deploy pipeline.
    logger = logging.getLogger(__name__)
    logger.info("Application initialized (migrations must be applied separately)")
    
    return app


def setup_logging(app: Flask) -> None:
    """
    Configure logging for the application.

    Args:
        app: Flask application instance
    """
    logger = logging.getLogger(__name__)
    
    # Create logs directory if it doesn't exist
    logs_dir = os.path.join(os.path.dirname(__file__), "logs")
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    
    # File handler for all logs
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(logs_dir, "ruff.log"),
        maxBytes=10485760,  # 10MB
        backupCount=10,
    )
    file_handler.setLevel(logging.INFO)
    
    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
    
    # Create formatter
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            payload = {
                "ts": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "request_id": getattr(record, "request_id", "-"),
                "message": record.getMessage(),
            }
            return json.dumps(payload)

    formatter = JsonFormatter()
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.DEBUG if app.debug else logging.INFO)
    
    # Inject request_id into log records
    class RequestIdFilter(logging.Filter):
        def filter(self, record):
            if has_request_context():
                record.request_id = getattr(g, "request_id", "-")
            else:
                record.request_id = "-"
            return True
    req_filter = RequestIdFilter()
    file_handler.addFilter(req_filter)
    console_handler.addFilter(req_filter)


def register_error_handlers(app: Flask) -> None:
    """
    Register custom error handlers.

    Args:
        app: Flask application instance
    """
    logger = logging.getLogger(__name__)

    @app.errorhandler(404)
    def not_found_error(error):
        """Handle 404 errors."""
        logger.warning(f"404 error: {error}")
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        logger.error(f"500 error: {error}")
        return render_template("errors/500.html"), 500

    @app.errorhandler(400)
    def bad_request_error(error):
        """Handle 400 errors."""
        logger.warning(f"400 error: {error}")
        return render_template("errors/400.html"), 400


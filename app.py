"""
Ruff - A Flask-based text stashing application.

A simple and elegant way to save, organize, and manage text snippets.
"""

import logging
import logging.handlers
import os
from flask import Flask, render_template

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
    
    # Setup logging
    setup_logging(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Create database tables
    try:
        with app.app_context():
            db.create_all()
            logger = logging.getLogger(__name__)
            logger.info("Application initialized")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to initialize application: {e}")
        raise
    
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
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.setLevel(logging.DEBUG if app.debug else logging.INFO)


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


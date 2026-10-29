"""
Configuration module for the Ruff application.

Loads configuration from environment variables with sensible defaults.
"""

import os
from datetime import timedelta

def database_url(default: str = "sqlite:///./ruff.db") -> str:
    """
    DATABASE_URL, normalised for SQLAlchemy: hosts such as Heroku and Render
    hand out postgres:// URLs; SQLAlchemy needs postgresql+psycopg://.
    """
    url = os.getenv("DATABASE_URL") or default
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


# Placeholder secrets for local development only; app.py refuses to start
# outside development/testing while either is still in use.
DEV_SECRET_KEY = "dev-secret-key-change-in-production"
DEV_PASSWORD_SALT = "dev-salt-change-in-production"
INSECURE_DEFAULTS = {DEV_SECRET_KEY, DEV_PASSWORD_SALT}


class Config:
    """Base configuration class."""

    # Product name shown in the UI (one place to change for a rename)
    APP_NAME = os.getenv("APP_NAME", "Ruff")

    # Flask Settings
    SECRET_KEY = os.getenv("SECRET_KEY", DEV_SECRET_KEY)
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", DEV_PASSWORD_SALT)
    DEBUG = os.getenv("FLASK_ENV", "production") == "development"
    
    # Session Settings
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"

    # Auth Tokens
    EMAIL_VERIFY_TOKEN_EXP = int(os.getenv("EMAIL_VERIFY_TOKEN_EXP", "86400"))  # 24h
    PASSWORD_RESET_TOKEN_EXP = int(os.getenv("PASSWORD_RESET_TOKEN_EXP", "3600"))  # 1h
    REQUIRE_EMAIL_VERIFICATION = os.getenv("REQUIRE_EMAIL_VERIFICATION", "1") == "1"

    # SMTP Email
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "0") == "1"
    
    # Database Settings
    # IV Backing services: the database is an attached resource named by URL
    SQLALCHEMY_DATABASE_URI = database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Rate Limiting
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per day;50 per hour")
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    
    # Reverse proxy hops that set X-Forwarded-* (0 = trust no proxy headers)
    PROXY_FIX_COUNT = int(os.getenv("PROXY_FIX_COUNT", "0"))

    # Maximum request body size (uploads/imports); larger requests get 413
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024)))

    # Socket.IO: extra allowed origins (comma-separated); empty = same origin only
    # Socket.IO across several processes/containers: a shared message queue
    # (e.g. redis://redis:6379/1). Empty = single process.
    SOCKETIO_MESSAGE_QUEUE = os.getenv("SOCKETIO_MESSAGE_QUEUE") or None

    SOCKETIO_CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv("SOCKETIO_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]

    # Recess Relay sessions (and their entries) are deleted after this many days
    RELAY_RETENTION_DAYS = int(os.getenv("RELAY_RETENTION_DAYS", "30"))

    # Stash Settings
    MAX_STASH_LENGTH = 50000  # Maximum characters per stash
    PREVIEW_LENGTH = 100  # Characters to show in preview
    
    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # No time limit for CSRF tokens


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    # HTTPS-only session cookie unless explicitly disabled (SESSION_COOKIE_SECURE=0)
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1") == "1"


class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    # Use in-memory DB so tests never touch the real data file
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


def get_config(env: str = None) -> Config:
    """
    Get configuration based on environment.

    Args:
        env: Environment name (development, production, testing)
        
    Returns:
        Configuration object for the specified environment
    """
    if env is None:
        env = os.getenv("FLASK_ENV", "production")
    
    config_map = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }
    
    return config_map.get(env, ProductionConfig)()

"""
Configuration module for the Ruff application.

Loads configuration from environment variables with sensible defaults.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration class."""

    # Flask Settings
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "dev-salt-change-in-production")
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
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///./ruff.db"  # Store in project root
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Rate Limiting
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per day;50 per hour")
    RATELIMIT_STORAGE_URL = os.getenv("RATELIMIT_STORAGE_URL", "memory://")
    
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

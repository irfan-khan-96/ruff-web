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
    DEBUG = os.getenv("FLASK_ENV", "production") == "development"
    
    # Session Settings
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = True
    
    # Database Settings
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///./ruff.db"  # Store in project root
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Stash Settings
    MAX_STASH_LENGTH = 50000  # Maximum characters per stash
    PREVIEW_LENGTH = 50  # Characters to show in preview
    
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

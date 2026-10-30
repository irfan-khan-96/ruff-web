"""
Ruff - A Flask-based text stashing application.

A simple and elegant way to save, organize, and manage text snippets.
"""

import functools
import hashlib
import json
import logging
import os
import secrets
import sys
import uuid
from flask import Flask, render_template, g, request, has_request_context
from flask_compress import Compress
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config, INSECURE_DEFAULTS
from routes import bp, csrf, limiter
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

    # Refuse to run outside dev/testing with the publicly known default secrets:
    # anyone could forge sessions (log in as any user) or reset/verify tokens.
    if not (app.config.get("DEBUG") or app.config.get("TESTING")):
        insecure = [
            key for key in ("SECRET_KEY", "SECURITY_PASSWORD_SALT")
            if app.config.get(key) in INSECURE_DEFAULTS
            or len(app.config.get(key) or "") < MIN_SECRET_LENGTH
        ]
        if insecure:
            raise RuntimeError(
                f"{', '.join(insecure)} must be set to a random value of at least "
                f"{MIN_SECRET_LENGTH} characters in production."
            )

    init_error_reporting(app)

    # Behind a reverse proxy, take the client IP/scheme from X-Forwarded-*
    # so rate limits apply per client rather than to the proxy's address
    proxy_count = app.config.get("PROXY_FIX_COUNT", 0)
    if proxy_count > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=proxy_count,
            x_proto=proxy_count,
            x_host=proxy_count,
        )

    # Initialize database
    db.init_app(app)
    
    # gzip/brotli for HTML, CSS, JS and JSON responses
    Compress(app)

    # Static files: cached for a year, with ?v=<content hash> in every URL so
    # a changed file gets a new URL (repeat visits make no static requests)
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 365 * 24 * 3600

    @app.url_defaults
    def version_static_urls(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            values["v"] = static_file_version(app.static_folder, values["filename"])

    # Initialize CSRF protection
    csrf.init_app(app)

    # Initialize rate limiter
    limiter.init_app(app)
    
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

    @app.cli.command("purge-relays")
    def purge_relays_command():
        """Delete expired Recess Relay sessions (run from cron)."""
        from models import RelaySession
        days = app.config["RELAY_RETENTION_DAYS"]
        count = RelaySession.purge_expired(days)
        print(f"Deleted {count} relay session(s) older than {days} days.")

    @app.cli.command("purge-expired")
    def purge_expired_command():
        """Delete expired relays and unopened folded notes (run from cron)."""
        from models import FoldedNote, RelaySession
        relays = RelaySession.purge_expired(app.config["RELAY_RETENTION_DAYS"])
        notes = FoldedNote.purge_expired()
        print(f"Deleted {relays} expired relay session(s) and {notes} expired folded note(s).")

    # Security headers ---------------------------------------------------------
    @app.context_processor
    def inject_template_globals():
        """csp_nonce() for inline <script>s, and the product name."""
        return {"csp_nonce": get_csp_nonce, "app_name": app.config["APP_NAME"]}

    @app.after_request
    def set_security_headers(response):
        response.headers["Content-Security-Policy"] = build_csp(get_csp_nonce())
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config.get("SESSION_COOKIE_SECURE"):
            # Only when served over HTTPS (secure cookies imply it)
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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


MIN_SECRET_LENGTH = 32


@functools.lru_cache(maxsize=None)
def static_file_version(static_folder: str, filename: str) -> str:
    """Short content hash of a static file, for cache-busting URLs."""
    try:
        with open(os.path.join(static_folder, filename), "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()[:10]
    except OSError:
        return "0"


def init_error_reporting(app: Flask) -> None:
    """Send unhandled errors to Sentry when SENTRY_DSN is set (alerting)."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn or app.config.get("TESTING"):
        return
    import sentry_sdk
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("FLASK_ENV", "production"),
        send_default_pii=False,  # no IPs, cookies or user details
        traces_sample_rate=0.0,
    )


def get_csp_nonce() -> str:
    """Per-request random nonce for inline scripts allowed by the CSP."""
    # Stored on the request (not g, which lives as long as the app context)
    return request.environ.setdefault("ruff.csp_nonce", secrets.token_urlsafe(16))


def build_csp(nonce: str) -> str:
    """
    Content-Security-Policy for every response.

    Scripts: own origin only (everything is self-hosted), plus inline scripts
    carrying this request's nonce. Inline styles stay allowed because
    templates use <style> blocks and style attributes throughout.
    """
    return "; ".join([
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self'",  # fonts are self-hosted
        "img-src 'self' data:",
        "connect-src 'self'",  # sync and fold API calls
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


def setup_logging(app: Flask) -> None:
    """
    Log to stdout only, as an event stream (twelve-factor XI): the platform
    (Docker, Heroku, systemd, ...) collects and routes it. Nothing is written
    to disk, so the app also runs on a read-only filesystem.

    LOG_FORMAT: "json" (one JSON object per line; default outside debug) or
    "console" (readable lines; default in debug). LOG_LEVEL: DEBUG, INFO, ...
    """
    root_logger = logging.getLogger()
    if any(getattr(handler, "ruff_handler", False) for handler in root_logger.handlers):
        return

    log_format = os.getenv("LOG_FORMAT", "console" if app.debug else "json").lower()
    log_level = os.getenv("LOG_LEVEL", "DEBUG" if app.debug else "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.ruff_handler = True

    # Create formatters
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            payload = {
                "ts": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "request_id": getattr(record, "request_id", "-"),
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    class ConsoleFormatter(logging.Formatter):
        def format(self, record):
            base = (
                f"{self.formatTime(record, self.datefmt)} | "
                f"{record.levelname:<7} | {record.name} | "
                f"{getattr(record, 'request_id', '-')}"
                f" | {record.getMessage()}"
            )
            if record.exc_info:
                base += "\n" + self.formatException(record.exc_info)
            return base

    handler.setFormatter(JsonFormatter() if log_format == "json" else ConsoleFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Inject request_id into log records
    class RequestIdFilter(logging.Filter):
        def filter(self, record):
            if has_request_context():
                record.request_id = getattr(g, "request_id", "-")
            else:
                record.request_id = "-"
            return True
    handler.addFilter(RequestIdFilter())


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

    @app.errorhandler(429)
    def rate_limited_error(error):
        """Log rate-limit hits as security events (brute force, scraping)."""
        logging.getLogger("ruff.security").warning(
            "Rate limit hit: %s %s from %s (%s)",
            request.method, request.path, request.remote_addr, error.description,
        )
        if request.is_json:
            return {"error": "Too many requests"}, 429
        return render_template(
            "errors/400.html",
            message="Too many attempts. Please wait a minute and try again.",
        ), 429

    @app.errorhandler(413)
    def payload_too_large_error(error):
        """Handle request bodies over MAX_CONTENT_LENGTH."""
        logger.warning(f"413 error: {error}")
        if request.is_json:
            return {"error": "Request too large"}, 413
        return render_template(
            "errors/400.html",
            message="That file or request is too large to upload.",
        ), 413

# Ruff - Text Stashing Application

A simple, elegant Flask-based application for saving, organizing, and managing text snippets.

## Features

- 💾 **Quick Stash**: Save text snippets instantly
- 📝 **Edit & Update**: Modify your stashes anytime
- 🗂️ **Organize**: View all your stashes in one place
- 🌙 **Dark/Light Theme**: Toggle between themes
- 🛡️ **CSRF Protection**: Secure form handling
- 📱 **Responsive Design**: Works on all devices

## Project Structure

```
ruff-web/
├── app.py              # Application factory and initialization
├── config.py           # Configuration management
├── forms.py            # WTForms definitions
├── routes.py           # Route handlers and blueprints
├── utils.py            # Helper functions and utilities
├── run.py              # Entry point to start the server
├── requirements.txt    # Python dependencies
├── .env                # Environment variables (local)
├── .env.example        # Environment variables template
├── .gitignore          # Git ignore rules
├── static/             # CSS, JavaScript, images
│   ├── styles.css
│   └── script.js
├── templates/          # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── stashes.html
│   ├── viewstash.html
│   ├── editstash.html
│   └── errors/         # Error pages
│       ├── 400.html
│       ├── 404.html
│       └── 500.html
└── logs/               # Application logs (created at runtime)
```

## Getting Started

### Prerequisites

- Python 3.8+
- pip or conda

### Installation

1. **Clone the repository**
   ```bash
   cd ruff-web
   ```

2. **Create a virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and set SECRET_KEY to a secure value (optional for development)
   ```

5. **Run the application**
   ```bash
   python run.py
   ```

6. **Access the app**
   - Open your browser to `http://localhost:5000`

### Generate a Secure Secret Key

For production, generate a secure secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Add it to your `.env` file:
```
SECRET_KEY=your-generated-key-here
```

## Configuration

The application uses environment-based configuration. See `config.py` for available settings:

- `FLASK_ENV`: Environment mode (development, production, testing)
- `SECRET_KEY`: Secret key for session encryption
- `DEBUG`: Enable/disable debug mode
- `MAX_STASH_LENGTH`: Maximum characters per stash (default: 50,000)
- `PREVIEW_LENGTH`: Characters to show in preview (default: 50)

## Architecture

### Modern Development Practices

- **Separation of Concerns**: Routes, forms, configuration, and utilities are separated into modules
- **Application Factory Pattern**: `create_app()` function for flexible app instantiation
- **Configuration Management**: Environment-based config with sensible defaults
- **Logging**: Rotating file logs with console output
- **Error Handling**: Custom error handlers for 400, 404, and 500 errors
- **Type Hints**: Functions include type annotations for better IDE support
- **Documentation**: Docstrings for all functions and modules

### Security Features

- **CSRF Protection**: All forms are protected with CSRF tokens
- **Input Validation**: WTForms validators ensure data integrity
- **Session Security**: Secure session handling with Flask

## Production Readiness Checklist

Before deploying to production, ensure the following are complete:

- **Secrets**: Set `SECRET_KEY` to a strong random value (no defaults).
- **Database**: Set `DATABASE_URL` to a managed database (PostgreSQL recommended).
- **Migrations**: Run Alembic migrations as part of deploy (schema is not auto-created).
- **Debug**: Ensure debug is disabled (`FLASK_ENV=production`).
- **App Server**: Use Gunicorn (see [Procfile](Procfile) and [Dockerfile](Dockerfile)).
- **AuthZ**: Mutating routes require login and enforce ownership checks.
- **Logging**: Collect `logs/ruff.log` (or stdout in container deployments).
- **Health Checks**: Configure `/healthz` and `/readyz` in your load balancer.
- **Environment Secrets**: Sensitive configuration via environment variables

## Development

### Running in Development Mode

```bash
export FLASK_ENV=development
python run.py
```

The app will run with debug mode enabled and auto-reload on file changes.

### Checking Logs

Logs are stored in the `logs/` directory:

```bash
tail -f logs/ruff.log
```

### Testing

Set up test configuration in `.env`:

```
FLASK_ENV=testing
```

## Future Enhancements

- 🏷️ Tags and collections for organizing stashes
- 🔍 Full-text search functionality
- 👤 User authentication and accounts
- 💾 Database persistence (SQLite/PostgreSQL)
- 📤 Export stashes as PDF, Markdown, or JSON
- 🎨 Custom theme editor
- 🔒 Password-protected stashes
- 📱 Mobile app (React Native)

## Contributing

Contributions are welcome! Please follow PEP 8 style guidelines and include:

- Type hints
- Docstrings
- Unit tests for new features

## License

MIT License - feel free to use this project for personal or commercial purposes.

## Support

For issues or questions, please open an issue on the repository.

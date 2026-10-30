"""
Flask-WTF forms. Sign-in is passwordless: just an email address.
"""

import re

from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Email, Length, ValidationError

from models import User

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class EmailForm(FlaskForm):
    """Sign in, or sign up: we email a link either way."""

    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Type your email address."),
            Email(message="That doesn't look like an email address."),
            Length(max=120),
        ],
    )


class NameForm(FlaskForm):
    """The name shown on relay lines and in the Lounge."""

    username = StringField(
        "Your name",
        validators=[
            DataRequired(message="Pick a name."),
            Length(min=3, max=30, message="Between 3 and 30 characters."),
        ],
    )

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user

    def validate_username(self, field):
        if not NAME_RE.match(field.data or ""):
            raise ValidationError("Letters, numbers, dots, dashes and underscores only.")
        taken = User.query.filter(User.username == field.data).first()
        if taken and taken is not self.current_user:
            raise ValidationError("That name's taken.")

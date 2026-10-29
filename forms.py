"""
Flask-WTF forms for the Ruff application.
"""

from flask_wtf import FlaskForm
from wtforms import SubmitField, StringField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, ValidationError, Email, EqualTo
from models import User

# Password policy for new passwords (sign-up and reset)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_LENGTH_MESSAGE = (
    f"Password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters."
)


class LoginForm(FlaskForm):
    """Form for user login."""

    username = StringField(
        "Username",
        validators=[DataRequired(message="Username is required.")]
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password is required."),
            # No minimum here (older accounts may predate the policy), only the cap
            Length(max=PASSWORD_MAX_LENGTH, message=PASSWORD_LENGTH_MESSAGE),
        ]
    )
    remember = BooleanField("Remember me")
    submit = SubmitField("Login")


class SignupForm(FlaskForm):
    """Form for user registration."""

    username = StringField(
        "Username",
        validators=[
            DataRequired(message="Username is required."),
            Length(min=3, max=80, message="Username must be between 3 and 80 characters.")
        ]
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Invalid email address.")
        ]
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password is required."),
            Length(min=PASSWORD_MIN_LENGTH, max=PASSWORD_MAX_LENGTH, message=PASSWORD_LENGTH_MESSAGE)
        ]
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(message="Please confirm your password."),
            EqualTo("password", message="Passwords must match.")
        ]
    )
    submit = SubmitField("Sign Up")
    
    def validate_username(self, field):
        """Check if username is already taken."""
        if User.query.filter_by(username=field.data).first():
            raise ValidationError("Username already exists.")
    
    # No "email already registered" validator: it would reveal who has an
    # account. The signup route handles existing emails without saying so.


class ResendVerificationForm(FlaskForm):
    """Form to resend email verification."""

    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Invalid email address.")
        ]
    )
    submit = SubmitField("Resend Verification Email")


class ForgotPasswordForm(FlaskForm):
    """Form to request a password reset."""

    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="Invalid email address.")
        ]
    )
    submit = SubmitField("Send Reset Link")


class ResetPasswordForm(FlaskForm):
    """Form to reset password."""

    password = PasswordField(
        "New Password",
        validators=[
            DataRequired(message="Password is required."),
            Length(min=PASSWORD_MIN_LENGTH, max=PASSWORD_MAX_LENGTH, message=PASSWORD_LENGTH_MESSAGE)
        ]
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(message="Please confirm your password."),
            EqualTo("password", message="Passwords must match.")
        ]
    )
    submit = SubmitField("Reset Password")

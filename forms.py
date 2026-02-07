"""
Flask-WTF forms for the Ruff application.
"""

from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, StringField, SelectField, PasswordField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, ValidationError, Email, EqualTo
from config import get_config
from models import User
from sqlalchemy import func

config = get_config()


class StashForm(FlaskForm):
    """Form for creating a new stash."""

    title = StringField(
        "Title",
        validators=[
            Optional(),
            Length(max=200, message="Title must be 200 characters or less."),
        ],
        render_kw={"placeholder": "Give it a title (optional)"}
    )
    body = TextAreaField(
        "Body",
        validators=[
            DataRequired(message="Please enter some content."),
            Length(
                min=1,
                max=config.MAX_STASH_LENGTH,
                message=f"Body must be between 1 and {config.MAX_STASH_LENGTH} characters.",
            ),
        ],
    )
    checklist = HiddenField()
    collection = SelectField("Collection", coerce=int, validators=[Optional()])
    tags = StringField(
        "Tags",
        validators=[Optional()],
        render_kw={"placeholder": "Add tags separated by commas (e.g., python, web, tutorial)"}
    )
    submit = SubmitField("Stash It")


class EditStashForm(FlaskForm):
    """Form for editing an existing stash."""

    title = StringField(
        "Title",
        validators=[
            Optional(),
            Length(max=200, message="Title must be 200 characters or less."),
        ],
        render_kw={"placeholder": "Give it a title (optional)"}
    )
    body = TextAreaField(
        "Body",
        validators=[
            DataRequired(message="Please enter some content."),
            Length(
                min=1,
                max=config.MAX_STASH_LENGTH,
                message=f"Body must be between 1 and {config.MAX_STASH_LENGTH} characters.",
            ),
        ],
    )
    checklist = HiddenField()
    collection = SelectField("Collection", coerce=int, validators=[Optional()])
    tags = StringField(
        "Tags",
        validators=[Optional()],
        render_kw={"placeholder": "Add tags separated by commas (e.g., python, web, tutorial)"}
    )
    submit = SubmitField("Update Stash")


class CollectionForm(FlaskForm):
    """Form for creating and editing collections."""
    
    name = StringField(
        "Collection Name",
        validators=[
            DataRequired(message="Please enter a collection name."),
            Length(min=1, max=100, message="Collection name must be between 1 and 100 characters.")
        ]
    )
    description = TextAreaField(
        "Description",
        validators=[Optional(), Length(max=500)],
        render_kw={"rows": 3, "placeholder": "Optional description"}
    )
    submit = SubmitField("Create Collection")


class LoginForm(FlaskForm):
    """Form for user login."""

    username = StringField(
        "Username",
        validators=[DataRequired(message="Username is required.")]
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password is required.")]
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
            Length(min=6, message="Password must be at least 6 characters.")
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
    
    def validate_email(self, field):
        """Check if email is already registered."""
        email = field.data.strip().lower()
        if User.query.filter(func.lower(User.email) == email).first():
            raise ValidationError("Email already registered.")


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
            Length(min=6, message="Password must be at least 6 characters.")
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

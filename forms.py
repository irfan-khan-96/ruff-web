"""
Flask-WTF forms for the Ruff application.
"""

from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, StringField, SelectField, PasswordField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, ValidationError, Email, EqualTo
from config import get_config
from models import User

config = get_config()

# Password policy for new passwords (sign-up and reset)
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_LENGTH_MESSAGE = (
    f"Password must be between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters."
)


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

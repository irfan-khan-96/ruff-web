"""
Flask-WTF forms for the Ruff application.
"""

from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField, StringField, SelectField, SelectMultipleField, PasswordField
from wtforms.validators import DataRequired, Length, Optional, ValidationError, Email, EqualTo
from config import get_config
from models import User

config = get_config()


class StashForm(FlaskForm):
    """Form for creating a new stash."""

    text = TextAreaField(
        "Your Text",
        validators=[
            DataRequired(message="Please enter some text."),
            Length(
                min=1,
                max=config.MAX_STASH_LENGTH,
                message=f"Text must be between 1 and {config.MAX_STASH_LENGTH} characters.",
            ),
        ],
    )
    collection = SelectField("Collection", coerce=int, validators=[Optional()])
    tags = StringField(
        "Tags",
        validators=[Optional()],
        render_kw={"placeholder": "Add tags separated by commas (e.g., python, web, tutorial)"}
    )
    submit = SubmitField("Save")


class EditStashForm(FlaskForm):
    """Form for editing an existing stash."""

    text = TextAreaField(
        "Edit Text",
        validators=[
            DataRequired(message="Please enter some text."),
            Length(
                min=1,
                max=config.MAX_STASH_LENGTH,
                message=f"Text must be between 1 and {config.MAX_STASH_LENGTH} characters.",
            ),
        ],
    )
    collection = SelectField("Collection", coerce=int, validators=[Optional()])
    tags = StringField(
        "Tags",
        validators=[Optional()],
        render_kw={"placeholder": "Add tags separated by commas (e.g., python, web, tutorial)"}
    )
    submit = SubmitField("Update")


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


class SearchForm(FlaskForm):
    """Form for searching stashes."""
    
    query = StringField(
        "Search",
        validators=[Optional()],
        render_kw={"placeholder": "Search stashes..."}
    )
    collection = SelectField("Collection", coerce=int, validators=[Optional()])
    tag = SelectField("Tag", coerce=int, validators=[Optional()])
    submit = SubmitField("Search")


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
        if User.query.filter_by(email=field.data).first():
            raise ValidationError("Email already registered.")

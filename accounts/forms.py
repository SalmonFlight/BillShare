from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()

AUTH_INPUT_CLASSES = (
    "w-full bg-transparent border-0 border-b border-gray-200 "
    "py-3 text-base text-gray-900 placeholder-gray-400 "
    "focus:border-indigo-500 focus:ring-0 focus:outline-none "
    "transition-colors"
)


class SignupForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
        widgets = {
            "username": forms.TextInput(
                attrs={
                    "class": AUTH_INPUT_CLASSES,
                    "placeholder": "Your name",
                    "autocomplete": "username",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": AUTH_INPUT_CLASSES,
                    "placeholder": "you@example.com",
                    "autocomplete": "email",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update({
            "class": AUTH_INPUT_CLASSES,
            "placeholder": "Password",
            "autocomplete": "new-password",
        })
        self.fields["password2"].widget.attrs.update({
            "class": AUTH_INPUT_CLASSES,
            "placeholder": "Re-type password",
            "autocomplete": "new-password",
        })


class StyledLoginForm(AuthenticationForm):
    """Same underline-style inputs as SignupForm, applied to login."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({
            "class": AUTH_INPUT_CLASSES,
            "placeholder": "Your username",
            "autocomplete": "username",
        })
        self.fields["password"].widget.attrs.update({
            "class": AUTH_INPUT_CLASSES,
            "placeholder": "Password",
            "autocomplete": "current-password",
        })
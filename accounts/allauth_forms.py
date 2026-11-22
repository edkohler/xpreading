from allauth.account.forms import LoginForm


class XPLoginForm(LoginForm):
    """allauth login form with kid-friendly labels (the template adds its own
    "Forgot password?" link next to "Remember me")."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        login = self.fields["login"]
        login.label = "Username or email"
        login.widget.attrs.update({"placeholder": "", "autocomplete": "username", "autofocus": True})
        password = self.fields["password"]
        password.help_text = ""
        password.widget.attrs.update({"placeholder": ""})

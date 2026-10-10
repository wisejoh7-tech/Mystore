from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import User


class RegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    phone = forms.CharField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "phone", "password"]

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            self.add_error("confirm_password", "Passwords do not match")
        return cleaned_data


class ProfileUpdateForm(forms.ModelForm):
    new_password = forms.CharField(widget=forms.PasswordInput, required=False, label="New Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, required=False, label="Confirm Password")

    class Meta:
        model = User
        fields = ["username", "email", "phone"]

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")
        if password or confirm_password:
            if password != confirm_password:
                self.add_error("confirm_password", "Passwords do not match")
        return cleaned_data


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'placeholder': 'Enter your username'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Enter your password'}))


class PhoneLoginForm(forms.Form):
    phone = forms.CharField(required=True, label="Phone Number")


class ContactForm(forms.Form):
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'placeholder': 'Your Name'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'placeholder': 'Your Email'}))
    subject = forms.CharField(max_length=200, widget=forms.TextInput(attrs={'placeholder': 'Subject'}))
    message = forms.CharField(widget=forms.Textarea(attrs={'placeholder': 'How can we help you?', 'rows': 5}))

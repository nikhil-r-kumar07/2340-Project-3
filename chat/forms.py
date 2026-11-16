from pathlib import Path

from django import forms
from django.contrib.auth.forms import AuthenticationForm

PREPROCESSING_BOOLEAN_FIELDS = (
    "normalize_unicode",
    "remove_repeated_lines",
    "skip_contents_index",
    "filter_html_boilerplate",
    "deduplicate_chunks",
)


class DeveloperAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError(
                "This account does not have developer access.",
                code="not_developer",
            )


def validate_source_file(upload):
    if Path(upload.name).suffix.lower() not in {".pdf", ".txt"}:
        raise forms.ValidationError("Choose a PDF or TXT file.")


class PreprocessingForm(forms.Form):
    normalize_unicode = forms.BooleanField(
        required=False,
        initial=True,
        label="Normalize Unicode characters",
    )
    remove_repeated_lines = forms.BooleanField(
        required=False,
        initial=True,
        label="Remove repeated headers, footers, and page numbers",
    )
    skip_contents_index = forms.BooleanField(
        required=False,
        initial=True,
        label="Skip contents/index pages and dot-leader lines",
    )
    filter_html_boilerplate = forms.BooleanField(
        required=False,
        initial=True,
        label="Remove navigation and other HTML boilerplate",
    )
    deduplicate_chunks = forms.BooleanField(
        required=False,
        initial=True,
        label="Remove duplicate chunks",
    )
    minimum_chunk_length = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=5000,
        initial=80,
        label="Minimum chunk length (characters)",
    )


class LocalSourceForm(PreprocessingForm):
    title = forms.CharField(max_length=200)
    file = forms.FileField(validators=[validate_source_file])


class UrlSourceForm(PreprocessingForm):
    title = forms.CharField(max_length=200)
    url = forms.URLField()


class UpdateSourceForm(PreprocessingForm):
    title = forms.CharField(max_length=200, required=False)
    url = forms.URLField(required=False)
    file = forms.FileField(required=False, validators=[validate_source_file])

    def clean(self):
        cleaned_data = super().clean()
        has_cleaning_update = any(
            field in self.data
            for field in (*PREPROCESSING_BOOLEAN_FIELDS, "minimum_chunk_length")
        )
        if (
            not any(cleaned_data.get(field) for field in ("title", "url", "file"))
            and not has_cleaning_update
        ):
            raise forms.ValidationError(
                "Enter a title or URL, choose a replacement file, or change cleaning options."
            )
        return cleaned_data

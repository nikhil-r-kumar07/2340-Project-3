from pathlib import Path

from django import forms


def validate_source_file(upload):
    if Path(upload.name).suffix.lower() not in {".pdf", ".txt"}:
        raise forms.ValidationError("Choose a PDF or TXT file.")


class LocalSourceForm(forms.Form):
    title = forms.CharField(max_length=200)
    file = forms.FileField(validators=[validate_source_file])


class UrlSourceForm(forms.Form):
    title = forms.CharField(max_length=200)
    url = forms.URLField()


class UpdateSourceForm(forms.Form):
    title = forms.CharField(max_length=200, required=False)
    file = forms.FileField(required=False, validators=[validate_source_file])

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("title") and not cleaned_data.get("file"):
            raise forms.ValidationError("Enter a title or choose a replacement file.")
        return cleaned_data

from __future__ import annotations

from django import forms


class AddWatchlistForm(forms.Form):
    url = forms.URLField(label="作品 URL")


class UpdateWorkEnabledForm(forms.Form):
    work_id = forms.CharField(widget=forms.HiddenInput)
    enabled = forms.BooleanField(required=False)


class ManualRunForm(forms.Form):
    pass

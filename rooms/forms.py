from django import forms
from django.contrib.auth import get_user_model

from .models import CODE_LENGTH, Item, Payment, Room

User = get_user_model()

INPUT_CLASSES = (
    "w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 "
    "placeholder-gray-400 focus:border-indigo-500 focus:outline-none "
    "focus:ring-1 focus:ring-indigo-500"
)
WEIGHT_CLASSES = (
    "w-16 rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-900 "
    "focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
)


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": INPUT_CLASSES, "placeholder": "e.g. Friday dinner"}
            ),
        }


class RoomAdjustmentsForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ["tax_amount", "tip_amount"]
        widgets = {
            "tax_amount": forms.NumberInput(
                attrs={"class": INPUT_CLASSES, "step": "0.01", "min": "0.00"}
            ),
            "tip_amount": forms.NumberInput(
                attrs={"class": INPUT_CLASSES, "step": "0.01", "min": "0.00"}
            ),
        }


class GuestForm(forms.Form):
    """Just a display name — everything else is generated server-side."""
    name = forms.CharField(
        max_length=60,
        widget=forms.TextInput(
            attrs={"class": INPUT_CLASSES, "placeholder": "e.g. Bob from work"}
        ),
    )


class JoinCodeForm(forms.Form):
    code = forms.CharField(
        max_length=CODE_LENGTH, min_length=CODE_LENGTH, strip=True,
        widget=forms.TextInput(attrs={
            "class": INPUT_CLASSES + " uppercase tracking-widest text-center",
            "placeholder": "K7M2QX",
            "autocomplete": "off",
        }),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].upper().replace(" ", "")
        if not Room.objects.filter(join_code=code).exists():
            raise forms.ValidationError("No room found with that code.")
        return code


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["description", "cost"]
        widgets = {
            "description": forms.TextInput(
                attrs={"class": INPUT_CLASSES, "placeholder": "e.g. Pad Thai"}
            ),
            "cost": forms.NumberInput(
                attrs={"class": INPUT_CLASSES, "step": "0.01", "min": "0.01"}
            ),
        }

    def __init__(self, *args, approved_members=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.approved_members = list(approved_members or [])

        existing = {}
        if self.instance and self.instance.pk:
            existing = {s.member_id: s.weight for s in self.instance.shares.all()}

        for m in self.approved_members:
            uid = m.user_id
            self.fields[f"share_{uid}"] = forms.BooleanField(
                required=False, initial=(uid in existing),
            )
            self.fields[f"weight_{uid}"] = forms.IntegerField(
                min_value=1, required=False, initial=existing.get(uid, 1),
                widget=forms.NumberInput(
                    attrs={"class": WEIGHT_CLASSES, "min": "1", "step": "1"}
                ),
            )

    def clean(self):
        cleaned = super().clean()
        if not self.approved_members:
            return cleaned
        any_selected = any(
            cleaned.get(f"share_{m.user_id}") for m in self.approved_members
        )
        if not any_selected:
            raise forms.ValidationError(
                "Pick at least one person to split this item between."
            )
        return cleaned

    def share_pairs(self):
        for m in self.approved_members:
            uid = m.user_id
            if self.cleaned_data.get(f"share_{uid}"):
                weight = self.cleaned_data.get(f"weight_{uid}") or 1
                yield uid, weight


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount_paid", "note"]
        widgets = {
            "amount_paid": forms.NumberInput(
                attrs={"class": INPUT_CLASSES, "step": "0.01", "min": "0.01"}
            ),
            "note": forms.TextInput(
                attrs={"class": INPUT_CLASSES, "placeholder": "optional — e.g. Venmo"}
            ),
        }
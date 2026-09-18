# rooms/models.py
import secrets
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
MIN_AMOUNT = Decimal("0.01")
CLAIM_CODE_BYTES = 12


def generate_join_code():
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def generate_claim_code():
    return secrets.token_urlsafe(CLAIM_CODE_BYTES)


class Room(models.Model):
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hosted_rooms",
    )
    name = models.CharField(max_length=100)
    join_code = models.CharField(max_length=CODE_LENGTH, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    tax_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    tip_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    # Archived rooms are hidden from the active list and reject new items
    # and payments. The data stays — unarchive to bring them back.
    is_archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        #makes a join code if the rooms doesnt have one yet
        if not self.join_code:
            self.join_code = self._generate_unique_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_unique_code():
        #Generates a unique code for the room
        while True:
            code = generate_join_code()
            #make sure generated code doesnt already exist
            if not Room.objects.filter(join_code=code).exists():
                return code

    def __str__(self):
        return f"{self.name} ({self.join_code})"


class Membership(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REMOVED = "removed", "Removed"

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    is_guest = models.BooleanField(default=False)
    claim_code = models.CharField(max_length=32, unique=True, blank=True, null=True)

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["room", "user"], name="unique_membership_per_room"
            )
        ]

    def save(self, *args, **kwargs):
        #gives guest a claim code so that they can retrieve their data if they decide to sign up
        if self.is_guest and not self.claim_code:
            self.claim_code = self._generate_unique_claim_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_unique_claim_code():
        while True:
            code = generate_claim_code()
            if not Membership.objects.filter(claim_code=code).exists():
                return code

    @property
    def display_name(self):
        return self.user.first_name or self.user.username

    @property
    def total_owed(self):
        from decimal import ROUND_HALF_EVEN
        cents = Decimal("0.01")
        total = Decimal("0.00")
        for share in self.user.item_shares.filter(item__room=self.room):
            shares = list(share.item.shares.all())
            total_weight = sum(s.weight for s in shares)
            if total_weight:
                total += (share.item.cost * share.weight / total_weight).quantize(
                    cents, rounding=ROUND_HALF_EVEN
                )
        return total

    @property
    def total_paid(self):
        total = self.room.payments.filter(member=self.user).aggregate(
            total=Sum("amount_paid")
        )["total"]
        return total or Decimal("0.00")

    @property
    def balance(self):
        return self.total_owed - self.total_paid

    def __str__(self):
        return f"{self.user} in {self.room} ({self.status})"


class Item(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=200)
    cost = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(MIN_AMOUNT)]
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="items_created",
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.description} — {self.cost}"


class ItemShare(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="shares")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="item_shares"
    )
    weight = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "member"], name="unique_share_per_item_member"
            )
        ]

    def __str__(self):
        return f"{self.member} × {self.weight} on {self.item}"


class Payment(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="payments")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments"
    )
    amount_paid = models.DecimalField(
        max_digits=8, decimal_places=2, validators=[MinValueValidator(MIN_AMOUNT)]
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        return f"{self.member} paid {self.amount_paid} for {self.room}"
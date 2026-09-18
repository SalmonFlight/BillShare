# rooms/views.py
import secrets
from decimal import Decimal, ROUND_HALF_EVEN

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import (
    GuestForm,
    ItemForm,
    JoinCodeForm,
    PaymentForm,
    RoomAdjustmentsForm,
    RoomForm,
)
from .models import Item, ItemShare, Membership, Payment, Room

User = get_user_model()
CENTS = Decimal("0.01")


# ----------------------------------------------------------------------
# Permission helpers
# ----------------------------------------------------------------------

def get_approved_membership(request, room):
    """Get the current user's approved membership for this room, or 403."""
    membership = room.memberships.filter(user=request.user).first()
    if membership is None or membership.status != Membership.Status.APPROVED:
        raise PermissionDenied("You are not an approved member of this room.")
    return membership


def _archive_block(request, room):
    """Returns a redirect response if the room is archived, else None.

    Used at the top of views that shouldn't work on archived rooms.
    """
    if room.is_archived:
        messages.error(
            request,
            "This room is archived. Unarchive it to make changes.",
        )
        return redirect("rooms:room_detail", pk=room.pk)
    return None


# ----------------------------------------------------------------------
# Balance calculation
# ----------------------------------------------------------------------

def compute_subtotals(room):
    """Return {user_id: subtotal} for the whole room, in one pass.

    For each item, split its cost across its shares by weight.
    Rounding uses banker's rounding and the last share absorbs the
    remainder so the parts sum exactly to the item's cost.
    """
    subtotals = {}
    items = room.items.prefetch_related("shares")

    for item in items:
        shares = list(item.shares.all())
        if not shares:
            continue
        total_weight = sum(s.weight for s in shares)
        if total_weight <= 0:
            continue

        # Keep track of what we've allocated so the last share can take
        # whatever's left (handles rounding remainders).
        allocated = Decimal("0.00")
        last = len(shares) - 1
        for i, share in enumerate(shares):
            if i < last:
                portion = (item.cost * share.weight / total_weight).quantize(
                    CENTS, rounding=ROUND_HALF_EVEN
                )
                allocated += portion
            else:
                portion = item.cost - allocated
            subtotals[share.member_id] = (
                subtotals.get(share.member_id, Decimal("0.00")) + portion
            )

    return subtotals


def allocate_shared_costs(members, room):
    """Attach tax_share, tip_share, grand_total, balance_due to each member.

    Tax and tip are split proportional to subtotal. Same rounding trick
    as compute_subtotals — the last member takes the remainder so the
    shares sum exactly to the room's tax/tip amounts.
    """
    total_subtotal = sum((m.subtotal for m in members), Decimal("0.00"))
    tax = room.tax_amount
    tip = room.tip_amount

    # Nobody's ordered anything — no base to split against.
    if total_subtotal <= 0:
        for m in members:
            m.tax_share = Decimal("0.00")
            m.tip_share = Decimal("0.00")
            m.grand_total = m.subtotal
            m.balance_due = m.subtotal - m.paid
        return members

    allocated_tax = Decimal("0.00")
    allocated_tip = Decimal("0.00")
    last_index = len(members) - 1

    for i, m in enumerate(members):
        if i < last_index:
            share = m.subtotal / total_subtotal
            m.tax_share = (share * tax).quantize(CENTS, rounding=ROUND_HALF_EVEN)
            m.tip_share = (share * tip).quantize(CENTS, rounding=ROUND_HALF_EVEN)
            allocated_tax += m.tax_share
            allocated_tip += m.tip_share
        else:
            m.tax_share = tax - allocated_tax
            m.tip_share = tip - allocated_tip

        m.grand_total = m.subtotal + m.tax_share + m.tip_share
        m.balance_due = m.grand_total - m.paid

    return members


def _approved_members_with_allocations(room):
    """Load approved members and attach subtotal/paid/tax/tip/balance to each.

    This is the pipeline the dashboard uses. Subtotals and payments are
    fetched in bulk (not per-member) so we don't get N+1 queries.
    """
    members = list(
        room.memberships
        .filter(status=Membership.Status.APPROVED)
        .select_related("user")
    )
    subtotals = compute_subtotals(room)

    # One query for all payments in this room, then turn it into a dict
    # {user_id: total} so we don't hit the DB per member.
    paid_by_user = dict(
        Payment.objects
        .filter(room=room)
        .values("member_id")
        .annotate(total=Sum("amount_paid"))
        .values_list("member_id", "total")
    )

    for m in members:
        m.subtotal = subtotals.get(m.user_id, Decimal("0.00"))
        m.paid = paid_by_user.get(m.user_id, Decimal("0.00"))

    return allocate_shared_costs(members, room)


def _is_settled(approved_members, room):
    """True if no non-host member owes money.

    The host's own 'balance' is their share of the bill, not something
    anyone owes them, so we skip it.
    """
    return all(
        m.balance_due <= 0
        for m in approved_members
        if m.user_id != room.host_id
    )


# ----------------------------------------------------------------------
# Room list
# ----------------------------------------------------------------------

@login_required
def room_list(request):
    hosted = Room.objects.filter(host=request.user, is_archived=False)

    member_of = (
        Room.objects
        .filter(
            memberships__user=request.user,
            memberships__status=Membership.Status.APPROVED,
            is_archived=False,
        )
        .exclude(host=request.user)  # don't show the same room twice
    )

    # Archived rooms where the user is host OR approved member.
    # distinct() because the filter can match a room twice.
    archived = (
        Room.objects
        .filter(is_archived=True)
        .filter(
            Q(host=request.user)
            | Q(
                memberships__user=request.user,
                memberships__status=Membership.Status.APPROVED,
            )
        )
        .distinct()
    )

    pending = (
        Membership.objects
        .filter(user=request.user, status=Membership.Status.PENDING)
        .select_related("room")
    )

    return render(request, "rooms/room_list.html", {
        "hosted": hosted,
        "member_of": member_of,
        "archived": archived,
        "pending": pending,
    })


# ----------------------------------------------------------------------
# My debts
# ----------------------------------------------------------------------

@login_required
def my_debts(request):
    """Rooms where the current user owes money to the host."""
    memberships = (
        Membership.objects
        .filter(user=request.user, status=Membership.Status.APPROVED)
        .select_related("room", "room__host")
        .exclude(room__host=request.user)  # you can't owe yourself
        .exclude(room__is_archived=True)
    )

    debts = []
    for m in memberships:
        members = _approved_members_with_allocations(m.room)
        me = next((x for x in members if x.user_id == request.user.id), None)
        if me is None or me.balance_due <= 0:
            continue
        debts.append({
            "room": m.room,
            "amount": me.balance_due,
            "creditor": m.room.host,
            "subtotal": me.subtotal,
            "tax": me.tax_share,
            "tip": me.tip_share,
            "paid": me.paid,
        })

    total = sum((d["amount"] for d in debts), Decimal("0.00"))
    return render(request, "rooms/my_debts.html", {"debts": debts, "total": total})


# ----------------------------------------------------------------------
# Create room
# ----------------------------------------------------------------------

@login_required
def room_create(request):
    if request.method == "POST":
        form = RoomForm(request.POST)
        if form.is_valid():
            room = form.save(commit=False)
            room.host = request.user   # never trust the form for this
            room.save()
            # Host gets an approved membership so all views can treat
            # them like any other member.
            Membership.objects.create(
                room=room, user=request.user,
                status=Membership.Status.APPROVED,
            )
            messages.success(request, f"Room created. Share this code: {room.join_code}")
            return redirect("rooms:room_detail", pk=room.pk)
    else:
        form = RoomForm()
    return render(request, "rooms/room_create.html", {"form": form})


# ----------------------------------------------------------------------
# Room settings
# ----------------------------------------------------------------------

@login_required
def room_settings(request, pk):
    # get_object_or_404 with host=request.user means non-hosts get a 404,
    # not a 403 — they can't even confirm the room exists.
    room = get_object_or_404(Room, pk=pk, host=request.user)
    if request.method == "POST":
        form = RoomAdjustmentsForm(request.POST, instance=room)
        if form.is_valid():
            form.save()
            messages.success(request, "Tax and tip updated.")
            return redirect("rooms:room_detail", pk=room.pk)
    else:
        form = RoomAdjustmentsForm(instance=room)
    return render(request, "rooms/room_settings.html", {"room": room, "form": form})


# ----------------------------------------------------------------------
# Archive / unarchive / delete
# ----------------------------------------------------------------------

@login_required
@require_POST
def room_archive(request, pk):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    room.is_archived = True
    room.save(update_fields=["is_archived"])
    messages.success(request, f"Archived {room.name}.")
    return redirect("rooms:room_list")


@login_required
@require_POST
def room_unarchive(request, pk):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    room.is_archived = False
    room.save(update_fields=["is_archived"])
    messages.success(request, f"Unarchived {room.name}.")
    return redirect("rooms:room_detail", pk=room.pk)


@login_required
def room_delete(request, pk):
    room = get_object_or_404(Room, pk=pk, host=request.user)

    # Two guards before we let anyone delete: must be archived,
    # and everyone must be settled.
    if not room.is_archived:
        messages.error(
            request,
            "Archive the room before deleting it — that's the safety catch.",
        )
        return redirect("rooms:room_detail", pk=room.pk)

    members = _approved_members_with_allocations(room)
    if not _is_settled(members, room):
        messages.error(
            request,
            "Can't delete — someone still owes money in this room.",
        )
        return redirect("rooms:room_detail", pk=room.pk)

    if request.method == "POST":
        name = room.name
        room.delete()
        messages.success(request, f"Deleted {name}.")
        return redirect("rooms:room_list")

    # GET: show the confirmation page with what's about to be destroyed.
    item_count = room.items.count()
    payment_count = room.payments.count()
    total_spent = room.items.aggregate(total=Sum("cost"))["total"] or Decimal("0.00")

    return render(request, "rooms/room_delete.html", {
        "room": room,
        "item_count": item_count,
        "payment_count": payment_count,
        "total_spent": total_spent,
    })


# ----------------------------------------------------------------------
# Join flow
# ----------------------------------------------------------------------

@login_required
def join_by_code(request):
    if request.method == "POST":
        form = JoinCodeForm(request.POST)
        if form.is_valid():
            # Form already checked the code exists and normalized it.
            return redirect("rooms:join_room", code=form.cleaned_data["code"])
    else:
        form = JoinCodeForm()
    return render(request, "rooms/join_by_code.html", {"form": form})


@login_required
def join_room(request, code):
    room = get_object_or_404(Room, join_code=code.upper())

    # Host is already in — no need to request to join their own room.
    if room.host_id == request.user.id:
        return redirect("rooms:room_detail", pk=room.pk)

    existing = room.memberships.filter(user=request.user).first()

    if request.method == "POST":
        # State machine: none → pending, rejected → pending (re-request),
        # approved → nothing (already in), removed → blocked.
        if existing is None:
            Membership.objects.create(
                room=room, user=request.user, status=Membership.Status.PENDING
            )
            messages.success(request, "Join request sent.")
        elif existing.status == Membership.Status.PENDING:
            messages.info(request, "Your request is already pending.")
        elif existing.status == Membership.Status.REJECTED:
            existing.status = Membership.Status.PENDING
            existing.save(update_fields=["status"])
            messages.success(request, "Join request re-sent.")
        elif existing.status == Membership.Status.APPROVED:
            return redirect("rooms:room_detail", pk=room.pk)
        elif existing.status == Membership.Status.REMOVED:
            messages.error(request, "You were removed from this room by the host.")
        return redirect("rooms:join_room", code=room.join_code)

    return render(request, "rooms/join_room.html", {
        "room": room, "membership": existing,
    })


# ----------------------------------------------------------------------
# Room detail (dashboard)
# ----------------------------------------------------------------------

@login_required
def room_detail(request, pk):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)  # 403 if not approved
    is_host = room.host_id == request.user.id

    approved_members = _approved_members_with_allocations(room)

    summary = {
        "subtotal": sum((m.subtotal for m in approved_members), Decimal("0.00")),
        "tax": room.tax_amount,
        "tip": room.tip_amount,
        "total": sum((m.grand_total for m in approved_members), Decimal("0.00")),
        "paid": sum((m.paid for m in approved_members), Decimal("0.00")),
    }
    # Outstanding = what's owed to the host by everyone else.
    # The host's own balance is their own share, not a debt.
    summary["outstanding"] = sum(
        (m.balance_due for m in approved_members if m.user_id != room.host_id),
        Decimal("0.00"),
    )

    # prefetch_related + select_related so the template can loop through
    # shares and creators without triggering extra queries.
    items = room.items.prefetch_related("shares__member").select_related("created_by")

    return render(request, "rooms/room_detail.html", {
        "room": room,
        "membership": membership,
        "is_host": is_host,
        "approved_members": approved_members,
        "summary": summary,
        "items": items,
        "is_settled": _is_settled(approved_members, room),
    })


# ----------------------------------------------------------------------
# Member detail
# ----------------------------------------------------------------------

@login_required
def member_detail(request, pk, membership_id):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)
    is_host = room.host_id == request.user.id

    members = _approved_members_with_allocations(room)
    target = next((m for m in members if m.pk == membership_id), None)
    if target is None:
        raise Http404("No approved member with that id in this room.")

    # Build one row per item this member is involved in, with their
    # portion of that item already computed.
    item_rows = []
    shared_items = (
        Item.objects
        .filter(room=room, shares__member=target.user)
        .prefetch_related("shares__member")
    )
    for item in shared_items:
        shares = list(item.shares.all())
        total_weight = sum(s.weight for s in shares) or 1
        my_share = next(s for s in shares if s.member_id == target.user_id)
        portion = (item.cost * my_share.weight / total_weight).quantize(
            CENTS, rounding=ROUND_HALF_EVEN
        )
        item_rows.append({
            "item": item,
            "my_portion": portion,
            "my_weight": my_share.weight,
            "total_weight": total_weight,
        })

    payments = room.payments.filter(member=target.user)

    return render(request, "rooms/member_detail.html", {
        "room": room,
        "membership": membership,
        "is_host": is_host,
        "target": target,
        "item_rows": item_rows,
        "payments": payments,
    })


# ----------------------------------------------------------------------
# Guests
# ----------------------------------------------------------------------

@login_required
def guest_create(request, pk):
    room = get_object_or_404(Room, pk=pk, host=request.user)

    if request.method == "POST":
        form = GuestForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"].strip()
            # Wrap in a transaction so we don't end up with a User
            # created but no Membership (or vice versa).
            with transaction.atomic():
                # Opaque username so the guest name never blocks a real
                # signup later. Human name goes in first_name instead.
                shadow = User(username=f"guest_{secrets.token_hex(6)}")
                shadow.set_unusable_password()
                shadow.first_name = name
                shadow.save()
                Membership.objects.create(
                    room=room, user=shadow,
                    status=Membership.Status.APPROVED,
                    is_guest=True,
                )
            messages.success(request, f"Added guest: {name}")
            return redirect("rooms:room_detail", pk=room.pk)
    else:
        form = GuestForm()

    return render(request, "rooms/guest_form.html", {"room": room, "form": form})


# ----------------------------------------------------------------------
# Claim guest identity
# ----------------------------------------------------------------------

@login_required
def claim_guest(request, code):
    """Transfer a guest's data to a real user, then delete the guest."""
    guest_membership = get_object_or_404(
        Membership, claim_code=code, is_guest=True
    )
    room = guest_membership.room
    shadow = guest_membership.user
    real = request.user

    if shadow.id == real.id:
        messages.info(request, "This is already your account.")
        return redirect("rooms:room_detail", pk=room.pk)

    # Don't let someone end up with two memberships in the same room.
    existing_real = (
        room.memberships.filter(user=real)
        .exclude(pk=guest_membership.pk)
        .first()
    )
    if existing_real is not None:
        messages.error(request, f"You already have a membership in {room.name}.")
        return redirect("rooms:room_list")

    if request.method == "POST":
        # Everything in one transaction so a failure doesn't leave
        # FKs half-moved.
        with transaction.atomic():
            # Reassign item shares — if the real user already had a
            # share on the same item, merge weights instead of erroring.
            for share in ItemShare.objects.filter(member=shadow, item__room=room):
                existing = ItemShare.objects.filter(
                    item=share.item, member=real
                ).first()
                if existing:
                    existing.weight += share.weight
                    existing.save(update_fields=["weight"])
                    share.delete()
                else:
                    share.member = real
                    share.save(update_fields=["member"])

            # Payments and item audit trail, wholesale.
            Payment.objects.filter(room=room, member=shadow).update(member=real)
            Item.objects.filter(room=room, created_by=shadow).update(created_by=real)

            # Keep the host's nice display name, but don't overwrite a
            # name the real user already set for themselves.
            if not real.first_name and shadow.first_name:
                real.first_name = shadow.first_name
                real.save(update_fields=["first_name"])

            # Point the membership at the real user, remove guest flag
            # and claim code (so the link is dead after this).
            guest_membership.user = real
            guest_membership.is_guest = False
            guest_membership.claim_code = None
            guest_membership.save()

            shadow.delete()

        messages.success(
            request,
            f"You've claimed the guest entry for {room.name}.",
        )
        return redirect("rooms:room_detail", pk=room.pk)

    return render(request, "rooms/claim_guest.html", {
        "room": room,
        "guest_membership": guest_membership,
    })


# ----------------------------------------------------------------------
# Leave / remove
# ----------------------------------------------------------------------

@login_required
@require_POST
def leave_room(request, pk):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)
    if room.host_id == request.user.id:
        messages.error(request, "The host can't leave their own room.")
        return redirect("rooms:room_detail", pk=room.pk)

    # Block leaving if they still have skin in the game — otherwise
    # their items would silently disappear from the bill.
    has_activity = (
        ItemShare.objects.filter(item__room=room, member=request.user).exists()
        or room.payments.filter(member=request.user).exists()
    )
    if has_activity:
        messages.error(
            request,
            "You can't leave while you have items or payments in this room.",
        )
        return redirect("rooms:room_detail", pk=room.pk)

    membership.status = Membership.Status.REJECTED
    membership.save(update_fields=["status"])
    messages.success(request, f"You've left {room.name}.")
    return redirect("rooms:room_list")


@login_required
@require_POST
def member_remove(request, pk, membership_id):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    membership = get_object_or_404(Membership, pk=membership_id, room=room)

    if membership.user_id == room.host_id:
        messages.error(request, "The host can't be removed.")
        return redirect("rooms:room_detail", pk=room.pk)
    if membership.status != Membership.Status.APPROVED:
        messages.error(request, "Only approved members can be removed.")
        return redirect("rooms:room_detail", pk=room.pk)

    has_activity = (
        ItemShare.objects.filter(item__room=room, member=membership.user).exists()
        or room.payments.filter(member=membership.user).exists()
    )
    if has_activity:
        messages.error(
            request,
            f"Cannot remove {membership.display_name} — they have items or "
            f"payments in this room.",
        )
        return redirect("rooms:room_detail", pk=room.pk)

    # Guests don't have an account to "remove" — hard-delete them.
    if membership.is_guest:
        shadow = membership.user
        membership.delete()
        shadow.delete()
        messages.success(request, "Guest removed.")
        return redirect("rooms:room_detail", pk=room.pk)

    # Real users get a REMOVED status — different from REJECTED because
    # a removed member can't just re-request via the join flow.
    membership.status = Membership.Status.REMOVED
    membership.save(update_fields=["status"])
    messages.success(request, f"Removed {membership.display_name}.")
    return redirect("rooms:room_detail", pk=room.pk)


# ----------------------------------------------------------------------
# Host: review join requests
# ----------------------------------------------------------------------

@login_required
def room_requests(request, pk):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    pending = (
        room.memberships.filter(status=Membership.Status.PENDING)
        .select_related("user")
    )
    return render(request, "rooms/room_requests.html", {"room": room, "pending": pending})


@login_required
@require_POST
def approve_request(request, pk, membership_id):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    membership = get_object_or_404(Membership, pk=membership_id, room=room)
    membership.status = Membership.Status.APPROVED
    membership.save(update_fields=["status"])
    messages.success(request, f"Approved {membership.display_name}.")
    return redirect("rooms:room_requests", pk=room.pk)


@login_required
@require_POST
def reject_request(request, pk, membership_id):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    membership = get_object_or_404(Membership, pk=membership_id, room=room)
    membership.status = Membership.Status.REJECTED
    membership.save(update_fields=["status"])
    messages.info(request, f"Rejected {membership.display_name}.")
    return redirect("rooms:room_requests", pk=room.pk)


# ----------------------------------------------------------------------
# Items
# ----------------------------------------------------------------------

def _approved_members_list(room):
    """Plain list of approved memberships, for the item form's split rows."""
    return list(
        room.memberships
        .filter(status=Membership.Status.APPROVED)
        .select_related("user")
    )


def _share_rows_for_template(form, approved_members):
    """Bundle each member's two dynamic form fields (checkbox + weight).

    Templates can't look up fields by a variable name, so we pre-build
    the list here and pass it in as a context variable.
    """
    return [
        {
            "user": m.user,
            "display_name": m.display_name,
            "share_field": form[f"share_{m.user_id}"],
            "weight_field": form[f"weight_{m.user_id}"],
        }
        for m in approved_members
    ]


@login_required
def item_create(request, pk):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)
    if (blocked := _archive_block(request, room)):
        return blocked
    approved_members = _approved_members_list(room)

    if request.method == "POST":
        form = ItemForm(request.POST, approved_members=approved_members)
        if form.is_valid():
            item = form.save(commit=False)
            item.room = room
            item.created_by = request.user    # never trust the form for this
            item.save()
            # Create one ItemShare per ticked member.
            for uid, weight in form.share_pairs():
                ItemShare.objects.create(item=item, member_id=uid, weight=weight)
            messages.success(request, f"Added: {item.description}")
            return redirect("rooms:room_detail", pk=room.pk)
    else:
        # Pre-tick the current user — most items are just for themselves.
        form = ItemForm(
            approved_members=approved_members,
            initial={f"share_{request.user.id}": True},
        )

    return render(request, "rooms/item_form.html", {
        "room": room,
        "form": form,
        "membership": membership,
        "share_rows": _share_rows_for_template(form, approved_members),
        "heading": f"Add an item to {room.name}",
        "submit_label": "Add item",
    })


@login_required
def item_edit(request, pk, item_id):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)
    if (blocked := _archive_block(request, room)):
        return blocked
    # Scoping the fetch to this room means you can't edit items in rooms
    # you're not in, even if you guess the item id.
    item = get_object_or_404(Item, pk=item_id, room=room)
    approved_members = _approved_members_list(room)

    # Only the original creator or the host can edit.
    is_host = room.host_id == request.user.id
    if item.created_by_id != request.user.id and not is_host:
        raise PermissionDenied("You can only edit items you created.")

    if request.method == "POST":
        form = ItemForm(
            request.POST, instance=item, approved_members=approved_members
        )
        if form.is_valid():
            form.save()
            # Simplest way to update shares: wipe and recreate.
            item.shares.all().delete()
            for uid, weight in form.share_pairs():
                ItemShare.objects.create(item=item, member_id=uid, weight=weight)
            messages.success(request, "Item updated.")
            return redirect("rooms:room_detail", pk=room.pk)
    else:
        form = ItemForm(instance=item, approved_members=approved_members)

    return render(request, "rooms/item_form.html", {
        "room": room,
        "form": form,
        "membership": membership,
        "share_rows": _share_rows_for_template(form, approved_members),
        "heading": f"Edit item in {room.name}",
        "submit_label": "Save changes",
    })


@login_required
@require_POST
def item_delete(request, pk, item_id):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)
    if (blocked := _archive_block(request, room)):
        return blocked
    item = get_object_or_404(Item, pk=item_id, room=room)

    is_host = room.host_id == request.user.id
    if item.created_by_id != request.user.id and not is_host:
        raise PermissionDenied("You can only delete items you created.")

    item.delete()
    messages.info(request, "Item removed.")
    return redirect("rooms:room_detail", pk=room.pk)


# ----------------------------------------------------------------------
# Payments (host only)
# ----------------------------------------------------------------------

@login_required
def payment_create(request, pk):
    room = get_object_or_404(Room, pk=pk)
    membership = get_approved_membership(request, room)
    if (blocked := _archive_block(request, room)):
        return blocked
    if room.host_id != request.user.id:
        raise PermissionDenied("Only the host can record payments.")

    # Who is this payment for? Comes from the query string on first
    # render, hidden input on submit.
    member_id = request.GET.get("member") or request.POST.get("member")
    if not member_id:
        messages.error(request, "No member specified for this payment.")
        return redirect("rooms:room_detail", pk=room.pk)

    # Look up the target in the allocated members list — this also
    # validates that they're an approved member of *this* room.
    all_members = _approved_members_with_allocations(room)
    target = next(
        (m for m in all_members if str(m.user_id) == str(member_id)), None
    )
    if target is None:
        raise Http404("No approved member with that id in this room.")

    if request.method == "POST":
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.room = room
            payment.member = target.user
            payment.save()
            messages.success(
                request,
                f"Recorded {payment.amount_paid} from {target.display_name}.",
            )
            return redirect("rooms:room_detail", pk=room.pk)
    else:
        form = PaymentForm()

    return render(request, "rooms/payment_form.html", {
        "room": room, "form": form, "membership": membership,
        "target_membership": target,
    })


@login_required
@require_POST
def payment_delete(request, pk, payment_id):
    room = get_object_or_404(Room, pk=pk, host=request.user)
    get_approved_membership(request, room)  # also ensure they're approved
    if (blocked := _archive_block(request, room)):
        return blocked
    payment = get_object_or_404(Payment, pk=payment_id, room=room)
    payment.delete()
    messages.info(request, "Payment removed.")
    return redirect("rooms:room_detail", pk=room.pk)
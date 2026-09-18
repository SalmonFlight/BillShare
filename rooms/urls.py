from django.urls import path

from . import views

app_name = "rooms"

urlpatterns = [
    # Room list / my debts
    path("", views.room_list, name="room_list"),
    path("my-debts/", views.my_debts, name="my_debts"),

    # Create a room
    path("create/", views.room_create, name="room_create"),

    # Join flow (with a code)
    path("join/", views.join_by_code, name="join_by_code"),
    path("join/<str:code>/", views.join_room, name="join_room"),
    path("claim/<str:code>/", views.claim_guest, name="claim_guest"),

    # Room detail and settings
    path("<int:pk>/", views.room_detail, name="room_detail"),
    path("<int:pk>/settings/", views.room_settings, name="room_settings"),

    # Archive / unarchive / delete
    path("<int:pk>/archive/", views.room_archive, name="room_archive"),
    path("<int:pk>/unarchive/", views.room_unarchive, name="room_unarchive"),
    path("<int:pk>/delete/", views.room_delete, name="room_delete"),

    # Leave / guest management
    path("<int:pk>/leave/", views.leave_room, name="leave_room"),
    path("<int:pk>/guests/add/", views.guest_create, name="guest_create"),

    # Host: review join requests
    path("<int:pk>/requests/", views.room_requests, name="room_requests"),
    path(
        "<int:pk>/requests/<int:membership_id>/approve/",
        views.approve_request, name="approve_request",
    ),
    path(
        "<int:pk>/requests/<int:membership_id>/reject/",
        views.reject_request, name="reject_request",
    ),

    # Items
    path("<int:pk>/items/add/", views.item_create, name="item_create"),
    path(
        "<int:pk>/items/<int:item_id>/edit/",
        views.item_edit, name="item_edit",
    ),
    path(
        "<int:pk>/items/<int:item_id>/delete/",
        views.item_delete, name="item_delete",
    ),

    # Members
    path(
        "<int:pk>/members/<int:membership_id>/",
        views.member_detail, name="member_detail",
    ),
    path(
        "<int:pk>/members/<int:membership_id>/remove/",
        views.member_remove, name="member_remove",
    ),

    # Payments (host only)
    path("<int:pk>/payments/add/", views.payment_create, name="payment_create"),
    path(
        "<int:pk>/payments/<int:payment_id>/delete/",
        views.payment_delete, name="payment_delete",
    ),
]
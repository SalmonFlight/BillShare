from django.contrib import admin
from .models import Room, Membership, Item, Payment

admin.site.register(Room)
admin.site.register(Membership)
admin.site.register(Item)
admin.site.register(Payment)
from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import SignupForm


def signup(request):
    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)          # log them in immediately
            return redirect("rooms:room_list")
    else:
        form = SignupForm()

    return render(request, "accounts/signup.html", {"form": form})
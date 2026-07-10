from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Research identity", {"fields": ("orcid",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Research identity", {"fields": ("orcid",)}),
    )

from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Signature, Document

@admin.register(Signature)
class SignatureAdmin(ModelAdmin):
    list_display = ["user"]
    search_fields = ["user__username"]

@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    list_display = ["title", "owner", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "owner__username"]
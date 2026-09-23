from django.contrib import admin
from .models import Surface


@admin.register(Surface)
class SurfaceAdmin(admin.ModelAdmin):
    list_display = ("title", "created_by", "visibility", "updated_at")
    list_filter = ("visibility",)
    search_fields = ("title", "prompt")

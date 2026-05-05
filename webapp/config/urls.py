from django.contrib import admin
from django.urls import include, path

from chat.views import chat_ui

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", chat_ui, name="chat_ui"),
    path("api/", include("chat.urls")),
]

from django.contrib import admin
from django.urls import include, path

from chat import views as chat_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("chat.urls")),
    path("test-chat/", chat_views.test_chat, name="test_chat"),
]

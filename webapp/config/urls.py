from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from chat import views as chat_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", chat_views.chat_ui, name="chat_ui"),
    path("api/", include("chat.urls")),
    path("test-chat/", chat_views.test_chat, name="test_chat"),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

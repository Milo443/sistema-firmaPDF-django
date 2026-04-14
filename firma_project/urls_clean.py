from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'core/img/favicon.png')),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')), # <-- Rutas de login, logout, etc.
    path('', include('core.urls')), 
]

# Redirigido para servir media en producci?n`n
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

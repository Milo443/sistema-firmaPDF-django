# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    # Agregaremos más rutas aquí
    path('document/upload/', views.upload_document, name='upload_document'),
    path('signature/', views.manage_signature, name='manage_signature'),
    path('document/<int:pk>/sign/', views.sign_document_editor, name='sign_document_editor'),

    path('api/document/<int:pk>/save_signature/', views.api_save_signature, name='api_save_signature'),
    path('api/documents/<int:pk>/rasterize/', views.api_rasterize_document, name='api_rasterize_document'),
    path('api/documents/<int:pk>/flatten_original/', views.api_flatten_original, name='api_flatten_original'),
    path('api/documents/<int:pk>/delete/', views.delete_document, name='delete_document'),
    path('api/my-signature/', views.api_signature_proxy, name='api_signature_proxy'),

    path('redirect-after-login/', views.login_redirect_view, name='login_redirect'),
    
    # Password Reset
    path('accounts/password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('accounts/password-reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('accounts/reset/done/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
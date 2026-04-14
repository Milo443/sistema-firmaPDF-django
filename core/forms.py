# core/forms.py

from django import forms
from .models import Document, Signature
from django.core.validators import FileExtensionValidator

class DocumentForm(forms.ModelForm):
    original_file = forms.FileField(
        label='Seleccionar archivo PDF',
        validators=[FileExtensionValidator(allowed_extensions=['pdf'])],
        widget=forms.ClearableFileInput(attrs={'accept': 'application/pdf'})
    )

    class Meta:
        model = Document
        fields = ['title', 'original_file']
        labels = {
            'title': 'Título del Documento'
        }

class SignatureForm(forms.ModelForm):
    image = forms.ImageField(
        label='Sube tu firma (se recomienda archivo PNG con fondo transparente)',
        
        # 2. Añadimos el validador para permitir únicamente la extensión 'png'.
        validators=[FileExtensionValidator(allowed_extensions=['png'])],
        
        # 3. (Opcional pero recomendado) Mejoramos el widget para el frontend.
        #    Esto le dice al navegador que filtre y solo muestre archivos .png.
        widget=forms.ClearableFileInput(attrs={'accept': 'image/png'})
    )


    class Meta:
        model = Signature
        fields = ['image']


from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
import json
import urllib.request
import os
import logging

logger = logging.getLogger(__name__)

class CustomPasswordResetForm(PasswordResetForm):
    def save(self, domain_override=None, email_template_name=None,
             use_https=False, token_generator=default_token_generator,
             from_email=None, request=None, html_email_template_name=None,
             extra_email_context=None, **kwargs):
        
        email = self.cleaned_data["email"]
        active_users = self.get_users(email)
        
        for user in active_users:
            if not user.has_usable_password():
                continue
            
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = token_generator.make_token(user)
            
            protocol = 'https' if use_https or (request and request.is_secure()) else 'http'
            domain = domain_override or (request.get_host() if request else 'firma-ing.vooltlab.com')
            link = f"{protocol}://{domain}/accounts/reset/{uid}/{token}/"
            
            self.send_emailjs(user.email, link)

    def send_emailjs(self, email, link):
        url = "https://api.emailjs.com/api/v1.0/email/send"
        data = {
            'service_id': os.getenv('EMAILJS_SERVICE_ID'),
            'template_id': os.getenv('EMAILJS_TEMPLATE_ID'),
            'user_id': os.getenv('EMAILJS_PUBLIC_KEY'),
            'accessToken': os.getenv('EMAILJS_PRIVATE_KEY'),
            'template_params': {
                'email': email,
                'link': link,
            }
        }
        
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'))
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        
        try:
            with urllib.request.urlopen(req) as response:
                res_body = response.read().decode('utf-8')
                print(f"DEBUG: EmailJS Success: {res_body}")
                return res_body
        except urllib.error.HTTPError as e:
            res_body = e.read().decode('utf-8')
            print(f"DEBUG: EmailJS HTTP Error {e.code}: {res_body}")
            logger.error(f"EmailJS HTTP Error {e.code}: {res_body}")
        except Exception as e:
            print(f"DEBUG: EmailJS Exception: {e}")
            logger.error(f"Error enviando EmailJS: {e}")
        
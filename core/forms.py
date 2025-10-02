# core/forms.py

from django import forms
from .models import Document, Signature

class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['title', 'original_file']
        labels = {
            'title': 'Título del Documento',
            'original_file': 'Seleccionar archivo PDF',
        }

class SignatureForm(forms.ModelForm):
    class Meta:
        model = Signature
        fields = ['image']
        labels = {
            'image': 'Sube tu firma (se recomienda archivo PNG con fondo transparente)',
        }
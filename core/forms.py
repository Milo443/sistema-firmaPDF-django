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
        
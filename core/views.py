import json
import fitz
import tempfile
import os
import traceback
import logging

# Inicializar logger
logger = logging.getLogger('core')

import io
from rembg import remove

from PIL import Image
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_POST
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect , get_object_or_404 
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy
from .forms import CustomPasswordResetForm

class CustomPasswordResetView(auth_views.PasswordResetView):
    form_class = CustomPasswordResetForm
    template_name = 'registration/password_reset_form.html'
    success_url = reverse_lazy('password_reset_done')

class CustomPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'registration/password_reset_done.html'

class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'registration/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')

class CustomPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'registration/password_reset_complete.html'

# Asume que estos modelos ya tienen el campo 'status'
from .models import Document, Signature 
from .forms import DocumentForm, SignatureForm

# --- Funciones auxiliares (fuela de las vistas) ---
def rasterize_pdf(input_stream, output_stream, dpi=200):
    """
    Rasteriza un PDF convirtiendo cada página en una imagen y creando un nuevo PDF.
    
    Args:
        input_stream: Objeto tipo archivo o bytes del PDF de entrada.
        output_stream: Objeto tipo archivo o stream para guardar el PDF rasterizado.
        dpi (int): Resolución de las imágenes (puntos por pulgada).
    """
    try:
        # Si input_stream es un objeto de archivo de Django, leemos sus bytes
        if hasattr(input_stream, 'read'):
            source_doc = fitz.open(stream=input_stream.read(), filetype="pdf")
        else:
            source_doc = fitz.open(stream=input_stream, filetype="pdf")
            
        output_doc = fitz.open()
        
        for page in source_doc:
            pix = page.get_pixmap(dpi=dpi)
            new_page = output_doc.new_page(width=pix.width, height=pix.height)
            new_page.insert_image(new_page.rect, pixmap=pix)

        # Guardamos en el stream de salida
        pdf_bytes = output_doc.tobytes(garbage=4, deflate=True)
        output_stream.write(pdf_bytes)
        
        source_doc.close()
        output_doc.close()
        
    except Exception as e:
        logger.error(f"Error al rasterizar el PDF: {e}", exc_info=True)
        raise

# --- Vistas principales ---
@login_required
def dashboard(request):
    user_documents = Document.objects.filter(owner=request.user, is_active=True).order_by('-created_at')
    context = {
        'documents': user_documents
    }
    return render(request, 'core/dashboard.html', context)

@login_required
def upload_document(request):
    if request.method == 'POST':
        form = DocumentForm(request.POST, request.FILES)
        if form.is_valid():
            document = form.save(commit=False)
            document.owner = request.user
            document.status = 'uploaded' # Establece el estado inicial
            document.save()
            return redirect('dashboard')
    else:
        form = DocumentForm()
    
    context = {'form': form}
    return render(request, 'core/upload_document.html', context)

@login_required
def manage_signature(request):
    try:
        user_signature = Signature.objects.get(user=request.user)
    except Signature.DoesNotExist:
        user_signature = None

    if request.method == 'POST':
        # Se permiten formatos PNG, JPG y JPEG (rembg procesará el fondo)
        form = SignatureForm(request.POST, request.FILES, instance=user_signature)
        if form.is_valid():
            signature = form.save(commit=False)
            
            # --- Procesamiento con rembg para quitar el fondo ---
            try:
                # Abrir la imagen subida
                input_image = Image.open(request.FILES['image'])
                
                # Remover fondo usando IA
                output_image = remove(input_image)
                
                # Guardar el resultado en un buffer de memoria como PNG
                buffer = io.BytesIO()
                output_image.save(buffer, format='PNG')
                buffer.seek(0)
                
                # Asignar la imagen procesada al campo ImageField con un nombre único (timestamp)
                # Esto evita problemas de caché en el navegador y conflictos en el storage
                import time
                timestamp = int(time.time())
                file_name = f"signature_{request.user.id}_{timestamp}.png"
                
                signature.image.save(file_name, ContentFile(buffer.read()), save=False)
                
                logger.info(f"Firma procesada exitosamente con rembg para el usuario {request.user.username}")
            except Exception as e:
                logger.error(f"Error al procesar la firma con rembg: {e}", exc_info=True)
                # En caso de error, el flujo continúa con la imagen original subida por el usuario
            
            signature.user = request.user
            signature.save()
            return redirect('dashboard')
    else:
        form = SignatureForm(instance=user_signature)

    context = {
        'form': form,
        'user_signature': user_signature
    }
    return render(request, 'core/manage_signature.html', context)


@login_required
def sign_document_editor(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)

    try:
        user_signature = Signature.objects.get(user=request.user)
    except Signature.DoesNotExist:
        messages.error(request, 'Debes subir una firma antes de poder firmar un documento.')
        return redirect('manage_signature')

    num_pages = 0
    try:
        # Usamos .open() y stream para compatibilidad con S3/MinIO
        with document.original_file.open('rb') as f:
            pdf_doc = fitz.open(stream=f.read(), filetype="pdf")
            num_pages = pdf_doc.page_count
            pdf_doc.close()
    except Exception as e:
        logger.error(f"Error al leer el PDF para firma: {e}")
        messages.error(request, 'El archivo PDF parece estar dañado o no se puede leer.')
        return redirect('dashboard')
    
    if num_pages == 0:
        messages.error(request, 'El documento PDF no tiene páginas.')
        return redirect('dashboard')

    context = {
        'document': document,
        'signature_url': user_signature.image.url,
        'num_pages': num_pages,
    }
    return render(request, 'core/editor.html', context)



@login_required
@require_POST
def api_save_signature(request, pk):
    try:
        data = json.loads(request.body)
        if data['page_width'] == 0 or data['page_height'] == 0:
            return JsonResponse({'status': 'error', 'message': 'Las dimensiones de la página son cero.'}, status=400)

        document = get_object_or_404(Document, pk=pk, owner=request.user)
        signature = get_object_or_404(Signature, user=request.user)
        
        # --- Lógica de rotación de la firma ---
        with signature.image.open('rb') as f:
            img = Image.open(f)
            rotated_img = img.rotate(-data['rotation'], expand=True, resample=Image.Resampling.BICUBIC)
            
            # Obtener dimensiones reales de la imagen procesada (importante si expand=True cambió el tamaño)
            actual_w, actual_h = rotated_img.size
            img_aspect_ratio = actual_w / actual_h
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
                rotated_img.save(temp_img, "PNG")
                temp_image_path = temp_img.name

        # --- Lógica para insertar la firma en el PDF ---
        # Abrir el documento original mediante stream
        with document.original_file.open('rb') as f:
            pdf_doc = fitz.open(stream=f.read(), filetype="pdf")
            page_index = data['page_number'] - 1
            page = pdf_doc[page_index]
            
            # Conversión de coordenadas
            pdf_width = page.rect.width
            pdf_height = page.rect.height
            
            # Ratios para posicionamiento
            x_ratio = pdf_width / data['page_width']
            y_ratio = pdf_height / data['page_height']
            
            x = data['x'] * x_ratio
            y = data['y'] * y_ratio
            
            # Para las dimensiones (width/height), usamos x_ratio como escala base
            # y recalculamos el alto según la proporción real de la imagen rotada.
            # Esto evita que la firma se vea "estirada" o "aplastada".
            width_in_pdf = data['width'] * x_ratio
            height_in_pdf = width_in_pdf / img_aspect_ratio
            
            signature_rect = fitz.Rect(x, y, x + width_in_pdf, y + height_in_pdf)
            page.insert_image(signature_rect, filename=temp_image_path)
            
            # Obtener los bytes del PDF modificado directamente desde la memoria
            pdf_bytes = pdf_doc.tobytes(garbage=4, clean=True)
            pdf_doc.close()
        
        # Limpiar el archivo de imagen temporal
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
        
        # 1. Guardar los bytes del PDF en el modelo de Django
        # Usamos .name para obtener el nombre base sin depender de .path
        output_filename = os.path.basename(document.original_file.name).replace('.pdf', '_signed.pdf')
        document.signed_file.save(output_filename, ContentFile(pdf_bytes), save=True)
        
        # 2. Actualizar el estado del documento
        document.status = 'signed'
        document.save()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Firma aplicada correctamente.',
            'download_url': document.signed_file.url,
            'document_status': document.status
        })

    except Exception as e:
        logger.error(f"ERROR EN api_save_signature: {e}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@login_required
@require_POST
def api_rasterize_document(request, pk):
    try:
        document = get_object_or_404(Document, pk=pk, owner=request.user)
        
        if not document.signed_file:
            return JsonResponse({'status': 'error', 'message': 'El documento no tiene un archivo firmado para aplanar.'}, status=400)
        
        # Nombre del archivo basado en el nombre original disponible
        rasterized_filename = os.path.basename(document.signed_file.name).replace('.pdf', '_final.pdf')
        
        # Usamos un stream en memoria para el resultado
        import io
        output_buffer = io.BytesIO()
        
        # Llama a la función que hace el trabajo pesado pasandole el stream
        with document.signed_file.open('rb') as f:
            rasterize_pdf(f, output_buffer)
        
        # Guarda el nuevo archivo rasterizado en el modelo
        output_buffer.seek(0)
        document.signed_file.save(rasterized_filename, ContentFile(output_buffer.read()), save=True)
            
        # --- Actualizar el estado del documento a 'flattened' ---
        document.status = 'flattened'
        document.save()
            
        return JsonResponse({
            'status': 'success',
            'message': 'Documento rasterizado exitosamente.',
            'download_url': document.signed_file.url,
            'document_status': document.status
        })
    
    except Exception as e:
        logger.error(f"ERROR EN api_rasterize_document: {e}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    
# --- Nueva vista para aplanar el PDF original ---
@login_required
@require_POST
def api_flatten_original(request, pk):
    try:
        document = get_object_or_404(Document, pk=pk, owner=request.user)
        
        # El nombre del archivo de salida
        output_filename = os.path.basename(document.original_file.name).replace('.pdf', '_flattened.pdf')
        
        # Usamos un stream en memoria para el resultado
        import io
        output_buffer = io.BytesIO()
        
        # Llama a la función de rasterización usando streams
        with document.original_file.open('rb') as f:
            rasterize_pdf(f, output_buffer)
        
        # Guarda el nuevo archivo aplanado en el modelo
        output_buffer.seek(0)
        document.signed_file.save(output_filename, ContentFile(output_buffer.read()), save=True)
            
        # Actualiza el estado del documento
        document.status = 'flattened_original'
        document.save()
            
        return JsonResponse({
            'status': 'success',
            'message': 'Documento original aplanado exitosamente.',
            'download_url': document.signed_file.url,
            'document_status': document.status
        })
    
    except Exception as e:
        logger.error(f"ERROR EN api_flatten_original: {e}", exc_info=True)
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def download_signed_document(request, pk):
    """
    Proxy de descarga: sirve el archivo firmado desde Django con
    Content-Disposition: attachment para forzar la descarga incluso
    cuando el archivo está en un CDN/MinIO cross-origin.
    """
    document = get_object_or_404(Document, pk=pk, owner=request.user)

    if not document.signed_file:
        raise Http404("Este documento no tiene un archivo firmado.")

    try:
        filename = os.path.basename(document.signed_file.name)
        with document.signed_file.open('rb') as f:
            response = HttpResponse(f.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
    except Exception as e:
        logger.error(f"Error en proxy de descarga: {e}")
        raise Http404("Archivo no encontrado.")


@login_required
def login_redirect_view(request):
    if request.user.is_staff:
        return redirect('admin:index')
    else:
        return redirect('dashboard')


@login_required
@require_POST
def delete_document(request, pk):
    try:
        document = get_object_or_404(Document, pk=pk, owner=request.user)
        # Eliminación lógica (Soft Delete)
        document.is_active = False
        document.save()
        return JsonResponse({'status': 'success', 'message': 'Documento eliminado correctamente.'})
    except Exception as e:
        logger.error(f"Error al eliminar documento: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def api_signature_proxy(request):
    """
    Sirve la firma del usuario desde el backend para evitar problemas de CORS.
    """
    signature = get_object_or_404(Signature, user=request.user)
    try:
        with signature.image.open('rb') as f:
            return HttpResponse(f.read(), content_type="image/png")
    except Exception as e:
        logger.error(f"Error en proxy de firma: {e}")
        raise Http404("Archivo de firma no encontrado")

@login_required
def api_document_proxy(request, pk):
    """
    Sirve el documento original desde el backend para evitar problemas de CORS en el editor.
    """
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    try:
        with document.original_file.open('rb') as f:
            return HttpResponse(f.read(), content_type="application/pdf")
    except Exception as e:
        logger.error(f"Error en proxy de documento: {e}")
        raise Http404("Archivo de documento no encontrado")
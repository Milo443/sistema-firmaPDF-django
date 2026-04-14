import json
import fitz
import tempfile
import os
import traceback
import logging

# Inicializar logger
logger = logging.getLogger('core')

from PIL import Image
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect , get_object_or_404 
from django.contrib.auth.decorators import login_required
from django.contrib import messages

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
    user_documents = Document.objects.filter(owner=request.user).order_by('-created_at')
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
        #solo formato png
        form = SignatureForm(request.POST, request.FILES, instance=user_signature)
        if form.is_valid():
            signature = form.save(commit=False)
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
            x_ratio = pdf_width / data['page_width']
            y_ratio = pdf_height / data['page_height']
            x = data['x'] * x_ratio
            y = data['y'] * y_ratio
            width = data['width'] * x_ratio
            height = data['height'] * y_ratio
            signature_rect = fitz.Rect(x, y, x + width, y + height)
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
        # Opcional: Eliminar archivos físicos del almacenamiento si se desea
        # Con django-storages S3, esto llamará al borrado en el bucket
        if document.original_file:
            document.original_file.delete(save=False)
        if document.signed_file:
            document.signed_file.delete(save=False)
            
        document.delete()
        return JsonResponse({'status': 'success', 'message': 'Documento eliminado correctamente.'})
    except Exception as e:
        logger.error(f"Error al eliminar documento: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
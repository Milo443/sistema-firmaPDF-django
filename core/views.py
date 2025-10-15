import json
import fitz
import tempfile
import os
import traceback

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

# --- Funciones auxiliares (fuera de las vistas) ---
def rasterize_pdf(input_path, output_path, dpi=200):
    """
    Rasteriza un PDF convirtiendo cada página en una imagen y creando un nuevo PDF.
    
    Args:
        input_path (str): Ruta al archivo PDF de entrada.
        output_path (str): Ruta para guardar el PDF rasterizado.
        dpi (int): Resolución de las imágenes (puntos por pulgada).
    """
    try:
        source_doc = fitz.open(input_path)
        output_doc = fitz.open()
        
        for page in source_doc:
            pix = page.get_pixmap(dpi=dpi)
            new_page = output_doc.new_page(width=pix.width, height=pix.height)
            new_page.insert_image(new_page.rect, pixmap=pix)

        output_doc.save(output_path, garbage=4, deflate=True)
        source_doc.close()
        output_doc.close()
        
    except Exception as e:
        print(f"Error al rasterizar el PDF: {e}")
        raise # Vuelve a lanzar la excepción para que sea capturada por la vista

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
        pdf_doc = fitz.open(document.original_file.path)
        num_pages = pdf_doc.page_count
        pdf_doc.close()
    except Exception as e:
        print(f"Error al leer el PDF: {e}")
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
        img = Image.open(signature.image.path)
        rotated_img = img.rotate(-data['rotation'], expand=True, resample=Image.Resampling.BICUBIC)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            rotated_img.save(temp_img, "PNG")
            temp_image_path = temp_img.name

        # --- Lógica para insertar la firma en el PDF ---
        # Abrir el documento original
        pdf_doc = fitz.open(document.original_file.path)
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
        os.remove(temp_image_path)
        
        # 1. Guardar los bytes del PDF en el modelo de Django
        output_filename = os.path.basename(document.original_file.path).replace('.pdf', '_signed.pdf')
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
        print(f"\n¡¡¡ ERROR EN api_save_signature !!!")
        print(f"Tipo de error: {type(e).__name__}")
        print(f"Mensaje de error: {e}")
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    try:
        data = json.loads(request.body)
        if data['page_width'] == 0 or data['page_height'] == 0:
            return JsonResponse({'status': 'error', 'message': 'Las dimensiones de la página son cero.'}, status=400)

        document = get_object_or_404(Document, pk=pk, owner=request.user)
        signature = get_object_or_404(Signature, user=request.user)
        
        # Lógica de rotación de la firma
        img = Image.open(signature.image.path)
        rotated_img = img.rotate(-data['rotation'], expand=True, resample=Image.Resampling.BICUBIC)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            rotated_img.save(temp_img, "PNG")
            temp_image_path = temp_img.name

        pdf_doc = fitz.open(document.original_file.path)
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
        
        # 1. Guardar los cambios en un nuevo archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_signed_pdf:
            pdf_doc.save(temp_signed_pdf.name, garbage=4, clean=True)
            output_path = temp_signed_pdf.name
        
        # 2. CERRAR el documento de PyMuPDF antes de hacer cualquier otra cosa
        pdf_doc.close()
        
        # Limpiar el archivo de imagen temporal
        os.remove(temp_image_path)
        
        # 3. Guardar el archivo temporal en el modelo de Django
        output_filename = os.path.basename(document.original_file.path).replace('.pdf', '_signed.pdf')
        with open(output_path, 'rb') as f:
            document.signed_file.save(output_filename, ContentFile(f.read()), save=True)
        
        # Actualizar el estado del documento
        document.status = 'signed'
        document.save()
        
        # 4. Eliminar el archivo temporal DESPUÉS de haberlo guardado en el modelo
        os.remove(output_path)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Firma aplicada correctamente.',
            'download_url': document.signed_file.url,
            'document_status': document.status
        })

    except Exception as e:
        print(f"\n¡¡¡ ERROR EN api_save_signature !!!")
        print(f"Tipo de error: {type(e).__name__}")
        print(f"Mensaje de error: {e}")
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@login_required
@require_POST
def api_rasterize_document(request, pk):
    try:
        document = get_object_or_404(Document, pk=pk, owner=request.user)
        
        if not document.signed_file:
            return JsonResponse({'status': 'error', 'message': 'El documento no tiene un archivo firmado para aplanar.'}, status=400)
        
        # Rutas de los archivos
        input_path = document.signed_file.path
        
        # Usamos un nombre de archivo temporal para el PDF rasterizado
        rasterized_filename = os.path.basename(input_path).replace('.pdf', '_final.pdf')
        output_path = os.path.join(os.path.dirname(input_path), rasterized_filename)
        
        # Llama a la función que hace el trabajo pesado
        rasterize_pdf(input_path, output_path)
        
        # Guarda el nuevo archivo rasterizado en el modelo
        with open(output_path, 'rb') as f:
            # Reemplaza el archivo signed_file con el nuevo
            document.signed_file.save(rasterized_filename, ContentFile(f.read()), save=True)
            
        # --- Actualizar el estado del documento a 'flattened' ---
        document.status = 'flattened'
        document.save()
            
        # Limpia el archivo temporal
        os.remove(output_path)

        return JsonResponse({
            'status': 'success',
            'message': 'Documento rasterizado exitosamente.',
            'download_url': document.signed_file.url,
            'document_status': document.status
        })
    
    except Exception as e:
        print(f"\n¡¡¡ ERROR REAL EN api_rasterize_document !!!")
        print(f"Tipo de error: {type(e).__name__}")
        print(f"Mensaje de error: {e}")
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
    
# --- Nueva vista para aplanar el PDF original ---
@login_required
@require_POST
def api_flatten_original(request, pk):
    try:
        document = get_object_or_404(Document, pk=pk, owner=request.user)
        
        # El archivo de entrada es el original_file
        input_path = document.original_file.path
        
        # El nombre del archivo de salida
        output_filename = os.path.basename(input_path).replace('.pdf', '_flattened.pdf')
        output_path = os.path.join(os.path.dirname(input_path), output_filename)
        
        # Llama a la función de rasterización
        rasterize_pdf(input_path, output_path)
        
        # Guarda el nuevo archivo aplanado en el modelo
        with open(output_path, 'rb') as f:
            # Reemplaza el archivo 'signed_file' con el nuevo aplanado
            document.signed_file.save(output_filename, ContentFile(f.read()), save=True)
            
        # Actualiza el estado del documento
        document.status = 'flattened_original'
        document.save()
            
        # Limpia el archivo temporal
        os.remove(output_path)

        return JsonResponse({
            'status': 'success',
            'message': 'Documento original aplanado exitosamente.',
            'download_url': document.signed_file.url,
            'document_status': document.status
        })
    
    except Exception as e:
        print(f"\n¡¡¡ ERROR EN api_flatten_original !!!")
        print(f"Tipo de error: {type(e).__name__}")
        print(f"Mensaje de error: {e}")
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
def login_redirect_view(request):
    if request.user.is_staff:
        return redirect('admin:index')
    else:
        return redirect('dashboard')
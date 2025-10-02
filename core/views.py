
import json
import fitz  # PyMuPDF libreria que maneja la edicion pdf
import tempfile
import os

from PIL import Image
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.files.base import ContentFile
from django.shortcuts import render, redirect , get_object_or_404 
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .models import Document, Signature
from .forms import DocumentForm, SignatureForm

@login_required
def dashboard(request):
    # 2. Busca en la BD solo los documentos que pertenecen al usuario actual
    user_documents = Document.objects.filter(owner=request.user).order_by('-created_at')

    # 3. Pasa la lista de documentos a la plantilla a través del "contexto"
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
            document.save()
            return redirect('dashboard')
    else:
        form = DocumentForm()
    
    context = {'form': form}
    # Esta vista usará la plantilla 'upload_document.html' que ya creamos para Bootstrap 5
    return render(request, 'core/upload_document.html', context)

@login_required
def manage_signature(request):
    try:
        # Intenta obtener la firma que el usuario ya podría tener
        user_signature = Signature.objects.get(user=request.user)
    except Signature.DoesNotExist:
        user_signature = None

    if request.method == 'POST':
        # Si el usuario envía el formulario, actualiza la firma existente o crea una nueva
        form = SignatureForm(request.POST, request.FILES, instance=user_signature)
        if form.is_valid():
            signature = form.save(commit=False)
            signature.user = request.user
            signature.save()
            return redirect('dashboard') # Redirige al dashboard tras guardar
    else:
        # Si solo está visitando la página, muéstrale el formulario
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
        'num_pages': num_pages, # Pasamos el número total de páginas
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
        
        # --- INICIO DE LA LÓGICA DE ROTACIÓN ---

        # 2. Abrir la imagen de la firma con Pillow
        img = Image.open(signature.image.path)
        
        # 3. Rotar la imagen. Pillow rota en sentido antihorario, así que usamos el ángulo negativo.
        #    `expand=True` asegura que la nueva imagen sea lo suficientemente grande para contener la imagen rotada.
        rotated_img = img.rotate(-data['rotation'], expand=True, resample=Image.Resampling.BICUBIC)

        # 4. Guardar esta imagen ya rotada en un archivo temporal
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_img:
            rotated_img.save(temp_img, "PNG")
            temp_image_path = temp_img.name

        # --- FIN DE LA LÓGICA DE ROTACIÓN ---
        
        pdf_doc = fitz.open(document.original_file.path)
        page_index = data['page_number'] - 1
        page = pdf_doc[page_index]
        
        pdf_width = page.rect.width
        pdf_height = page.rect.height
        
        x_ratio = pdf_width / data['page_width']
        y_ratio = pdf_height / data['page_height']

        x = data['x'] * x_ratio
        y = data['y'] * y_ratio
        width = data['width'] * x_ratio
        height = data['height'] * y_ratio

        signature_rect = fitz.Rect(x, y, x + width, y + height)
        
        # 5. Insertar la IMAGEN TEMPORAL (ya rotada) y SIN el parámetro `rotate`
        page.insert_image(signature_rect, filename=temp_image_path)
        
        pdf_bytes = pdf_doc.tobytes(garbage=4, clean=True)
        pdf_doc.close()
        
        # 6. Limpiar el archivo de imagen temporal
        os.remove(temp_image_path)
        
        output_filename = os.path.basename(document.original_file.path).replace('.pdf', '_signed.pdf')
        document.signed_file.save(output_filename, ContentFile(pdf_bytes), save=True)
        
        return JsonResponse({'status': 'success', 'download_url': document.signed_file.url})

    except Exception as e:
        print(f"\n¡¡¡ ERROR REAL EN api_save_signature !!!")
        print(f"Tipo de error: {type(e).__name__}")
        print(f"Mensaje de error: {e}")
        import traceback
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    try:
        # --- DEBUG: Imprimir los datos recibidos del frontend ---
        data = json.loads(request.body)
        print(f"--- DEBUG: Datos recibidos para firmar doc {pk} ---")
        print(data)
        print("-------------------------------------------------")

        document = get_object_or_404(Document, pk=pk, owner=request.user)
        signature = get_object_or_404(Signature, user=request.user)
        
        pdf_doc = fitz.open(document.original_file.path)
        
        # PyMuPDF usa un índice basado en 0, así que restamos 1
        page_index = data['page_number'] - 1

        # --- DEBUG: Verificar el índice y el total de páginas ---
        print(f"Intentando cargar la página con índice {page_index} (Página {data['page_number']})")
        print(f"El documento tiene {pdf_doc.page_count} páginas en total.")
        
        # Cargar la página
        page = pdf_doc[page_index]
        
        # --- Conversión de coordenadas ---
        pdf_width = page.rect.width
        pdf_height = page.rect.height
        
        x_ratio = pdf_width / data['page_width']
        y_ratio = pdf_height / data['page_height']

        x = data['x'] * x_ratio
        y = data['y'] * y_ratio
        width = data['width'] * x_ratio
        height = data['height'] * y_ratio

        signature_rect = fitz.Rect(x, y, x + width, y + height)
        page.insert_image(signature_rect, filename=signature.image.path)
        
        # --- 2. Usar tempfile para un guardado seguro y multiplataforma ---
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
            pdf_doc.save(temp_pdf.name)
            output_path = temp_pdf.name
        
        pdf_doc.close()
        
        # Guardar el archivo temporal en el modelo de Django
        output_filename = os.path.basename(document.original_file.path).replace('.pdf', '_signed.pdf')
        with open(output_path, 'rb') as f:
            document.signed_file.save(output_filename, File(f), save=True)
        
        # Eliminar el archivo temporal
        os.remove(output_path)
        
        return JsonResponse({'status': 'success', 'download_url': document.signed_file.url})

    except Exception as e:
        # --- DEBUG: Imprimir el error real que está ocurriendo ---
        print(f"\n¡¡¡ ERROR REAL EN api_save_signature !!!")
        print(f"Tipo de error: {type(e).__name__}")
        print(f"Mensaje de error: {e}")
        import traceback
        traceback.print_exc() # Imprime el traceback completo en la terminal
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

# core/views.py

@login_required
def login_redirect_view(request):
    """
    Revisa si el usuario es parte del staff (administrador).
    Si lo es, lo redirige al panel de administración.
    Si no, lo redirige al dashboard del sistema de firmas.
    """
    
    # --- INICIO DEL CÓDIGO DE DIAGNÓSTICO ---
    print(f"--- DEBUG: Redirección post-login ---")
    print(f"Usuario que ha iniciado sesión: {request.user.username}")
    print(f"¿Es staff? (request.user.is_staff): {request.user.is_staff}")
    print(f"------------------------------------")
    # --- FIN DEL CÓDIGO DE DIAGNÓSTICO ---

    if request.user.is_staff:
        return redirect('admin:index')
    else:
        return redirect('dashboard')
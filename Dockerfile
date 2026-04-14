# Usa una imagen oficial de Python como base
FROM python:3.12-slim

# Evita que Python genere archivos .pyc y que el buffer se llene en los logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Establece el directorio de trabajo
WORKDIR /app

# Instala dependencias del sistema necesarias para Pillow y PyMuPDF
# En Debian Trixie (base de python:slim actual), libgl1-mesa-glx se reemplazó por libgl1
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Instala gunicorn directamente o vía requirements
RUN pip install --upgrade pip
RUN pip install gunicorn

# Copia los archivos de requerimientos e instala las dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código de la aplicación
COPY . .

# Crea carpetas para archivos estáticos, media y logs
RUN mkdir -p staticfiles media logs

# Expone el puerto que usará Gunicorn
EXPOSE 8000

# Comando para ejecutar la aplicación con configuración optimizada
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--worker-class", "gthread", "--threads", "2", "firma_project.wsgi:application"]

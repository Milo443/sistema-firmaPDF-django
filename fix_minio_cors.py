import boto3
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def set_minio_cors():
    # Obtener credenciales desde el .env
    endpoint = os.getenv('MINIO_ENDPOINT')
    access_key = os.getenv('MINIO_ACCESS_KEY')
    secret_key = os.getenv('MINIO_SECRET_KEY')
    bucket_name = os.getenv('MINIO_STORAGE_BUCKET_NAME', 'sistema-firmas')

    print(f"--- Configurando CORS para MinIO ---")
    print(f"Endpoint: {endpoint}")
    print(f"Bucket: {bucket_name}")

    try:
        # Configurar el cliente S3 (usando el endpoint interno)
        s3 = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            # MinIO usa path-style por defecto en muchas configuraciones
            config=boto3.session.Config(signature_version='s3v4'),
            region_name='us-east-1' # Requerido por S3v4, aunque sea MinIO
        )

        # Definición de la política CORS
        cors_configuration = {
            'CORSRules': [{
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'HEAD'],
                'AllowedOrigins': ['*'], # Cambiar a un dominio específico si se prefiere mayor seguridad
                'MaxAgeSeconds': 3000
            }]
        }

        # Aplicar la política
        s3.put_bucket_cors(Bucket=bucket_name, CORSConfiguration=cors_configuration)
        
        print(f"¡Éxito! CORS configurado correctamente para el bucket '{bucket_name}'.")
        print("Ahora los navegadores podrán cargar las firmas sin bloqueos.")

    except Exception as e:
        print(f"Error configurando CORS: {e}")

if __name__ == "__main__":
    set_minio_cors()

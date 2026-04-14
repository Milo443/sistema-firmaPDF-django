import boto3
import os
import sys
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def set_minio_cors(endpoint=None):
    # Obtener credenciales desde el .env si no se pasan
    access_key = os.getenv('MINIO_ACCESS_KEY')
    secret_key = os.getenv('MINIO_SECRET_KEY')
    bucket_name = os.getenv('MINIO_STORAGE_BUCKET_NAME', 'sistema-firmas')
    
    # Prioridad: argumento > variable .env > default (S3/Public)
    if not endpoint:
        endpoint = os.getenv('MINIO_ENDPOINT', 'https://cdn.vooltlab.com')

    print(f"\n--- Configurando CORS para MinIO ---")
    print(f"Endpoint: {endpoint}")
    print(f"Bucket: {bucket_name}")

    try:
        # Configurar el cliente S3
        s3 = boto3.client(
            's3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=boto3.session.Config(signature_version='s3v4'),
            region_name='us-east-1'
        )

        # Definición de la política CORS robusta
        cors_configuration = {
            'CORSRules': [{
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'HEAD'],
                'AllowedOrigins': [
                    '*', 
                    'https://firma-ing.vooltlab.com', 
                    'http://firma-ing.vooltlab.com'
                ],
                'ExposeHeaders': ['ETag', 'Content-Type', 'Content-Length'],
                'MaxAgeSeconds': 3600
            }]
        }

        # Aplicar la política
        s3.put_bucket_cors(Bucket=bucket_name, CORSConfiguration=cors_configuration)
        
        print(f"¡Éxito! CORS configurado correctamente para el bucket '{bucket_name}'.")
        return True

    except Exception as e:
        print(f"Error configurando CORS en {endpoint}: {e}")
        return False

if __name__ == "__main__":
    # Intentar con el endpoint interno primero (si se corre en docker)
    # y luego con el externo
    internal_endpoint = os.getenv('MINIO_ENDPOINT')
    
    success = False
    if internal_endpoint:
        success = set_minio_cors(internal_endpoint)
    
    if not success:
        # Reintentar con el dominio público
        public_domain = "https://cdn.vooltlab.com"
        print(f"\nReintentando con endpoint público: {public_domain}")
        set_minio_cors(public_domain)

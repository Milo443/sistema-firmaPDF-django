from django.db import models
from django.contrib.auth.models import User

class Signature(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='signatures/')

    def __str__(self):
        return f"Firma de {self.user.username}"

class Document(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    original_file = models.FileField(upload_to='documents/original/')
    signed_file = models.FileField(upload_to='documents/signed/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
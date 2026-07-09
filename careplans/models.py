from django.db import models

class CarePlan(models.Model):
    patient_name = models.CharField(max_length=200)
    medication = models.CharField(max_length=200)
    condition = models.TextField()
    generated_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
from django.db import models

class CarePlan(models.Model):
    patient_name = models.CharField(max_length=200)
    medication = models.CharField(max_length=200)
    condition = models.TextField()
    patient_record = models.TextField(blank=True, default="")
    retrieval_query = models.TextField(blank=True, default="")
    retrieved_chunks = models.JSONField(blank=True, default=list)
    generated_text = models.TextField()
    structured_data = models.JSONField(blank=True, null=True, default=None)
    parse_failed = models.BooleanField(default=False)
    raw_output = models.TextField(blank=True, default="")
    prompt_version = models.CharField(max_length=50, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)

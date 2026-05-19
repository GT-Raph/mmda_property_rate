from django.db.models.signals import post_save
from django.dispatch import receiver

from properties.models import Property
from .models import PropertyCertificate


@receiver(post_save, sender=Property)
def create_property_certificate(sender, instance, created, **kwargs):
    if created:
        PropertyCertificate.objects.get_or_create(property=instance)
# sales/signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Payment, Sale
from decimal import Decimal


@receiver(post_save, sender=Payment)
@receiver(post_delete, sender=Payment)
def update_sale_payment_status(sender, instance, **kwargs):
    """Met à jour le statut de paiement de la vente après modification d'un paiement"""
    try:
        if hasattr(instance, 'invoice') and instance.invoice:
            sale = instance.invoice.sale
            if sale:
                # Calculer le total payé
                total_paid = sale.invoice.payments.filter(
                    status='completed'
                ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')

                # Mettre à jour le statut
                if total_paid >= sale.total:
                    sale.payment_status = 'paid'
                elif total_paid > 0:
                    sale.payment_status = 'partially_paid'
                else:
                    if sale.invoice.due_date < timezone.now().date():
                        sale.payment_status = 'overdue'
                    else:
                        sale.payment_status = 'pending'

                sale.save(update_fields=['payment_status'])
    except Exception as e:
        print(f"Erreur lors de la mise à jour du statut: {e}")

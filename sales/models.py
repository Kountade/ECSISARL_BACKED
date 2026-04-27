from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from users.models import CustomUser
from products.models import Product, ProductVariant
from inventory.models import Warehouse
from decimal import Decimal
from django.utils import timezone


class Customer(models.Model):
    """Client"""
    CUSTOMER_TYPES = (
        ('individual', 'Particulier'),
        ('company', 'Entreprise'),
        ('government', 'Administration'),
        ('reseller', 'Revendeur'),
    )

    PAYMENT_TERMS = (
        ('cash', 'Comptant'),
        ('15_days', '15 jours'),
        ('30_days', '30 jours'),
        ('45_days', '45 jours'),
        ('60_days', '60 jours'),
        ('end_of_month', 'Fin de mois'),
    )

    # Informations de base
    code = models.CharField(max_length=50, unique=True,
                            verbose_name="Code client")
    customer_type = models.CharField(
        max_length=20, choices=CUSTOMER_TYPES, default='individual')
    company_name = models.CharField(
        max_length=200, blank=True, null=True, verbose_name="Raison sociale")

    # Identité
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    mobile = models.CharField(max_length=20, blank=True, null=True)

    # Adresse
    address = models.TextField()
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Sénégal')

    # Numéros d'identification
    registration_number = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="N° RC/RCCM")
    tax_id = models.CharField(
        max_length=50, blank=True, null=True, verbose_name="N° TVA/IFU")

    # Conditions commerciales
    payment_terms = models.CharField(
        max_length=20, choices=PAYMENT_TERMS, default='cash')
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Limite de crédit")
    discount_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0, verbose_name="Remise (%)")

    # Statistiques
    total_orders = models.IntegerField(
        default=0, verbose_name="Total commandes")
    total_spent = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Total dépensé")
    total_invoices = models.IntegerField(
        default=0, verbose_name="Total factures")
    total_paid = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Total payé")
    outstanding_balance = models.DecimalField(
        max_digits=15, decimal_places=2, default=0, verbose_name="Solde dû")

    # Options
    is_active = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    blocking_reason = models.TextField(blank=True, null=True)

    # Métadonnées
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_customers')
    updated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='updated_customers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name', 'company_name']
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['email']),
            models.Index(fields=['phone']),
        ]

    def __str__(self):
        if self.company_name:
            return f"{self.code} - {self.company_name}"
        return f"{self.code} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        if self.company_name:
            return self.company_name
        return f"{self.first_name} {self.last_name}".strip()


class CustomerAddress(models.Model):
    """Adresses multiples pour un client"""
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name='addresses')

    address_type = models.CharField(max_length=20, choices=[
        ('billing', 'Facturation'),
        ('shipping', 'Livraison'),
        ('both', 'Les deux'),
    ], default='both')

    address = models.TextField()
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Sénégal')

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_default', 'address_type']

    def __str__(self):
        return f"{self.customer.full_name} - {self.get_address_type_display()}"


class Sale(models.Model):
    """Vente / Commande client"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('confirmed', 'Confirmée'),
        ('in_preparation', 'En préparation'),
        ('shipped', 'Expédiée'),
        ('delivered', 'Livrée'),
        ('partially_delivered', 'Partiellement livrée'),
        ('cancelled', 'Annulée'),
        ('returned', 'Retournée'),
    )

    PAYMENT_STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('partially_paid', 'Partiellement payé'),
        ('paid', 'Payé'),
        ('overdue', 'En retard'),
        ('refunded', 'Remboursé'),
    )

    # Références
    sale_number = models.CharField(max_length=50, unique=True)
    external_reference = models.CharField(
        max_length=100, blank=True, null=True)

    # Relations
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='sales')
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='sales')
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_sales')
    validated_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='validated_sales')

    # Dates
    sale_date = models.DateField(auto_now_add=True)
    delivery_date = models.DateField(
        null=True, blank=True, verbose_name="Date de livraison")
    shipped_date = models.DateField(null=True, blank=True)
    delivered_date = models.DateField(null=True, blank=True)

    # Statuts
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')

    # Montants
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default='XOF')

    # Livraison
    shipping_address = models.TextField(blank=True)
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    carrier = models.CharField(max_length=100, blank=True, null=True)

    # Notes
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    terms_conditions = models.TextField(blank=True, null=True)

    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sale_date', '-sale_number']
        indexes = [
            models.Index(fields=['sale_number']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['sale_date']),
        ]

    def __str__(self):
        return f"SO-{self.sale_number} - {self.customer.full_name}"

    def save(self, *args, **kwargs):
        if not self.sale_number:
            last_sale = Sale.objects.order_by('-id').first()
            if last_sale:
                last_num = int(last_sale.sale_number.replace('SO', ''))
                self.sale_number = f"SO{str(last_num + 1).zfill(6)}"
            else:
                self.sale_number = "SO000001"
        super().save(*args, **kwargs)

    def calculate_totals(self):
        """Calcule les totaux de la vente"""
        self.subtotal = sum(item.subtotal for item in self.items.all())
        self.tax_total = sum(item.tax_amount for item in self.items.all())
        self.total = self.subtotal - self.discount + self.shipping_cost + self.tax_total
        self.save()

    def update_payment_status(self):
        """Met à jour le statut de paiement"""
        total_paid = self.payments.aggregate(
            total=models.Sum('amount'))['total'] or 0

        if total_paid >= self.total:
            self.payment_status = 'paid'
        elif total_paid > 0:
            self.payment_status = 'partially_paid'
        else:
            # Vérifier si la date d'échéance est dépassée
            if self.invoice and self.invoice.due_date < timezone.now().date():
                self.payment_status = 'overdue'
            else:
                self.payment_status = 'pending'
        self.save()


class SaleItem(models.Model):
    """Lignes de vente"""
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name='items')

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    quantity_delivered = models.IntegerField(default=0)
    quantity_returned = models.IntegerField(default=0)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    total = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)

    notes = models.CharField(max_length=200, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.sale.sale_number} - {self.product.name}"

    def save(self, *args, **kwargs):
        qty = Decimal(self.quantity)
        unit_price = self.unit_price
        disc_rate = self.discount_rate
        tax_rate = self.tax_rate

        discount_factor = (Decimal('100') - disc_rate) / Decimal('100')
        tax_factor = tax_rate / Decimal('100')

        self.subtotal = qty * unit_price * discount_factor
        self.tax_amount = self.subtotal * tax_factor
        self.total = self.subtotal + self.tax_amount

        super().save(*args, **kwargs)

    @property
    def remaining_quantity(self):
        """Quantité restant à livrer"""
        return self.quantity - self.quantity_delivered


class Delivery(models.Model):
    """Livraison"""
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('in_transit', 'En transit'),
        ('delivered', 'Livrée'),
        ('partial', 'Partielle'),
        ('cancelled', 'Annulée'),
    )

    delivery_number = models.CharField(max_length=50, unique=True)
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name='deliveries')

    delivery_date = models.DateField(auto_now_add=True)
    delivered_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='deliveries')

    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    carrier = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending')

    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-delivery_date']

    def __str__(self):
        return f"DEL-{self.delivery_number}"


class DeliveryItem(models.Model):
    """Lignes de livraison"""
    delivery = models.ForeignKey(
        Delivery, on_delete=models.CASCADE, related_name='items')
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    lot_number = models.CharField(max_length=100, blank=True, null=True)
    serial_numbers = models.JSONField(default=list, blank=True)

    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Mettre à jour la quantité livrée
        sale_item = self.sale_item
        sale_item.quantity_delivered += self.quantity
        sale_item.save()


class Quotation(models.Model):
    """Devis"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyé'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('expired', 'Expiré'),
        ('converted', 'Converti en vente'),
    )

    quotation_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='quotations')
    created_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_quotations')

    quotation_date = models.DateField(auto_now_add=True)
    valid_until = models.DateField()

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default='XOF')

    notes = models.TextField(blank=True, null=True)
    terms_conditions = models.TextField(blank=True, null=True)

    converted_sale = models.ForeignKey(
        Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name='quotation')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-quotation_date']

    def __str__(self):
        return f"QT-{self.quotation_number} - {self.customer.full_name}"

    def save(self, *args, **kwargs):
        if not self.quotation_number:
            last = Quotation.objects.order_by('-id').first()
            if last:
                last_num = int(last.quotation_number.replace('QT', ''))
                self.quotation_number = f"QT{str(last_num + 1).zfill(6)}"
            else:
                self.quotation_number = "QT000001"
        super().save(*args, **kwargs)


class QuotationItem(models.Model):
    """Lignes de devis"""
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name='items')

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(
        ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=20)

    subtotal = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)
    total = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False)

    notes = models.CharField(max_length=200, blank=True, null=True)

    def save(self, *args, **kwargs):
        qty = Decimal(self.quantity)
        unit_price = self.unit_price
        disc_rate = self.discount_rate
        tax_rate = self.tax_rate

        discount_factor = (Decimal('100') - disc_rate) / Decimal('100')
        tax_factor = tax_rate / Decimal('100')

        self.subtotal = qty * unit_price * discount_factor
        self.tax_amount = self.subtotal * tax_factor
        self.total = self.subtotal + self.tax_amount

        super().save(*args, **kwargs)


class Invoice(models.Model):
    """Facture"""
    STATUS_CHOICES = (
        ('draft', 'Brouillon'),
        ('sent', 'Envoyée'),
        ('paid', 'Payée'),
        ('partially_paid', 'Partiellement payée'),
        ('overdue', 'En retard'),
        ('cancelled', 'Annulée'),
    )

    invoice_number = models.CharField(max_length=50, unique=True)
    sale = models.OneToOneField(
        Sale, on_delete=models.CASCADE, related_name='invoice')

    invoice_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft')

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    remaining_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)

    currency = models.CharField(max_length=10, default='XOF')

    notes = models.TextField(blank=True, null=True)
    pdf_file = models.FileField(upload_to='invoices/', null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date']

    def __str__(self):
        return f"INV-{self.invoice_number}"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            last = Invoice.objects.order_by('-id').first()
            if last:
                last_num = int(last.invoice_number.replace('INV', ''))
                self.invoice_number = f"INV{str(last_num + 1).zfill(6)}"
            else:
                self.invoice_number = "INV000001"

        self.remaining_amount = self.total - self.paid_amount

        # Mettre à jour le statut
        if self.paid_amount >= self.total:
            self.status = 'paid'
        elif self.paid_amount > 0:
            self.status = 'partially_paid'
        elif self.due_date < timezone.now().date():
            self.status = 'overdue'

        super().save(*args, **kwargs)


class Payment(models.Model):
    """Paiement"""
    PAYMENT_METHODS = (
        ('cash', 'Espèces'),
        ('card', 'Carte bancaire'),
        ('check', 'Chèque'),
        ('transfer', 'Virement'),
        ('mobile_money', 'Mobile Money'),
        ('other', 'Autre'),
    )

    PAYMENT_STATUS = (
        ('pending', 'En attente'),
        ('completed', 'Complété'),
        ('failed', 'Échoué'),
        ('refunded', 'Remboursé'),
    )

    payment_number = models.CharField(max_length=50, unique=True)
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='payments')
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='payments')

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_date = models.DateField(auto_now_add=True)

    reference = models.CharField(max_length=100, blank=True, null=True,
                                 help_text="Référence du paiement (numéro de chèque, de virement, etc.)")
    status = models.CharField(
        max_length=20, choices=PAYMENT_STATUS, default='completed')

    notes = models.TextField(blank=True, null=True)
    received_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, related_name='received_payments')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date']

    def __str__(self):
        return f"PAY-{self.payment_number} - {self.amount}"

    def save(self, *args, **kwargs):
        if not self.payment_number:
            last = Payment.objects.order_by('-id').first()
            if last:
                last_num = int(last.payment_number.replace('PAY', ''))
                self.payment_number = f"PAY{str(last_num + 1).zfill(6)}"
            else:
                self.payment_number = "PAY000001"

        super().save(*args, **kwargs)

        # Mettre à jour le montant payé de la facture
        self.invoice.paid_amount = self.invoice.payments.filter(
            status='completed').aggregate(total=models.Sum('amount'))['total'] or 0
        self.invoice.save()

        # Mettre à jour le statut de paiement de la vente
        if self.invoice.sale:
            self.invoice.sale.update_payment_status()


class Return(models.Model):
    """Retour client"""
    REASON_CHOICES = (
        ('defective', 'Produit défectueux'),
        ('wrong_product', 'Produit erroné'),
        ('damaged', 'Endommagé pendant le transport'),
        ('change_mind', 'Changement d\'avis'),
        ('other', 'Autre'),
    )

    return_number = models.CharField(max_length=50, unique=True)
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name='returns')
    customer = models.ForeignKey(
        Customer, on_delete=models.PROTECT, related_name='returns')

    return_date = models.DateField(auto_now_add=True)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)

    status = models.CharField(max_length=20, choices=[
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('completed', 'Terminé'),
    ], default='pending')

    refund_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    restocking_fee = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)
    net_refund = models.DecimalField(
        max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(blank=True, null=True)
    approved_by = models.ForeignKey(
        CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_returns')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-return_date']

    def __str__(self):
        return f"RET-{self.return_number}"


class ReturnItem(models.Model):
    """Lignes de retour"""
    return_obj = models.ForeignKey(
        Return, on_delete=models.CASCADE, related_name='items')
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE)

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    reason = models.CharField(max_length=200, blank=True, null=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Mettre à jour la quantité retournée
        sale_item = self.sale_item
        sale_item.quantity_returned += self.quantity
        sale_item.save()

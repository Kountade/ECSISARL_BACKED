# sales/serializers.py - Version CORRIGÉE (supprimer les doublons)
from products.models import Product
from decimal import Decimal
from django.utils import timezone
from rest_framework import serializers
from .models import *
from products.serializers import ProductListSerializer, ProductVariantSerializer
from users.serializers import UserSerializer
from inventory.serializers import WarehouseSerializer

from products.models import Product   # Ajoutez cet import en haut du fichier


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = '__all__'


class CustomerListSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    customer_type_display = serializers.CharField(
        source='get_customer_type_display', read_only=True)
    outstanding_balance = serializers.DecimalField(
        max_digits=15, decimal_places=2, read_only=True)

    class Meta:
        model = Customer
        fields = ('id', 'code', 'full_name', 'customer_type', 'customer_type_display',
                  'email', 'phone', 'city', 'country', 'total_orders',
                  'total_spent', 'outstanding_balance', 'is_active', 'credit_limit')

    def get_full_name(self, obj):
        return obj.full_name


class CustomerDetailSerializer(serializers.ModelSerializer):
    addresses = CustomerAddressSerializer(many=True, read_only=True)
    customer_type_display = serializers.CharField(
        source='get_customer_type_display', read_only=True)
    payment_terms_display = serializers.CharField(
        source='get_payment_terms_display', read_only=True)

    class Meta:
        model = Customer
        fields = '__all__'


class CustomerCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at', 'created_by', 'updated_by',
                            'total_orders', 'total_spent', 'total_invoices',
                            'total_paid', 'outstanding_balance')


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    remaining = serializers.IntegerField(
        source='remaining_quantity', read_only=True)

    class Meta:
        model = SaleItem
        fields = '__all__'
        read_only_fields = ('subtotal', 'tax_amount',
                            'total', 'created_at', 'sale')


class SaleListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source='customer.full_name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    payment_status_display = serializers.CharField(
        source='get_payment_status_display', read_only=True)
    items_count = serializers.IntegerField(
        source='items.count', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)
    warehouse_id = serializers.IntegerField(
        source='warehouse.id', read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = ('id', 'sale_number', 'customer_name', 'sale_date', 'delivery_date',
                  'status', 'status_display', 'payment_status', 'payment_status_display',
                  'total', 'items_count', 'warehouse_id', 'warehouse_name', 'items')

    def get_items(self, obj):
        return [
            {
                'id': item.id,
                'product': item.product.id,
                'product_name': item.product.name,
                'product_reference': item.product.reference,
                'quantity': item.quantity,
                'quantity_delivered': item.quantity_delivered,
                'unit_price': item.unit_price,
                'total': item.total,
                'remaining_quantity': item.remaining_quantity
            }
            for item in obj.items.all()
        ]


class SaleDetailSerializer(serializers.ModelSerializer):
    customer = CustomerListSerializer(read_only=True)
    warehouse = WarehouseSerializer(read_only=True)
    items = SaleItemSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)
    validated_by = UserSerializer(read_only=True)
    deliveries = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    returns = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = '__all__'

    def get_deliveries(self, obj):
        return DeliverySerializer(obj.deliveries.all(), many=True).data

    def get_invoice(self, obj):
        if hasattr(obj, 'invoice'):
            return InvoiceSerializer(obj.invoice).data
        return None

    def get_payments(self, obj):
        if hasattr(obj, 'invoice') and obj.invoice:
            return PaymentSerializer(obj.invoice.payments.all(), many=True).data
        return []

    def get_returns(self, obj):
        return ReturnSerializer(obj.returns.all(), many=True).data

# sales/serializers.py (modification de SaleCreateUpdateSerializer)


class SaleCreateUpdateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )

    class Meta:
        model = Sale
        fields = [
            'customer', 'warehouse', 'delivery_date', 'shipping_address',
            'notes', 'internal_notes', 'terms_conditions',
            'discount_rate', 'shipping_cost', 'price_type', 'items'
        ]
        read_only_fields = ('sale_number', 'created_by', 'validated_by',
                            'created_at', 'updated_at', 'sale_date', 'status',
                            'payment_status', 'subtotal', 'tax_total', 'total')

    def validate(self, data):
        if not data.get('customer'):
            raise serializers.ValidationError(
                {'customer': 'Le client est obligatoire'})
        if not data.get('warehouse'):
            raise serializers.ValidationError(
                {'warehouse': 'L\'entrepôt est obligatoire'})
        items = data.get('items', [])
        if not items:
            raise serializers.ValidationError(
                {'items': 'Au moins un produit est requis'})
        for idx, item in enumerate(items):
            if not item.get('product'):
                raise serializers.ValidationError(
                    {'items': f'Ligne {idx+1} : produit manquant'})
            if item.get('quantity', 0) <= 0:
                raise serializers.ValidationError(
                    {'items': f'Ligne {idx+1} : quantité invalide'})
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        customer = validated_data.pop('customer')      # instance Customer
        warehouse = validated_data.pop('warehouse')   # instance Warehouse

        sale = Sale.objects.create(
            customer=customer, warehouse=warehouse, **validated_data)
        sale.created_by = self.context['request'].user
        sale.save()

        price_type = validated_data.get('price_type', 'retail')
        for item_data in items_data:
            # ← récupération de l’instance
            product = Product.objects.get(id=item_data['product'])
            quantity = item_data['quantity']
            if price_type == 'wholesale':
                unit_price = product.wholesale_price or product.sale_price
            else:
                unit_price = product.sale_price

            SaleItem.objects.create(
                sale=sale,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                discount_rate=0,
                tax_rate=20
            )
        sale.calculate_totals()
        return sale

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items_data is not None:
            instance.items.all().delete()
            price_type = validated_data.get('price_type', instance.price_type)
            for item_data in items_data:
                product = Product.objects.get(id=item_data['product'])
                quantity = item_data['quantity']
                if price_type == 'wholesale':
                    unit_price = product.wholesale_price or product.sale_price
                else:
                    unit_price = product.sale_price
                SaleItem.objects.create(
                    sale=instance,
                    product=product,
                    quantity=quantity,
                    unit_price=unit_price
                )
            instance.calculate_totals()
        return instance


class DeliveryItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source='sale_item.product.name', read_only=True)
    product_reference = serializers.CharField(
        source='sale_item.product.reference', read_only=True)

    class Meta:
        model = DeliveryItem
        fields = '__all__'


class DeliverySerializer(serializers.ModelSerializer):
    items = DeliveryItemSerializer(many=True, read_only=True)
    delivered_by_name = serializers.CharField(
        source='delivered_by.email', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Delivery
        fields = '__all__'
        read_only_fields = ('delivery_number', 'created_at')


class DeliveryCreateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )

    class Meta:
        model = Delivery
        fields = ['sale', 'tracking_number', 'carrier', 'notes', 'items']
        read_only_fields = ('delivery_number', 'created_at', 'delivered_by')

    def validate_sale(self, value):
        if isinstance(value, Sale):
            sale_id = value.id
        else:
            sale_id = value

        try:
            sale = Sale.objects.get(id=sale_id)
            if sale.status not in ['confirmed', 'in_preparation']:
                raise serializers.ValidationError(
                    "Cette vente ne peut pas être livrée"
                )
            return sale
        except Sale.DoesNotExist:
            raise serializers.ValidationError("Vente non trouvée")

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Au moins un article est requis")

        for idx, item in enumerate(value):
            if 'sale_item' not in item:
                raise serializers.ValidationError({
                    f'items[{idx}]': "Le champ 'sale_item' est requis"
                })
            if 'quantity' not in item:
                raise serializers.ValidationError({
                    f'items[{idx}]': "Le champ 'quantity' est requis"
                })

            quantity = item.get('quantity', 0)
            if quantity <= 0:
                raise serializers.ValidationError({
                    f'items[{idx}]': "La quantité doit être supérieure à 0"
                })

            try:
                sale_item = SaleItem.objects.get(id=item['sale_item'])
                item['sale_item_obj'] = sale_item

                if sale_item.remaining_quantity < quantity:
                    raise serializers.ValidationError({
                        f'items[{idx}]': f"Quantité ({quantity}) dépasse le reste à livrer ({sale_item.remaining_quantity})"
                    })
            except SaleItem.DoesNotExist:
                raise serializers.ValidationError({
                    f'items[{idx}]': "Ligne de vente introuvable"
                })

        return value

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        sale = validated_data.pop('sale')

        last_delivery = Delivery.objects.order_by('-id').first()
        if last_delivery:
            try:
                last_num = int(
                    last_delivery.delivery_number.replace('DEL', ''))
                delivery_number = f"DEL{str(last_num + 1).zfill(6)}"
            except (ValueError, AttributeError):
                delivery_number = "DEL000001"
        else:
            delivery_number = "DEL000001"

        delivery = Delivery.objects.create(
            delivery_number=delivery_number,
            sale=sale,
            tracking_number=validated_data.get('tracking_number', ''),
            carrier=validated_data.get('carrier', ''),
            notes=validated_data.get('notes', ''),
            delivered_by=self.context['request'].user
        )

        for item_data in items_data:
            sale_item = item_data.pop('sale_item_obj')
            DeliveryItem.objects.create(
                delivery=delivery,
                sale_item=sale_item,
                quantity=item_data['quantity'],
                lot_number=item_data.get('lot_number', ''),
                serial_numbers=item_data.get('serial_numbers', []),
                notes=item_data.get('notes', '')
            )

            sale_item.quantity_delivered += item_data['quantity']
            sale_item.save()

        all_delivered = all(
            item.remaining_quantity == 0 for item in sale.items.all()
        )
        if all_delivered:
            sale.status = 'delivered'
            sale.delivered_date = timezone.now().date()
            sale.save()

        return delivery


class QuotationItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_reference = serializers.CharField(
        source='product.reference', read_only=True)
    warehouse_name = serializers.CharField(
        source='warehouse.name', read_only=True)

    class Meta:
        model = QuotationItem
        fields = '__all__'
        read_only_fields = ('subtotal', 'tax_amount', 'total', 'quotation')


class QuotationListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source='customer.full_name', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    items_count = serializers.IntegerField(
        source='items.count', read_only=True)
    items = serializers.SerializerMethodField()  # Ajouter cette ligne

    class Meta:
        model = Quotation
        fields = ('id', 'quotation_number', 'customer_name', 'quotation_date',
                  'valid_until', 'status', 'status_display', 'total',
                  'items_count', 'items')  # Ajouter 'items' ici

    def get_items(self, obj):
        """Récupérer les items du devis"""
        return [
            {
                'id': item.id,
                'product_name': item.product.name,
                'product_reference': item.product.reference,
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total': float(item.total),
                'product': item.product.id
            }
            for item in obj.items.all()
        ]


class QuotationDetailSerializer(serializers.ModelSerializer):
    customer = CustomerListSerializer(read_only=True)
    items = QuotationItemSerializer(many=True, read_only=True)
    created_by = UserSerializer(read_only=True)
    subtotal = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True)
    tax_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True)
    total = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Quotation
        fields = '__all__'


class QuotationCreateUpdateSerializer(serializers.ModelSerializer):
    items = QuotationItemSerializer(many=True)

    class Meta:
        model = Quotation
        fields = ['customer', 'valid_until',
                  'notes', 'terms_conditions', 'items']
        # Enlever 'created_by' d'ici
        read_only_fields = ('quotation_number', 'quotation_date', 'status')

    def validate(self, data):
        if not data.get('customer'):
            raise serializers.ValidationError({
                'customer': 'Le client est obligatoire'
            })
        if not data.get('items'):
            raise serializers.ValidationError({
                'items': 'Au moins un produit est requis'
            })
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        # NE PAS passer created_by ici car il sera ajouté dans le viewset
        quotation = Quotation.objects.create(**validated_data)

        # created_by sera ajouté par le viewset via perform_create
        # donc on ne le met pas ici

        for item_data in items_data:
            QuotationItem.objects.create(quotation=quotation, **item_data)

        quotation.save()
        return quotation


# ========== SERIALIZERS POUR FACTURES ==========

class InvoiceSerializer(serializers.ModelSerializer):
    sale_number = serializers.CharField(
        source='sale.sale_number', read_only=True)
    customer_name = serializers.CharField(
        source='sale.customer.full_name', read_only=True)
    customer_id = serializers.IntegerField(
        source='sale.customer.id', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = '__all__'

    def get_items(self, obj):
        if obj.sale:
            return [
                {
                    'id': item.id,
                    'product': item.product.id,
                    'product_name': item.product.name,
                    'product_reference': item.product.reference,
                    'quantity': item.quantity,
                    'unit_price': float(item.unit_price),
                    'total': float(item.total)
                }
                for item in obj.sale.items.all()
            ]
        return []


class InvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ['sale', 'due_date', 'notes']
        read_only_fields = ('invoice_number', 'invoice_date', 'status',
                            'subtotal', 'discount', 'tax_total', 'total',
                            'paid_amount', 'remaining_amount', 'created_at', 'updated_at')

    def validate_sale(self, value):
        if isinstance(value, Sale):
            sale_id = value.id
        else:
            sale_id = value

        try:
            sale = Sale.objects.get(id=sale_id)
            if hasattr(sale, 'invoice'):
                raise serializers.ValidationError(
                    "Cette vente a déjà une facture")
            return sale
        except Sale.DoesNotExist:
            raise serializers.ValidationError("Vente non trouvée")

    def create(self, validated_data):
        sale = validated_data.pop('sale')

        invoice = Invoice.objects.create(
            sale=sale,
            due_date=validated_data.get('due_date'),
            notes=validated_data.get('notes', ''),
            subtotal=sale.subtotal,
            discount=sale.discount,
            tax_total=sale.tax_total,
            total=sale.total
        )

        return invoice


# ========== SERIALIZERS POUR PAIEMENTS ==========

class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(
        source='invoice.invoice_number', read_only=True)
    customer_name = serializers.CharField(
        source='customer.full_name', read_only=True)
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)
    received_by_name = serializers.CharField(
        source='received_by.email', read_only=True)

    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('payment_number', 'created_at')


# sales/serializers.py - CORRECTION du PaymentCreateSerializer

# sales/serializers.py - Modifiez le PaymentCreateSerializer

class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['invoice', 'amount', 'payment_method', 'reference', 'notes']
        read_only_fields = ('payment_number', 'payment_date',
                            'status', 'received_by', 'customer')

    def validate(self, data):
        invoice = data.get('invoice')
        amount = data.get('amount', 0)

        if invoice and amount > invoice.remaining_amount:
            raise serializers.ValidationError({
                'amount': f"Le montant dépasse le reste à payer ({invoice.remaining_amount})"
            })

        return data

    def create(self, validated_data):
        invoice = validated_data.pop('invoice')

        payment = Payment.objects.create(
            invoice=invoice,
            customer=invoice.sale.customer,
            **validated_data
        )

        # Mettre à jour le montant payé de la facture
        total_paid = invoice.payments.filter(
            status='completed'
        ).aggregate(total=models.Sum('amount'))['total'] or 0

        invoice.paid_amount = total_paid
        invoice.save()

        # === CORRECTION ICI ===
        # Mettre à jour le statut de paiement de la vente
        sale = invoice.sale
        sale.payment_status = self._get_payment_status(sale, total_paid)
        sale.save(update_fields=['payment_status'])

        return payment

    def _get_payment_status(self, sale, total_paid):
        """Calcule le statut de paiement"""
        if total_paid >= sale.total:
            return 'paid'
        elif total_paid > 0:
            return 'partially_paid'
        else:
            if sale.invoice and sale.invoice.due_date < timezone.now().date():
                return 'overdue'
            return 'pending'
# ========== SERIALIZERS POUR RETOURS ==========


class ReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(
        source='sale_item.product.name', read_only=True)
    product_reference = serializers.CharField(
        source='sale_item.product.reference', read_only=True)

    class Meta:
        model = ReturnItem
        fields = '__all__'


class ReturnSerializer(serializers.ModelSerializer):
    items = ReturnItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(
        source='customer.full_name', read_only=True)
    sale_number = serializers.CharField(
        source='sale.sale_number', read_only=True)
    reason_display = serializers.CharField(
        source='get_reason_display', read_only=True)
    status_display = serializers.CharField(
        source='get_status_display', read_only=True)

    class Meta:
        model = Return
        fields = '__all__'
        read_only_fields = ('return_number', 'created_at')


class ReturnCreateSerializer(serializers.ModelSerializer):
    items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )

    class Meta:
        model = Return
        fields = ['sale', 'reason', 'notes', 'items']
        read_only_fields = ('return_number', 'created_at')

    def validate(self, data):
        sale = data.get('sale')
        if sale and sale.status not in ['delivered', 'partially_delivered']:
            raise serializers.ValidationError({
                'sale': 'Seules les ventes livrées peuvent être retournées'
            })
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        sale = validated_data.get('sale')

        last_return = Return.objects.order_by('-id').first()
        if last_return:
            try:
                last_num = int(last_return.return_number.replace('RET', ''))
                return_number = f"RET{str(last_num + 1).zfill(6)}"
            except (ValueError, AttributeError):
                return_number = "RET000001"
        else:
            return_number = "RET000001"

        return_obj = Return.objects.create(
            return_number=return_number,
            customer=sale.customer,
            **validated_data
        )

        total_refund = 0
        for item_data in items_data:
            sale_item = SaleItem.objects.get(id=item_data['sale_item'])
            quantity = item_data['quantity']

            ReturnItem.objects.create(
                return_obj=return_obj,
                sale_item=sale_item,
                quantity=quantity,
                reason=item_data.get('reason', '')
            )

            total_refund += sale_item.unit_price * quantity
            sale_item.quantity_returned += quantity
            sale_item.save()

        return_obj.refund_amount = total_refund
        return_obj.restocking_fee = total_refund * \
            Decimal('0.10') if total_refund > 0 else 0
        return_obj.net_refund = return_obj.refund_amount - return_obj.restocking_fee
        return_obj.save()

        return return_obj


class SaleStatsSerializer(serializers.Serializer):
    total_sales = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    average_order_value = serializers.DecimalField(
        max_digits=10, decimal_places=2)
    pending_payments = serializers.IntegerField()
    pending_deliveries = serializers.IntegerField()
    top_customers = serializers.ListField(child=serializers.DictField())
    monthly_revenue = serializers.ListField(child=serializers.DictField())
    top_products = serializers.ListField(child=serializers.DictField())

from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from .serializers import *
from .models import *
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from django.db.models import Q, Sum, Count, Avg, F
from django.utils import timezone
from datetime import timedelta
from inventory.models import StockMovement


class CustomerViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les clients
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Customer.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['customer_type',
                        'is_active', 'is_blocked', 'city', 'country']
    search_fields = ['code', 'first_name',
                     'last_name', 'company_name', 'email', 'phone']
    ordering_fields = ['code', 'total_spent', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return CustomerListSerializer
        elif self.action == 'retrieve':
            return CustomerDetailSerializer
        return CustomerCreateUpdateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=['get'])
    def sales(self, request, pk=None):
        customer = self.get_object()
        sales = customer.sales.all()
        serializer = SaleListSerializer(
            sales, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def invoices(self, request, pk=None):
        customer = self.get_object()
        invoices = Invoice.objects.filter(sale__customer=customer)
        serializer = InvoiceSerializer(invoices, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def top_customers(self, request):
        customers = self.get_queryset().filter(
            is_active=True,
            total_spent__gt=0
        ).order_by('-total_spent')[:10]
        serializer = CustomerListSerializer(customers, many=True)
        return Response(serializer.data)


class SaleViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les ventes
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Sale.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['customer', 'status',
                        'payment_status', 'warehouse', 'sale_date']
    search_fields = ['sale_number', 'customer__first_name', 'customer__last_name',
                     'customer__company_name', 'customer__email']
    ordering_fields = ['sale_date', 'delivery_date', 'total', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return SaleListSerializer
        elif self.action == 'retrieve':
            return SaleDetailSerializer
        return SaleCreateUpdateSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)

        payment_status = self.request.query_params.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        customer = self.request.query_params.get('customer')
        if customer:
            queryset = queryset.filter(customer_id=customer)

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            queryset = queryset.filter(sale_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(sale_date__lte=end_date)

        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirmer une vente"""
        sale = self.get_object()
        if sale.status != 'draft':
            return Response({"error": "Vente déjà confirmée"}, status=status.HTTP_400_BAD_REQUEST)

        # Vérifier le stock
        for item in sale.items.all():
            if item.product.stock_quantity < item.quantity:
                return Response({
                    "error": f"Stock insuffisant pour {item.product.name}. "
                    f"Disponible: {item.product.stock_quantity}"
                }, status=status.HTTP_400_BAD_REQUEST)

        sale.status = 'confirmed'
        sale.validated_by = request.user
        sale.save()

        # Déduire le stock
        for item in sale.items.all():
            StockMovement.objects.create(
                movement_type='out',
                reference_type='sale',
                reference_id=sale.id,
                product=item.product,
                variant=item.variant,
                quantity=item.quantity,
                from_warehouse=sale.warehouse,
                unit_price=item.unit_price,
                total_price=item.unit_price * item.quantity,
                notes=f"Vente {sale.sale_number} - {item.product.name}",
                created_by=request.user
            )

        return Response({"status": "sale confirmed"})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler une vente"""
        sale = self.get_object()
        if sale.status in ['delivered', 'cancelled']:
            return Response({"error": "Vente déjà terminée ou annulée"},
                            status=status.HTTP_400_BAD_REQUEST)

        sale.status = 'cancelled'
        sale.save()

        return Response({"status": "sale cancelled"})

    @action(detail=False, methods=['get'])
    def pending_payments(self, request):
        """Ventes avec paiements en attente"""
        sales = self.get_queryset().filter(
            payment_status__in=['pending', 'partially_paid']
        )
        serializer = SaleListSerializer(sales, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def pending_deliveries(self, request):
        """Ventes en attente de livraison"""
        sales = self.get_queryset().filter(
            status__in=['confirmed', 'in_preparation']
        )
        serializer = SaleListSerializer(sales, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Statistiques des ventes"""
        total_sales = Sale.objects.count()
        total_amount = Sale.objects.filter(
            status='delivered'
        ).aggregate(total=Sum('total'))['total'] or 0

        pending_payments = Sale.objects.filter(
            payment_status__in=['pending', 'partially_paid']
        ).count()

        pending_deliveries = Sale.objects.filter(
            status__in=['confirmed', 'in_preparation']
        ).count()

        # Top clients
        top_customers = Customer.objects.annotate(
            total_spent=Sum('sales__total', filter=Q(
                sales__status='delivered'))
        ).filter(total_spent__isnull=False).order_by('-total_spent')[:5]

        # Revenus mensuels
        six_months_ago = timezone.now().date() - timedelta(days=180)
        monthly_revenue = Sale.objects.filter(
            sale_date__gte=six_months_ago,
            status='delivered'
        ).extra(
            select={'month': "strftime('%Y-%m', sale_date)"}
        ).values('month').annotate(
            total=Sum('total')
        ).order_by('month')

        # Top produits
        top_products = SaleItem.objects.values(
            'product__name', 'product__reference'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total')
        ).order_by('-total_quantity')[:10]

        return Response({
            'total_sales': total_sales,
            'total_amount': total_amount,
            'average_order_value': total_amount / total_sales if total_sales else 0,
            'pending_payments': pending_payments,
            'pending_deliveries': pending_deliveries,
            'top_customers': [
                {'id': c.id, 'name': c.full_name,
                    'total_spent': float(c.total_spent)}
                for c in top_customers
            ],
            'monthly_revenue': list(monthly_revenue),
            'top_products': list(top_products)
        })


class QuotationViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les devis
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Quotation.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['customer', 'status']
    search_fields = ['quotation_number',
                     'customer__first_name', 'customer__last_name']
    ordering_fields = ['quotation_date', 'valid_until', 'total']

    def get_serializer_class(self):
        if self.action == 'list':
            return QuotationListSerializer
        elif self.action == 'retrieve':
            return QuotationDetailSerializer
        return QuotationCreateUpdateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Envoyer un devis"""
        quotation = self.get_object()
        if quotation.status != 'draft':
            return Response({"error": "Devis déjà envoyé"}, status=status.HTTP_400_BAD_REQUEST)

        quotation.status = 'sent'
        quotation.save()

        return Response({"status": "quotation sent"})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approuver un devis"""
        quotation = self.get_object()
        if quotation.status != 'sent':
            return Response({"error": "Devis non envoyé"}, status=status.HTTP_400_BAD_REQUEST)

        quotation.status = 'approved'
        quotation.save()

        return Response({"status": "quotation approved"})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Rejeter un devis"""
        quotation = self.get_object()
        quotation.status = 'rejected'
        quotation.save()

        return Response({"status": "quotation rejected"})

    @action(detail=True, methods=['post'])
    def convert_to_sale(self, request, pk=None):
        """Convertir un devis en vente"""
        quotation = self.get_object()

        if quotation.status != 'approved':
            return Response({"error": "Le devis doit être approuvé"},
                            status=status.HTTP_400_BAD_REQUEST)

        warehouse_id = request.data.get('warehouse')
        if not warehouse_id:
            return Response({"error": "L'entrepôt est obligatoire"},
                            status=status.HTTP_400_BAD_REQUEST)

        from inventory.models import Warehouse
        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({"error": "Entrepôt non trouvé"}, status=status.HTTP_400_BAD_REQUEST)

        # Créer la vente
        sale = Sale.objects.create(
            customer=quotation.customer,
            warehouse=warehouse,
            shipping_address=request.data.get('shipping_address', ''),
            notes=f"Converti depuis devis {quotation.quotation_number}",
            created_by=request.user
        )

        # Copier les articles
        for quote_item in quotation.items.all():
            SaleItem.objects.create(
                sale=sale,
                product=quote_item.product,
                variant=quote_item.variant,
                quantity=quote_item.quantity,
                unit_price=quote_item.unit_price,
                discount_rate=quote_item.discount_rate,
                tax_rate=quote_item.tax_rate
            )

        sale.calculate_totals()
        sale.save()

        quotation.status = 'converted'
        quotation.converted_sale = sale
        quotation.save()

        return Response({
            'status': 'converted',
            'sale_id': sale.id,
            'sale_number': sale.sale_number
        })


class InvoiceViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les factures
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Invoice.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'sale__sale_number', 'sale__customer__first_name',
                     'sale__customer__last_name', 'sale__customer__company_name']
    ordering_fields = ['invoice_date', 'due_date', 'total']

    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceCreateSerializer
        return InvoiceSerializer

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Envoyer une facture"""
        invoice = self.get_object()
        if invoice.status != 'draft':
            return Response({"error": "Facture déjà envoyée"}, status=status.HTTP_400_BAD_REQUEST)

        invoice.status = 'sent'
        invoice.save()

        return Response({"status": "invoice sent"})


class PaymentViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les paiements
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Payment.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['payment_method', 'status', 'payment_date']
    search_fields = ['payment_number', 'reference', 'invoice__invoice_number',
                     'customer__first_name', 'customer__last_name', 'customer__company_name']
    ordering_fields = ['payment_date', 'amount']

    def get_serializer_class(self):
        if self.action == 'create':
            return PaymentCreateSerializer
        return PaymentSerializer

    def perform_create(self, serializer):
        serializer.save(received_by=self.request.user)


class DeliveryViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les livraisons
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Delivery.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['sale', 'status']
    search_fields = ['delivery_number', 'tracking_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return DeliveryCreateSerializer
        return DeliverySerializer

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Démarrer la livraison (mettre en transit)"""
        delivery = self.get_object()
        if delivery.status != 'pending':
            return Response({"error": "Livraison déjà en cours"},
                            status=status.HTTP_400_BAD_REQUEST)

        delivery.status = 'in_transit'
        delivery.save()

        # Mettre à jour le statut de la vente
        sale = delivery.sale
        if sale.status == 'confirmed':
            sale.status = 'in_preparation'
            sale.save()

        return Response({"status": "delivery started"})

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirmer une livraison"""
        delivery = self.get_object()
        if delivery.status != 'in_transit':
            return Response({"error": "Livraison non en transit"},
                            status=status.HTTP_400_BAD_REQUEST)

        delivery.status = 'delivered'
        delivery.save()

        # Vérifier si la vente est complètement livrée
        sale = delivery.sale
        all_delivered = all(
            item.remaining_quantity == 0 for item in sale.items.all()
        )
        if all_delivered:
            sale.status = 'delivered'
            sale.delivered_date = timezone.now().date()
            sale.save()
        else:
            sale.status = 'partially_delivered'
            sale.save()

        return Response({"status": "delivery confirmed"})


class ReturnViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les retours
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Return.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['sale', 'customer', 'status', 'reason']
    search_fields = ['return_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return ReturnCreateSerializer
        return ReturnSerializer

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approuver un retour"""
        return_obj = self.get_object()
        if return_obj.status != 'pending':
            return Response({"error": "Retour déjà traité"},
                            status=status.HTTP_400_BAD_REQUEST)

        return_obj.status = 'approved'
        return_obj.approved_by = request.user
        return_obj.save()

        # Réintégrer le stock
        for item in return_obj.items.all():
            StockMovement.objects.create(
                movement_type='return_customer',
                reference_type='sale',
                reference_id=return_obj.sale.id,
                product=item.sale_item.product,
                variant=item.sale_item.variant,
                quantity=item.quantity,
                to_warehouse=return_obj.sale.warehouse,
                unit_price=item.sale_item.unit_price,
                total_price=item.sale_item.unit_price * item.quantity,
                notes=f"Retour client #{return_obj.return_number}",
                created_by=request.user
            )

        return Response({"status": "return approved"})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Rejeter un retour"""
        return_obj = self.get_object()
        if return_obj.status != 'pending':
            return Response({"error": "Retour déjà traité"},
                            status=status.HTTP_400_BAD_REQUEST)

        return_obj.status = 'rejected'
        return_obj.save()

        return Response({"status": "return rejected"})

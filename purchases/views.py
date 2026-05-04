from .serializers import (
    PurchaseOrderListSerializer,
    PurchaseOrderDetailSerializer,
    PurchaseOrderCreateUpdateSerializer,
    PurchaseReceiptCreateSerializer,
    PurchaseReceiptSerializer
)
from .models import PurchaseOrder, Supplier
from django.db.models.functions import TruncMonth
from django.db.models import Q, Sum
from django.shortcuts import render

# Create your views here.
# purchases/views.py
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
import csv
import pandas as pd
import io


class SupplierViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les fournisseurs
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Supplier.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['supplier_type', 'is_preferred',
                        'is_active', 'rating', 'country']
    search_fields = ['code', 'company_name', 'contact_name', 'email', 'city']
    ordering_fields = ['company_name', 'rating', 'total_orders', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return SupplierListSerializer
        elif self.action == 'retrieve':
            return SupplierDetailSerializer
        return SupplierCreateUpdateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=['get'])
    def orders(self, request, pk=None):
        supplier = self.get_object()
        orders = supplier.purchase_orders.all()
        serializer = PurchaseOrderListSerializer(
            orders, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        supplier = self.get_object()
        products = Product.objects.filter(
            purchase_orders__supplier=supplier
        ).distinct()
        from products.serializers import ProductListSerializer
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def price_history(self, request, pk=None):
        supplier = self.get_object()
        prices = PurchasePriceHistory.objects.filter(supplier=supplier)
        serializer = PurchasePriceHistorySerializer(prices, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def evaluate(self, request, pk=None):
        supplier = self.get_object()
        serializer = SupplierEvaluationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(supplier=supplier, evaluator=request.user)
            evaluations = supplier.evaluations.all()
            if evaluations.exists():
                total_score = sum(e.total_score for e in evaluations)
                supplier.rating = total_score / evaluations.count()
                supplier.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def top_suppliers(self, request):
        suppliers = self.get_queryset().filter(
            is_active=True,
            rating__isnull=False
        ).order_by('-rating')[:10]
        serializer = SupplierListSerializer(suppliers, many=True)
        return Response(serializer.data)


class SupplierContactViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = SupplierContact.objects.all()
    serializer_class = SupplierContactSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['supplier', 'is_primary', 'is_active']
    search_fields = ['first_name', 'last_name', 'email']


# purchases/views.py (ou purchase_orders/views.py)


class PurchaseOrderViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = PurchaseOrder.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['supplier', 'status', 'urgency', 'order_date']
    search_fields = ['order_number',
                     'supplier__company_name', 'supplier_reference']
    ordering_fields = ['order_date', 'expected_date', 'total', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseOrderListSerializer
        elif self.action == 'retrieve':
            return PurchaseOrderDetailSerializer
        return PurchaseOrderCreateUpdateSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        supplier = self.request.query_params.get('supplier')
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            queryset = queryset.filter(order_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(order_date__lte=end_date)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        order = self.get_object()
        if order.status != 'draft':
            return Response({"error": "Commande déjà envoyée"}, status=status.HTTP_400_BAD_REQUEST)
        order.status = 'sent'
        order.save()
        return Response({"status": "order sent"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        order = self.get_object()
        if order.status not in ['sent', 'draft']:
            return Response({"error": "Impossible de confirmer"}, status=status.HTTP_400_BAD_REQUEST)
        order.status = 'confirmed'
        order.confirmed_date = timezone.now().date()
        order.validated_by = request.user
        order.save()
        return Response({"status": "order confirmed"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        order = self.get_object()
        if order.status not in ['confirmed', 'in_transit', 'partially_received']:
            return Response({"error": "Commande non réceptionnable"}, status=status.HTTP_400_BAD_REQUEST)

        items_data = request.data.get('items', [])
        receipt_data = {
            'purchase_order': order.id,
            'notes': request.data.get('notes', ''),
            'items': items_data
        }
        receipt_serializer = PurchaseReceiptCreateSerializer(
            data=receipt_data,
            context={'request': request}
        )
        if receipt_serializer.is_valid():
            receipt = receipt_serializer.save(received_by=request.user)
            return Response(PurchaseReceiptSerializer(receipt).data, status=status.HTTP_201_CREATED)
        return Response(receipt_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status in ['received', 'cancelled']:
            return Response({"error": "Commande déjà terminée ou annulée"}, status=status.HTTP_400_BAD_REQUEST)
        order.status = 'cancelled'
        order.save()
        return Response({"status": "order cancelled"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def pending_delivery(self, request):
        orders = self.get_queryset().filter(
            status__in=['confirmed', 'in_transit'],
            expected_date__lt=timezone.now().date()
        )
        serializer = PurchaseOrderListSerializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        total_orders = PurchaseOrder.objects.count()
        total_amount = PurchaseOrder.objects.filter(
            status='received'
        ).aggregate(total=Sum('total'))['total'] or 0
        pending_orders = PurchaseOrder.objects.filter(
            status__in=['confirmed', 'in_transit']
        ).count()
        late_orders = PurchaseOrder.objects.filter(
            status__in=['confirmed', 'in_transit'],
            expected_date__lt=timezone.now().date()
        ).count()

        # Top fournisseurs – annotation sans conflit
        top_suppliers = Supplier.objects.annotate(
            total_spent_calc=Sum('purchase_orders__total', filter=Q(
                purchase_orders__status='received'))
        ).filter(total_spent_calc__isnull=False).order_by('-total_spent_calc')[:5]

        # Dépenses mensuelles avec TruncMonth
        six_months_ago = timezone.now().date() - timedelta(days=180)
        monthly_spending = PurchaseOrder.objects.filter(
            order_date__gte=six_months_ago,
            status='received'
        ).annotate(
            month=TruncMonth('order_date')
        ).values('month').annotate(
            total=Sum('total')
        ).order_by('month')

        monthly_data = [
            {
                'month': item['month'].strftime('%Y-%m') if item['month'] else None,
                'total': float(item['total']) if item['total'] else 0
            }
            for item in monthly_spending
        ]

        return Response({
            'total_orders': total_orders,
            'total_amount': total_amount,
            'average_order_value': total_amount / total_orders if total_orders else 0,
            'pending_orders': pending_orders,
            'late_orders': late_orders,
            'top_suppliers': [
                {'name': s.company_name,
                    'total_spent': float(s.total_spent_calc)}
                for s in top_suppliers
            ],
            'monthly_spending': monthly_data
        })

# purchases/views.py - VÉRIFICATION


class PurchaseReceiptViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = PurchaseReceipt.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['purchase_order', 'receipt_date']
    search_fields = ['receipt_number']

    def get_serializer_class(self):
        if self.action == 'create':
            return PurchaseReceiptCreateSerializer
        elif self.action == 'retrieve':
            return PurchaseReceiptSerializer
        return PurchaseReceiptSerializer

    @action(detail=False, methods=['get'])
    def available_orders(self, request):
        """Retourne les commandes réceptionnables avec leurs items"""
        orders = PurchaseOrder.objects.filter(
            status__in=['confirmed', 'in_transit', 'partially_received']
        ).select_related('supplier').prefetch_related(
            'items',
            'items__product'
        )

        serializer = PurchaseOrderListSerializer(
            orders,
            many=True,
            context={'request': request}
        )
        return Response(serializer.data)

    def perform_create(self, serializer):
        serializer.save(received_by=self.request.user)


class PurchasePriceHistoryViewset(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = PurchasePriceHistory.objects.all()
    serializer_class = PurchasePriceHistorySerializer
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['product', 'supplier']
    ordering_fields = ['date', 'price']


class SupplierCatalogViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = SupplierCatalog.objects.all()
    serializer_class = SupplierCatalogSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['supplier', 'status', 'file_format']

    @action(detail=False, methods=['post'])
    def import_catalog(self, request):
        serializer = SupplierCatalogImportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        file = data['file']
        supplier_id = data['supplier']
        try:
            supplier = Supplier.objects.get(id=supplier_id)
        except Supplier.DoesNotExist:
            return Response({"error": "Fournisseur non trouvé"}, status=status.HTTP_404_NOT_FOUND)
        catalog = SupplierCatalog.objects.create(
            supplier=supplier,
            name=data['name'],
            description=data.get('description', ''),
            file=file,
            file_format=data['file_format'],
            imported_by=request.user,
            status='processing'
        )
        try:
            imported = 0
            if data['file_format'] == 'csv':
                decoded_file = file.read().decode('utf-8')
                reader = csv.DictReader(io.StringIO(decoded_file))
                for row in reader:
                    imported += 1
            elif data['file_format'] == 'excel':
                df = pd.read_excel(file)
                imported = len(df)
            catalog.status = 'completed'
            catalog.products_imported = imported
            catalog.save()
            return Response({
                'status': 'success',
                'imported': imported,
                'catalog_id': catalog.id
            }, status=status.HTTP_200_OK)
        except Exception as e:
            catalog.status = 'failed'
            catalog.error_log = str(e)
            catalog.save()
            return Response({
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# purchases/views.py – Classe PurchaseAlertViewset complète

class PurchaseAlertViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les alertes d'achat
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = PurchaseAlert.objects.filter(is_active=True)
    serializer_class = PurchaseAlertSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['alert_type', 'product', 'supplier']

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Marquer une alerte comme résolue"""
        alert = self.get_object()
        alert.is_active = False
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user
        alert.save()
        return Response({"status": "resolved"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def check_reorders(self, request):
        """Vérifie les stocks et crée des alertes de réapprovisionnement"""
        from products.models import Product
        alerts_created = []
        products = Product.objects.filter(
            stock_quantity__lte=F('minimum_stock'),
            is_active=True
        )
        for product in products:
            if not PurchaseAlert.objects.filter(
                product=product,
                alert_type='reorder',
                is_active=True
            ).exists():
                suggested_qty = None
                if product.maximum_stock and product.maximum_stock > product.stock_quantity:
                    suggested_qty = product.maximum_stock - product.stock_quantity
                alert = PurchaseAlert.objects.create(
                    product=product,
                    alert_type='reorder',
                    current_stock=product.stock_quantity,
                    reorder_point=product.minimum_stock,
                    suggested_quantity=suggested_qty,
                    message=f"Stock faible pour {product.name} ({product.reference}). "
                    f"Actuel: {product.stock_quantity}, Seuil: {product.minimum_stock}"
                )
                alerts_created.append(alert.id)
        return Response({
            'alerts_created': len(alerts_created),
            'products_checked': products.count()
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def check_delivery_delays(self, request):
        """
        Vérifie les commandes non réceptionnées dont la date prévue est dépassée
        et crée des alertes de type 'delivery_delay'
        """
        from .models import PurchaseOrder
        alerts_created = []
        today = timezone.now().date()
        # Commandes en retard : non reçues, non annulées, date prévue < aujourd'hui
        delayed_orders = PurchaseOrder.objects.filter(
            expected_date__lt=today,
            status__in=['confirmed', 'in_transit', 'partially_received']
        )
        for order in delayed_orders:
            # Vérifier si une alerte active existe déjà pour cette commande
            existing = PurchaseAlert.objects.filter(
                alert_type='delivery_delay',
                is_active=True,
                message__icontains=order.order_number
            ).exists()
            if not existing:
                alert = PurchaseAlert.objects.create(
                    product=None,               # pas de produit spécifique
                    supplier=order.supplier,
                    alert_type='delivery_delay',
                    current_stock=0,
                    reorder_point=0,
                    suggested_quantity=None,
                    message=f"Retard de livraison pour la commande {order.order_number}. "
                    f"Date prévue: {order.expected_date}. Fournisseur: {order.supplier.company_name}"
                )
                alerts_created.append(alert.id)
        return Response({
            'alerts_created': len(alerts_created),
            'orders_checked': delayed_orders.count()
        }, status=status.HTTP_200_OK)

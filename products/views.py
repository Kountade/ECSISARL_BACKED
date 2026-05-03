from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from .serializers import *
from .models import *
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from django.db.models import Q, F, Sum, Count
from django.utils import timezone
from rest_framework.parsers import MultiPartParser, FormParser

# Import sécurisé de inventory
try:
    from inventory.models import Warehouse, StockMovement
    INVENTORY_AVAILABLE = True
except ImportError:
    INVENTORY_AVAILABLE = False
    Warehouse = None
    StockMovement = None


class CategoryViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Category.objects.all()
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_active', 'parent']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CategoryDetailSerializer
        return CategorySerializer


class BrandViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        brand = self.get_object()
        products = brand.products.filter(is_active=True)
        page = self.paginate_queryset(products)
        if page:
            serializer = ProductListSerializer(
                page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)


class UnitViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Unit.objects.all()
    serializer_class = UnitSerializer


class ProductViewset(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'brand', 'is_active', 'product_type']
    search_fields = ['reference', 'barcode', 'name', 'description']
    ordering_fields = ['created_at', 'name', 'sale_price', 'stock_quantity']

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        elif self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductCreateUpdateSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_queryset(self):
        queryset = super().get_queryset()
        warehouse_id = self.request.query_params.get('warehouse_id')
        if warehouse_id and INVENTORY_AVAILABLE:
            try:
                Warehouse.objects.get(id=warehouse_id)
                # On filtre les produits ayant du stock global (simplifié)
                queryset = queryset.filter(stock_quantity__gt=0)
            except Warehouse.DoesNotExist:
                queryset = queryset.none()
        return queryset

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        products = self.get_queryset().filter(stock_quantity__lte=F('minimum_stock'))
        serializer = ProductStockAlertSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def out_of_stock(self, request):
        products = self.get_queryset().filter(stock_quantity=0)
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def wholesale_products(self, request):
        products = self.get_queryset().filter(
            wholesale_price__isnull=False, wholesale_price__gt=0)
        serializer = ProductListSerializer(
            products, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stock_movements(self, request, pk=None):
        if not INVENTORY_AVAILABLE:
            return Response({'detail': 'Module inventory non disponible'}, status=status.HTTP_501_NOT_IMPLEMENTED)
        product = self.get_object()
        movements = StockMovement.objects.filter(
            product=product).order_by('-created_at')[:50]
        from inventory.serializers import StockMovementSerializer
        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def check_availability(self, request, pk=None):
        """Endpoint robuste (ne plante pas si inventory manque)"""
        product = self.get_object()
        warehouse_id = request.query_params.get('warehouse_id')
        quantity = int(request.query_params.get('quantity', 1))

        if not warehouse_id:
            return Response({'error': 'Paramètre warehouse_id requis'}, status=status.HTTP_400_BAD_REQUEST)

        # Si inventory non dispo, on utilise le stock global
        if not INVENTORY_AVAILABLE:
            return Response({
                'product_id': product.id,
                'product_name': product.name,
                'warehouse_id': int(warehouse_id),
                'warehouse_name': 'Entrepôt inconnu',
                'requested_quantity': quantity,
                'available_quantity': product.stock_quantity,
                'available': product.stock_quantity >= quantity
            })

        try:
            warehouse = Warehouse.objects.get(id=warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({'error': 'Entrepôt non trouvé'}, status=status.HTTP_404_NOT_FOUND)

        # Calcul du stock réel dans cet entrepôt à partir des mouvements
        stock_in = StockMovement.objects.filter(
            product=product, to_warehouse=warehouse, movement_type='in'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        stock_out = StockMovement.objects.filter(
            product=product, from_warehouse=warehouse, movement_type='out'
        ).aggregate(total=Sum('quantity'))['total'] or 0
        disponible = stock_in - stock_out

        return Response({
            'product_id': product.id,
            'product_name': product.name,
            'warehouse_id': warehouse.id,
            'warehouse_name': warehouse.name,
            'requested_quantity': quantity,
            'available_quantity': disponible,
            'available': disponible >= quantity
        })


class ProductVariantViewset(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer
    parser_classes = [MultiPartParser, FormParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'is_active']
    search_fields = ['sku']

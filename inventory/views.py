from rest_framework.exceptions import ValidationError  # Important pour l'erreur
from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from rest_framework import viewsets, permissions, status, filters
from .serializers import *
from .models import *
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.decorators import action
from django.db.models import Q, F, Sum, Count
from django.utils import timezone
from datetime import timedelta


class WarehouseViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les entrepôts
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Warehouse.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse_type', 'is_active', 'is_default']
    search_fields = ['code', 'name', 'city', 'address']
    ordering_fields = ['code', 'name', 'created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return WarehouseDetailSerializer
        return WarehouseSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['get'])
    def stock(self, request, pk=None):
        """Retourne le stock de l'entrepôt"""
        warehouse = self.get_object()
        movements = StockMovement.objects.filter(
            Q(from_warehouse=warehouse) | Q(to_warehouse=warehouse)
        ).select_related('product')

        # Calculer le stock par produit
        stock_data = {}
        for movement in movements:
            product_id = movement.product.id
            if product_id not in stock_data:
                stock_data[product_id] = {
                    'product': movement.product,
                    'quantity': 0
                }

            if movement.to_warehouse == warehouse:
                stock_data[product_id]['quantity'] += movement.quantity
            if movement.from_warehouse == warehouse:
                stock_data[product_id]['quantity'] -= movement.quantity

        result = [
            {
                'product_id': data['product'].id,
                'product_name': data['product'].name,
                'product_reference': data['product'].reference,
                'quantity': data['quantity']
            }
            for data in stock_data.values()
            if data['quantity'] != 0
        ]

        return Response(result)

    @action(detail=True, methods=['get'])
    def locations(self, request, pk=None):
        """Retourne les emplacements de l'entrepôt"""
        warehouse = self.get_object()
        locations = warehouse.locations.filter(is_active=True)
        serializer = LocationSerializer(locations, many=True)
        return Response(serializer.data)


class LocationViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les emplacements
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Location.objects.all()
    serializer_class = LocationSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['warehouse', 'is_active']
    search_fields = ['code', 'aisle', 'description']

# inventory/views.py
# inventory/views.py - Correction complète du StockMovementViewset

# inventory/views.py - Correction du StockMovementViewset


class StockMovementViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les mouvements de stock
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = StockMovement.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['movement_type', 'reference_type', 'product',
                        'from_warehouse', 'to_warehouse']
    search_fields = ['reference', 'product__name',
                     'product__reference', 'notes']
    ordering_fields = ['movement_date', 'quantity', 'total_price']

    def get_serializer_class(self):
        if self.action == 'list':
            return StockMovementListSerializer
        elif self.action == 'retrieve':
            return StockMovementDetailSerializer
        return StockMovementCreateSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(movement_date__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(movement_date__date__lte=end_date)

        return queryset

    def perform_create(self, serializer):
        """
        Met à jour le stock du produit après création du mouvement
        """
        # ✅ Récupérer les données validées
        validated_data = serializer.validated_data
        movement_type = validated_data.get('movement_type')
        product = validated_data.get('product')
        quantity = validated_data.get('quantity', 0)
        from_warehouse = validated_data.get('from_warehouse')
        to_warehouse = validated_data.get('to_warehouse')

        # ✅ Pour les transferts, s'assurer que la quantité est POSITIVE
        if movement_type == 'transfer' and quantity < 0:
            validated_data['quantity'] = abs(quantity)
            quantity = abs(quantity)

        # Sauvegarder le mouvement
        movement = serializer.save(created_by=self.request.user)

        # Mettre à jour le stock en fonction du type de mouvement
        try:
            if movement.movement_type == 'in':
                product.stock_quantity += movement.quantity

            elif movement.movement_type == 'out':
                if product.stock_quantity >= movement.quantity:
                    product.stock_quantity -= movement.quantity
                else:
                    movement.delete()
                    raise ValidationError({
                        'quantity': f"Stock insuffisant. Disponible: {product.stock_quantity}"
                    })

            elif movement.movement_type == 'transfer':
                # ✅ Pour un transfert, le stock global ne change PAS
                # car c'est juste un déplacement d'un entrepôt à un autre
                # On ne modifie PAS product.stock_quantity
                # Mais on s'assure que la quantité est POSITIVE
                pass

            elif movement.movement_type == 'adjustment':
                product.stock_quantity = movement.quantity

            elif movement.movement_type == 'return':
                product.stock_quantity += movement.quantity

            elif movement.movement_type == 'return_customer':
                product.stock_quantity += movement.quantity

            elif movement.movement_type == 'scrap':
                if product.stock_quantity >= movement.quantity:
                    product.stock_quantity -= movement.quantity
                else:
                    movement.delete()
                    raise ValidationError({
                        'quantity': f"Stock insuffisant pour mise au rebut. Disponible: {product.stock_quantity}"
                    })

            elif movement.movement_type == 'quarantine':
                if product.stock_quantity >= movement.quantity:
                    product.stock_quantity -= movement.quantity
                else:
                    movement.delete()
                    raise ValidationError({
                        'quantity': f"Stock insuffisant pour mise en quarantaine. Disponible: {product.stock_quantity}"
                    })

            # Sauvegarder le produit
            product.save()

            # Créer une alerte si le stock devient faible
            if product.stock_quantity <= product.minimum_stock:
                StockAlert.objects.create(
                    product=product,
                    warehouse=movement.to_warehouse or movement.from_warehouse,
                    alert_type='low_stock',
                    current_quantity=product.stock_quantity,
                    threshold=product.minimum_stock,
                    message=f"Stock faible pour {product.name}. Actuel: {product.stock_quantity}, Seuil: {product.minimum_stock}"
                )

        except ValidationError as e:
            raise e
        except Exception as e:
            movement.delete()
            raise ValidationError(
                f"Erreur lors de la mise à jour du stock: {str(e)}")


class TransferViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les transferts entre entrepôts
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Transfer.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['from_warehouse', 'to_warehouse', 'status']
    search_fields = ['reference', 'waybill', 'notes']
    ordering_fields = ['created_at', 'transfer_date', 'expected_date']

    def get_serializer_class(self):
        if self.action == 'list':
            return TransferListSerializer
        elif self.action == 'retrieve':
            return TransferDetailSerializer
        return TransferCreateSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def get_warehouse_stock(self, product, warehouse):
        """
        Calcule le stock d'un produit dans un entrepôt spécifique
        """
        # Entrées dans l'entrepôt
        stock_in = StockMovement.objects.filter(
            product=product,
            to_warehouse=warehouse
        ).aggregate(total=Sum('quantity'))['total'] or 0

        # Sorties de l'entrepôt
        stock_out = StockMovement.objects.filter(
            product=product,
            from_warehouse=warehouse
        ).aggregate(total=Sum('quantity'))['total'] or 0

        return stock_in - stock_out

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Démarrer un transfert (passer en transit)"""
        transfer = self.get_object()

        if transfer.status not in ['draft', 'pending']:
            return Response(
                {"error": f"Le transfert ne peut pas être démarré. Statut actuel: {transfer.get_status_display()}"},
                status=400
            )

        # Vérifier le stock disponible dans l'entrepôt source pour chaque article
        for item in transfer.items.all():
            stock_disponible = self.get_warehouse_stock(
                item.product,
                transfer.from_warehouse
            )

            if stock_disponible < item.quantity:
                return Response({
                    "error": f"Stock insuffisant dans l'entrepôt source pour {item.product.name}. "
                    f"Disponible: {stock_disponible}, Demandé: {item.quantity}"
                }, status=400)

        # Si le statut est 'draft', le passer d'abord en 'pending'
        if transfer.status == 'draft':
            transfer.status = 'pending'
            transfer.save()

        # Puis passer en 'in_transit'
        transfer.status = 'in_transit'
        transfer.save()

        # Créer les mouvements de stock (sortie de l'entrepôt source)
        for item in transfer.items.all():
            # ✅ Sortie de l'entrepôt source (quantité NEGATIVE dans le mouvement)
            StockMovement.objects.create(
                movement_type='transfer',
                reference_type='transfer',
                reference_id=transfer.id,
                product=item.product,
                variant=item.variant,
                quantity=item.quantity,  # Quantité positive pour la sortie
                from_warehouse=transfer.from_warehouse,
                to_warehouse=None,  # Pas de destination pour la sortie
                unit_price=item.unit_price,
                notes=f"Transfert {transfer.reference} - Départ",
                created_by=request.user
            )

        return Response({
            "status": "transfer started",
            "message": f"Le transfert {transfer.reference} a été démarré avec succès"
        })

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        """Réceptionner un transfert"""
        transfer = self.get_object()
        if transfer.status not in ['in_transit', 'partial']:
            return Response(
                {"error": f"Le transfert ne peut pas être réceptionné. Statut actuel: {transfer.get_status_display()}"},
                status=400
            )

        items_data = request.data.get('items', [])

        if not items_data:
            return Response(
                {"error": "Aucun article à réceptionner"},
                status=400
            )

        for item_data in items_data:
            item_id = item_data.get('id')
            quantity_received = item_data.get('quantity_received', 0)

            if quantity_received <= 0:
                continue

            try:
                item = transfer.items.get(id=item_id)

                if quantity_received > item.remaining_quantity:
                    return Response(
                        {"error": f"La quantité reçue ({quantity_received}) dépasse la quantité restante ({item.remaining_quantity}) pour {item.product.name}"},
                        status=400
                    )

                item.quantity_received += quantity_received
                item.save()

                # ✅ Entrée dans l'entrepôt destination (quantité POSITIVE)
                StockMovement.objects.create(
                    movement_type='transfer',
                    reference_type='transfer',
                    reference_id=transfer.id,
                    product=item.product,
                    variant=item.variant,
                    quantity=quantity_received,  # Quantité positive pour l'entrée
                    from_warehouse=None,  # Pas de source pour l'entrée
                    to_warehouse=transfer.to_warehouse,
                    unit_price=item.unit_price,
                    notes=f"Transfert {transfer.reference} - Réception",
                    created_by=request.user
                )
            except TransferItem.DoesNotExist:
                return Response(
                    {"error": f"L'article {item_id} n'existe pas dans ce transfert"},
                    status=400
                )

        # Mettre à jour le statut
        all_received = all(item.remaining_quantity ==
                           0 for item in transfer.items.all())
        if all_received:
            transfer.status = 'completed'
            transfer.completed_date = timezone.now().date()
        else:
            transfer.status = 'partial'

        transfer.save()

        return Response({
            "status": "transfer received",
            "message": f"Le transfert {transfer.reference} a été réceptionné avec succès",
            "data": TransferDetailSerializer(transfer).data
        })

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Annuler un transfert"""
        transfer = self.get_object()

        if transfer.status in ['completed', 'cancelled']:
            return Response(
                {"error": f"Le transfert ne peut pas être annulé. Statut actuel: {transfer.get_status_display()}"},
                status=400
            )

        transfer.status = 'cancelled'
        transfer.save()

        return Response({
            "status": "transfer cancelled",
            "message": f"Le transfert {transfer.reference} a été annulé avec succès"
        })


class InventoryCountViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les inventaires
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = InventoryCount.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['warehouse', 'status']
    search_fields = ['reference', 'notes']
    ordering_fields = ['count_date', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return InventoryCountListSerializer
        elif self.action == 'retrieve':
            return InventoryCountDetailSerializer
        return InventoryCountCreateSerializer

    def perform_create(self, serializer):
        serializer.save(counted_by=self.request.user)

    @action(detail=True, methods=['post'])
    def add_item(self, request, pk=None):
        """Ajouter un article à l'inventaire"""
        inventory = self.get_object()
        if inventory.status != 'in_progress':
            return Response({"error": "Inventaire non en cours"}, status=400)

        product_id = request.data.get('product_id')
        counted_quantity = request.data.get('counted_quantity', 0)

        try:
            product = Product.objects.get(id=product_id)

            # Récupérer le stock théorique
            theoretical = StockMovement.objects.filter(
                product=product,
                to_warehouse=inventory.warehouse
            ).aggregate(total=Sum('quantity'))['total'] or 0

            theoretical -= StockMovement.objects.filter(
                product=product,
                from_warehouse=inventory.warehouse
            ).aggregate(total=Sum('quantity'))['total'] or 0

            item, created = InventoryCountItem.objects.get_or_create(
                inventory=inventory,
                product=product,
                defaults={
                    'theoretical_quantity': theoretical,
                    'counted_quantity': counted_quantity,
                    'unit_price': product.purchase_price
                }
            )

            if not created:
                item.counted_quantity = counted_quantity
                item.save()

            return Response(InventoryCountItemSerializer(item).data)

        except Product.DoesNotExist:
            return Response({"error": "Product not found"}, status=400)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Terminer l'inventaire"""
        inventory = self.get_object()
        if inventory.status != 'in_progress':
            return Response({"error": "Inventaire non en cours"}, status=400)

        inventory.status = 'completed'
        inventory.save()

        return Response({"status": "inventory completed"})

    @action(detail=True, methods=['post'])
    def validate(self, request, pk=None):
        """Valider l'inventaire et créer les ajustements"""
        inventory = self.get_object()
        if inventory.status != 'completed':
            return Response({"error": "Inventaire non terminé"}, status=400)

        serializer = InventoryCountValidateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        if serializer.validated_data.get('create_movements', True):
            for item in inventory.items.filter(difference__gt=0):
                StockMovement.objects.create(
                    movement_type='adjustment',
                    reference_type='inventory',
                    reference_id=inventory.id,
                    product=item.product,
                    variant=item.variant,
                    quantity=abs(item.difference),
                    to_warehouse=inventory.warehouse if item.difference > 0 else None,
                    from_warehouse=inventory.warehouse if item.difference < 0 else None,
                    unit_price=item.unit_price,
                    notes=f"Ajustement inventaire {inventory.reference}",
                    created_by=request.user
                )

        inventory.status = 'validated'
        inventory.validated_by = request.user
        inventory.save()

        return Response({"status": "inventory validated"})


class StockAlertViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les alertes de stock
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = StockAlert.objects.all()
    serializer_class = StockAlertSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['alert_type', 'status', 'product', 'warehouse']
    search_fields = ['product__name', 'product__reference']

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        """Reconnaître une alerte"""
        alert = self.get_object()
        alert.status = 'acknowledged'
        alert.acknowledged_by = request.user
        alert.acknowledged_at = timezone.now()
        alert.save()
        return Response({"status": "acknowledged"})

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        """Résoudre une alerte"""
        alert = self.get_object()
        alert.status = 'resolved'
        alert.resolved_at = timezone.now()
        alert.save()
        return Response({"status": "resolved"})


class LotViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les lots
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = Lot.objects.all()
    filter_backends = [DjangoFilterBackend,
                       filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['product', 'warehouse', 'quality_status']
    search_fields = ['lot_number', 'serial_number', 'supplier']
    ordering_fields = ['manufacturing_date', 'expiry_date', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return LotListSerializer
        return LotDetailSerializer

    @action(detail=False, methods=['get'])
    def expiring(self, request):
        """Retourne les lots proches d'expiration"""
        days = int(request.query_params.get('days', 30))
        expiry_threshold = timezone.now().date() + timedelta(days=days)

        lots = self.get_queryset().filter(
            expiry_date__lte=expiry_threshold,
            expiry_date__gt=timezone.now().date(),
            quantity__gt=0
        )
        serializer = LotListSerializer(lots, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def quality_control(self, request, pk=None):
        """Ajouter un contrôle qualité"""
        lot = self.get_object()

        serializer = QualityControlSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(lot=lot, inspector=request.user)

            # Mettre à jour le statut qualité du lot
            if serializer.validated_data['result'] == 'failed':
                lot.quality_status = 'damaged'
            elif serializer.validated_data['result'] == 'passed':
                lot.quality_status = 'good'
            lot.save()

            return Response(serializer.data)

        return Response(serializer.errors, status=400)


class QualityControlViewset(viewsets.ModelViewSet):
    """
    Viewset pour gérer les contrôles qualité
    """
    permission_classes = [permissions.IsAuthenticated]
    queryset = QualityControl.objects.all()
    serializer_class = QualityControlSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['lot', 'result', 'inspector']
    ordering_fields = ['control_date']


class InventoryDashboardViewset(viewsets.ViewSet):
    """
    Viewset pour le dashboard inventaire
    """
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Statistiques générales de l'inventaire"""
        total_warehouses = Warehouse.objects.count()
        total_products = Product.objects.count()

        # Valeur totale du stock
        total_stock_value = StockMovement.objects.filter(
            movement_type='in'
        ).aggregate(total=Sum('total_price'))['total'] or 0

        # Produits en stock faible
        low_stock_count = Product.objects.filter(
            stock_quantity__lte=F('minimum_stock'),
            stock_quantity__gt=0
        ).count()

        # Produits en rupture
        out_of_stock_count = Product.objects.filter(stock_quantity=0).count()

        # Transferts en attente
        pending_transfers = Transfer.objects.filter(
            status__in=['pending', 'in_transit', 'partial']
        ).count()

        # Inventaires en cours
        pending_inventories = InventoryCount.objects.filter(
            status__in=['draft', 'in_progress']
        ).count()

        # Alertes actives
        active_alerts = StockAlert.objects.filter(status='active').count()

        # Lots proches d'expiration
        expiring_soon = Lot.objects.filter(
            expiry_date__lte=timezone.now().date() + timedelta(days=30),
            expiry_date__gt=timezone.now().date(),
            quantity__gt=0
        ).count()

        return Response({
            'total_warehouses': total_warehouses,
            'total_products': total_products,
            'total_stock_value': total_stock_value,
            'low_stock_count': low_stock_count,
            'out_of_stock_count': out_of_stock_count,
            'pending_transfers': pending_transfers,
            'pending_inventories': pending_inventories,
            'active_alerts': active_alerts,
            'expiring_soon': expiring_soon
        })

    @action(detail=False, methods=['get'])
    def movements_chart(self, request):
        """Données pour le graphique des mouvements"""
        days = int(request.query_params.get('days', 7))
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days - 1)

        data = []
        for i in range(days):
            date = start_date + timedelta(days=i)
            movements = StockMovement.objects.filter(movement_date__date=date)

            data.append({
                'date': date.strftime('%d/%m'),
                'in': movements.filter(movement_type='in').count(),
                'out': movements.filter(movement_type='out').count(),
                'transfer': movements.filter(movement_type='transfer').count(),
                'adjustment': movements.filter(movement_type='adjustment').count()
            })

        return Response(data)

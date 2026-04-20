from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from django.conf import settings
from django.conf.urls.static import static

router = DefaultRouter()
router.register('warehouses', WarehouseViewset, basename='warehouses')
router.register('locations', LocationViewset, basename='locations')
router.register('stock-movements', StockMovementViewset,
                basename='stock-movements')
router.register('transfers', TransferViewset, basename='transfers')
router.register('inventory-counts', InventoryCountViewset,
                basename='inventory-counts')
router.register('stock-alerts', StockAlertViewset, basename='stock-alerts')
router.register('lots', LotViewset, basename='lots')
router.register('quality-controls', QualityControlViewset,
                basename='quality-controls')
router.register('dashboard', InventoryDashboardViewset,
                basename='inventory-dashboard')

urlpatterns = [
    path('', include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,
                          document_root=settings.MEDIA_ROOT)

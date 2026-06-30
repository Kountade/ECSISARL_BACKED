from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register('suppliers', SupplierViewset, basename='suppliers')
router.register('supplier-contacts', SupplierContactViewset,
                basename='supplier-contacts')
router.register('purchase-orders', PurchaseOrderViewset,
                basename='purchase-orders')
router.register('purchase-receipts', PurchaseReceiptViewset,
                basename='purchase-receipts')
router.register('price-history', PurchasePriceHistoryViewset,
                basename='price-history')
router.register('catalogs', SupplierCatalogViewset, basename='catalogs')
router.register('alerts', PurchaseAlertViewset, basename='purchase-alerts')


urlpatterns = [
    path('', include(router.urls)),
]

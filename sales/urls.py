# sales/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *

router = DefaultRouter()
router.register('customers', CustomerViewset, basename='customers')
router.register('sales', SaleViewset, basename='sales')
router.register('quotations', QuotationViewset, basename='quotations')
router.register('invoices', InvoiceViewset, basename='invoices')
router.register('payments', PaymentViewset, basename='payments')
router.register('returns', ReturnViewset, basename='returns')
router.register('deliveries', DeliveryViewset, basename='deliveries')

urlpatterns = [
    path('', include(router.urls)),
]

from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import BaseUserManager
from django_rest_passwordreset.signals import reset_password_token_created
from django.dispatch import receiver
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.template.loader import render_to_string


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is a required field')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'super_admin')   # Administrateur général
        extra_fields.setdefault('is_active', True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    # ✅ Rôles simplifiés : seulement deux
    ROLE_CHOICES = (
        ('super_admin', 'Administrateur général'),
        ('commercial', 'Commercial'),
    )

    DEPARTMENT_CHOICES = (
        ('direction', 'Direction'),
        ('administration', 'Administration'),
        ('comptabilite', 'Comptabilité'),
        ('rh', 'Ressources Humaines'),
        ('commercial', 'Commercial'),
        ('ventes', 'Ventes'),
        ('achats', 'Achats'),
        ('magasin', 'Magasin'),
        ('logistique', 'Logistique'),
        ('technique', 'Technique'),
        ('marketing', 'Marketing'),
        ('informatique', 'Informatique'),
    )

    email = models.EmailField(max_length=200, unique=True)
    birthday = models.DateField(null=True, blank=True)
    username = models.CharField(max_length=200, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='commercial')
    department = models.CharField(max_length=20, choices=DEPARTMENT_CHOICES, null=True, blank=True)
    
    # Informations personnelles
    phone = models.CharField(max_length=20, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True, default='France')
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    
    # Informations professionnelles
    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    contract_type = models.CharField(max_length=50, null=True, blank=True)
    salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Métadonnées
    is_active = models.BooleanField(default=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_users')
    
    # Photo de profil
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"

    def get_full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.email

    class Meta:
        permissions = [
            ("can_view_reports", "Peut voir les rapports"),
            ("can_manage_users", "Peut gérer les utilisateurs"),
            ("can_validate_orders", "Peut valider les commandes"),
            ("can_manage_inventory", "Peut gérer l'inventaire"),
        ]


@receiver(reset_password_token_created)
def password_reset_token_created(reset_password_token, *args, **kwargs):
    sitelink = "http://localhost:5173/"
    token = reset_password_token.key
    full_link = f"{sitelink}password-reset/{token}"

    context = {
        'full_link': full_link,
        'email_address': reset_password_token.user.email,
        'user_name': reset_password_token.user.get_full_name()
    }

    html_message = render_to_string("users/email/password_reset.html", context=context)
    plain_message = strip_tags(html_message)

    msg = EmailMultiAlternatives(
        subject=f"Réinitialisation de mot de passe pour {reset_password_token.user.email}",
        body=plain_message,
        from_email="noreply@votreentreprise.com",
        to=[reset_password_token.user.email]
    )

    msg.attach_alternative(html_message, "text/html")
    msg.send()
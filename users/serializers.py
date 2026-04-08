from rest_framework import serializers
from .models import CustomUser
from django.contrib.auth import get_user_model

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret.pop('password', None)
        return ret


class RegisterSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(
        choices=CustomUser.ROLE_CHOICES, required=False)

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'role')
        extra_kwargs = {
            'password': {'write_only': True},
            'role': {'required': False}
        }

    def create(self, validated_data):
        # Si le rôle n'est pas fourni, défaut à 'commercial' (seul rôle disponible avec super_admin)
        if 'role' not in validated_data:
            validated_data['role'] = 'commercial'
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'role', 'birthday', 'username')
        read_only_fields = ('id', 'email', 'role')


class UserDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'role', 'birthday',
                  'username', 'is_staff', 'is_superuser')
        read_only_fields = ('id', 'is_staff', 'is_superuser')
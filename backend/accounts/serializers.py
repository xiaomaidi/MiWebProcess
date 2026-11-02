from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_username(self, value):
        from accounts.models import User

        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("用户名已存在")
        return value

    def validate_email(self, value):
        from accounts.models import User

        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("邮箱已存在")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated):
        from accounts.models import User

        user = User.objects.create_user(
            username=validated["username"],
            email=validated["email"],
            password=validated["password"],
            first_name=validated.get("first_name", ""),
            last_name=validated.get("last_name", ""),
        )
        return user


class UserAdminSerializer(serializers.ModelSerializer):
    """平台管理员对用户的管理视图。"""

    class Meta:
        from accounts.models import User

        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_platform_admin",
            "is_superuser",
            "is_active",
            "date_joined",
            "last_login",
        )
        read_only_fields = ("id", "date_joined", "last_login")


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        from accounts.models import User

        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_staff",
            "is_platform_admin",
            "is_superuser",
            "is_active",
            "date_joined",
        )
        read_only_fields = ("id", "username", "is_staff", "is_platform_admin", "is_superuser", "is_active", "date_joined")


class MeUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)


class TokenSerializer(serializers.Serializer):
    """登录校验：返回 user 实例供视图签发 JWT。"""

    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(
            username=data.get("username"),
            password=data.get("password"),
        )
        if user is None:
            raise AuthenticationFailed("用户名或密码错误")
        if not user.is_active:
            raise AuthenticationFailed("账号已禁用")
        data["user"] = user
        return data

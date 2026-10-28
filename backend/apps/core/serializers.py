from rest_framework import serializers

from .models import LoginEvent


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField(max_length=254)
    password = serializers.CharField(max_length=256, trim_whitespace=False)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=32)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=256, trim_whitespace=False)
    new_password = serializers.CharField(max_length=256, trim_whitespace=False)


class LoginEventSerializer(serializers.ModelSerializer):
    outcome_label = serializers.CharField(source="get_outcome_display")

    class Meta:
        model = LoginEvent
        fields = ["created_at", "outcome", "outcome_label", "ip_address", "user_agent"]

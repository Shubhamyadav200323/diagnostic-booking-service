from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import CentreTest, DiagnosticCentre, DiagnosticTest


class DiagnosticTestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticTest
        fields = ("id", "code", "name", "description", "sample_type")


class CentreTestSerializer(serializers.ModelSerializer):
    test = DiagnosticTestSerializer(read_only=True)
    test_id = serializers.PrimaryKeyRelatedField(
        queryset=DiagnosticTest.objects.all(), source="test", write_only=True
    )

    class Meta:
        model = CentreTest
        fields = ("id", "test", "test_id", "price", "is_available")

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def validate(self, attrs):
        centre = self.context["centre"]
        test = attrs.get("test")
        if test and self.instance is None and centre.offerings.filter(test=test).exists():
            raise serializers.ValidationError({"test_id": "This centre already offers this test."})
        if self.instance is not None and test and test != self.instance.test:
            raise serializers.ValidationError({"test_id": "Cannot change the test of an offering, create a new one."})
        return attrs


class DiagnosticCentreListSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiagnosticCentre
        fields = ("id", "name", "address", "city", "pincode", "phone", "is_active")


class DiagnosticCentreDetailSerializer(DiagnosticCentreListSerializer):
    tests = serializers.SerializerMethodField()

    class Meta(DiagnosticCentreListSerializer.Meta):
        fields = DiagnosticCentreListSerializer.Meta.fields + ("tests",)

    @extend_schema_field(CentreTestSerializer(many=True))
    def get_tests(self, centre):
        offerings = [o for o in centre.offerings.all() if o.is_available]
        return CentreTestSerializer(offerings, many=True).data

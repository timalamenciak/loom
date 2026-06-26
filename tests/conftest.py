import pytest


@pytest.fixture
def superuser(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_superuser("admin", "admin@test.example", "password123")

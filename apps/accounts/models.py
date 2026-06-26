from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model — swappable; no extra fields at this stage."""

from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models


class User(AbstractUser):
    """Custom user model with ORCID support."""

    orcid = models.CharField(
        max_length=19,
        blank=True,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$",
                message="Enter a valid ORCID (format: 0000-0000-0000-0000)",
            )
        ],
        help_text="Researcher ORCID iD (e.g., 0000-0002-1825-0097)",
    )

    def __str__(self):
        if self.orcid:
            return f"{self.username} ({self.orcid})"
        return self.username

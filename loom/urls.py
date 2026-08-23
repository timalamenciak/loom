from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import TemplateView

from .health import liveness, readiness

urlpatterns = [
    path("health/live/", liveness, name="health-live"),
    path("health/ready/", readiness, name="health-ready"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("projects/", include("apps.projects.urls")),
    path("schemas/", include("apps.schemas.urls")),
    path("annotation/", include("apps.annotation.urls")),
    path("reader/", include("apps.documents.urls")),
    path("ontology/", include("apps.ontology.urls")),
    path("export/", include("apps.export.urls")),
    path("", include("apps.llm.urls")),
    path(
        "docs/",
        login_required(TemplateView.as_view(template_name="docs/index.html")),
        name="docs-index",
    ),
    path(
        "docs/annotating-your-first-paper/",
        login_required(
            TemplateView.as_view(template_name="docs/annotating-your-first-paper.html")
        ),
        name="docs-annotating-first-paper",
    ),
    path(
        "",
        login_required(TemplateView.as_view(template_name="home.html")),
        name="home",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

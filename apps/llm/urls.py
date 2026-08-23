from django.urls import path

from .views import (
    EnvVarCheckView,
    FewShotSelectorView,
    LLMConfigView,
    LLMMetricsView,
    ProposalAcceptView,
    ProposalRejectView,
    ProposalReviewView,
)

urlpatterns = [
    path(
        "projects/<int:project_pk>/review-proposals/",
        ProposalReviewView.as_view(),
        name="proposal-review",
    ),
    path(
        "llm/proposals/<int:edge_pk>/accept/",
        ProposalAcceptView.as_view(),
        name="proposal-accept",
    ),
    path(
        "llm/proposals/<int:edge_pk>/reject/",
        ProposalRejectView.as_view(),
        name="proposal-reject",
    ),
    path(
        "projects/<int:pk>/settings/llm/",
        LLMConfigView.as_view(),
        name="llm-config",
    ),
    path(
        "projects/<int:pk>/settings/llm/check-env-var/",
        EnvVarCheckView.as_view(),
        name="llm-config-check-env-var",
    ),
    path(
        "projects/<int:pk>/settings/llm/few-shot/",
        FewShotSelectorView.as_view(),
        name="llm-few-shot-selector",
    ),
    path(
        "projects/<int:pk>/settings/llm/metrics/",
        LLMMetricsView.as_view(),
        name="llm-metrics",
    ),
]

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ontology.models import OntologySnapshot
from apps.projects.models import Project, ProjectMembership
from apps.schemas.models import SchemaVersion


class Command(BaseCommand):
    help = "Create a new Loom project and assign an admin."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Project name")
        parser.add_argument(
            "--admin", required=True, metavar="USERNAME", help="Project admin username"
        )
        parser.add_argument("--description", default="", metavar="TEXT")

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            admin_user = User.objects.get(username=options["admin"])
        except User.DoesNotExist:
            raise CommandError(f"No user with username '{options['admin']}'.")

        snapshot = OntologySnapshot.get_active()
        project = Project.objects.create(
            name=options["name"],
            description=options["description"],
            created_by=admin_user,
            active_schema=SchemaVersion.get_active(),
            ontology_snapshot=snapshot,
            ontology_names=(
                sorted(
                    meta.get("name", prefix.lower())
                    for prefix, meta in snapshot.source_versions.items()
                )
                if snapshot
                else []
            ),
        )
        ProjectMembership.objects.create(
            project=project,
            user=admin_user,
            role=ProjectMembership.ROLE_ADMIN,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created project #{project.pk}: {project.name}")
        )

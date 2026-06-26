from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.projects.models import Project, ProjectMembership


class Command(BaseCommand):
    help = "Create a new Loom project and assign an admin."

    def add_arguments(self, parser):
        parser.add_argument("name", help="Project name")
        parser.add_argument("--admin", required=True, metavar="USERNAME", help="Project admin username")
        parser.add_argument("--description", default="", metavar="TEXT")

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            admin_user = User.objects.get(username=options["admin"])
        except User.DoesNotExist:
            raise CommandError(f"No user with username '{options['admin']}'.")

        project = Project.objects.create(
            name=options["name"],
            description=options["description"],
            created_by=admin_user,
        )
        ProjectMembership.objects.create(
            project=project,
            user=admin_user,
            role=ProjectMembership.ROLE_ADMIN,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created project #{project.pk}: {project.name}")
        )

from django.core.management.base import BaseCommand, CommandError

from apps.projects.models import Project
from apps.projects.services import import_ris_file


class Command(BaseCommand):
    help = "Import a RIS bibliographic file into a project."

    def add_arguments(self, parser):
        parser.add_argument("project_id", type=int, help="Project primary key")
        parser.add_argument("ris_file", help="Path to the .ris file")

    def handle(self, *args, **options):
        try:
            project = Project.objects.get(pk=options["project_id"])
        except Project.DoesNotExist:
            raise CommandError(f"No project with id {options['project_id']}.")

        try:
            with open(options["ris_file"], "rb") as f:
                created, skipped = import_ris_file(project, f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {options['ris_file']}")
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(created)} record(s) into '{project.name}'; "
                f"{len(skipped)} duplicate(s) skipped."
            )
        )

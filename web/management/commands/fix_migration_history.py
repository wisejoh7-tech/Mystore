from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = "Reconciles django_migrations history when web.0001_initial is missing but dependent initial migrations exist."

    def handle(self, *args, **options):
        tables = connection.introspection.table_names()
        if "django_migrations" not in tables:
            self.stdout.write(self.style.SUCCESS("django_migrations table does not exist yet. Nothing to fix."))
            return

        with connection.cursor() as cursor:
            cursor.execute("SELECT app, name FROM django_migrations WHERE app = 'web' AND name = '0001_initial';")
            web_initial_exists = cursor.fetchone() is not None

            cursor.execute(
                "SELECT app, name FROM django_migrations WHERE (app = 'admin' AND name = '0001_initial') OR (app = 'account' AND name = '0001_initial');"
            )
            dependent_initials = cursor.fetchall()

        if not web_initial_exists and dependent_initials:
            self.stdout.write(
                self.style.WARNING(
                    "Found dependent initial migrations without web.0001_initial in django_migrations history."
                )
            )
            web_user_exists = "web_user" in tables

            with connection.cursor() as cursor:
                if web_user_exists:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "web_user table exists. Inserting web.0001_initial into django_migrations."
                        )
                    )
                    cursor.execute(
                        "INSERT INTO django_migrations (app, name, applied) VALUES ('web', '0001_initial', %s);",
                        [timezone.now()]
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            "web_user table does not exist. Removing dependent initial migrations from django_migrations."
                        )
                    )
                    cursor.execute(
                        "DELETE FROM django_migrations WHERE (app = 'admin' AND name = '0001_initial') OR (app = 'account' AND name = '0001_initial');"
                    )
            self.stdout.write(self.style.SUCCESS("Successfully reconciled migration history."))
        else:
            self.stdout.write(self.style.SUCCESS("Migration history is consistent."))

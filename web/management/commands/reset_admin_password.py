from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Reset an existing admin user's password or create a new superuser/staff user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            type=str,
            help="Username of the admin account to reset or create",
        )
        parser.add_argument(
            "--password",
            type=str,
            help="New password for the admin account",
        )
        parser.add_argument(
            "--email",
            type=str,
            help="Email address for creating a new user if user does not exist",
        )

    def handle(self, *args, **options):
        username = options.get("username")
        password = options.get("password")
        email = options.get("email")

        if not username:
            users = User.objects.filter(is_staff=True)
            if not users.exists():
                users = User.objects.filter(is_superuser=True)

            if not users.exists():
                self.stdout.write(
                    self.style.WARNING("No existing staff or superuser accounts found.")
                )
                self.stdout.write(
                    "Usage to create one: python manage.py reset_admin_password --username <username> --password <password> [--email <email>]"
                )
                return

            self.stdout.write(self.style.SUCCESS("Existing admin/staff users found:"))
            for user in users:
                self.stdout.write(
                    f"  - Username: {user.username} | Email: {user.email or 'N/A'} | Superuser: {user.is_superuser} | Active: {user.is_active}"
                )
            self.stdout.write(
                "\nTo reset a password, run:\n"
                "python manage.py reset_admin_password --username <username> --password <new_password>"
            )
            return

        if not password:
            raise CommandError("Please provide a --password argument to set a new password.")

        try:
            from django.db.models import Q
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully reset password and ensured superuser/staff/active status for admin user '{user.username}'."
                )
            )
        except User.DoesNotExist:
            user_email = email if (email or "@" in username) else f"{username}@admin.local"
            actual_username = username if "@" not in username else username.split("@")[0]
            user = User.objects.create_superuser(
                username=actual_username, email=user_email, password=password
            )
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"User did not exist. Created new superuser account '{user.username}' with email '{user_email}'."
                )
            )

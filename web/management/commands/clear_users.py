from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


class Command(BaseCommand):
    help = "Clear user accounts from the database to resolve 'user already exist' errors during registration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Delete all users including staff and superusers.",
        )
        parser.add_argument(
            "--username",
            type=str,
            help="Delete a specific user by username or email.",
        )

    def handle(self, *args, **options):
        delete_all = options.get("all")
        username = options.get("username")

        if username:
            users_to_delete = User.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
            count = users_to_delete.count()
            if count == 0:
                self.stdout.write(self.style.WARNING(f"No user found matching '{username}'."))
                return
            users_to_delete.delete()
            self.stdout.write(self.style.SUCCESS(f"Successfully deleted {count} user(s) matching '{username}'."))
            return

        if delete_all:
            users_to_delete = User.objects.all()
        else:
            # By default delete non-superuser, non-staff users (regular accounts)
            users_to_delete = User.objects.filter(is_superuser=False, is_staff=False)
            if not users_to_delete.exists():
                # If no regular users exist, check all users
                users_to_delete = User.objects.all()

        count = users_to_delete.count()
        if count == 0:
            self.stdout.write(self.style.WARNING("No user accounts found to delete."))
            return

        users_to_delete.delete()
        self.stdout.write(self.style.SUCCESS(f"Successfully emptied {count} user account(s) from the database."))

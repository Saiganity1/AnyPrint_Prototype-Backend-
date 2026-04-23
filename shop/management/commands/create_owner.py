from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from shop.models import UserProfile


class Command(BaseCommand):
    help = 'Creates a default owner account'

    def handle(self, *args, **options):
        username = 'Owner1'
        password = 'Owner1'

        # Check if owner already exists
        existing_profile = UserProfile.objects.filter(role=UserProfile.ROLE_OWNER).first()
        if existing_profile:
            self.stdout.write(self.style.WARNING(f'Owner account already exists ({existing_profile.user.username}).'))
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists but no owner profile. Creating profile...'))
            user = User.objects.get(username=username)
        else:
            # Create user with superuser and staff privileges
            user = User.objects.create_user(
                username=username,
                password=password,
                is_superuser=True,
                is_staff=True
            )
            self.stdout.write(self.style.SUCCESS(f'Created user: {username}'))

        # Create UserProfile with OWNER role if it doesn't exist
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': UserProfile.ROLE_OWNER,
                'display_name': 'Store Owner'
            }
        )

        self.stdout.write(self.style.SUCCESS(f'Successfully set up owner account: {username}'))
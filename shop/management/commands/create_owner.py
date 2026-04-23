from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from shop.models import UserProfile


class Command(BaseCommand):
    help = 'Creates a default owner account'

    def handle(self, *args, **options):
        username = 'Owner1'
        password = 'Owner1'

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists.'))
            return

        # Create user with superuser and staff privileges
        user = User.objects.create_user(
            username=username,
            password=password,
            is_superuser=True,
            is_staff=True
        )

        # Create UserProfile with OWNER role
        UserProfile.objects.create(
            user=user,
            role=UserProfile.ROLE_OWNER,
            display_name='Store Owner'
        )

        self.stdout.write(self.style.SUCCESS(f'Successfully created owner account: {username}'))
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from shop.models import UserProfile


class Command(BaseCommand):
    help = 'Creates default owner and admin accounts'

    def handle(self, *args, **options):
        # Create Owner account
        self.create_user('Owner1', 'Owner1', UserProfile.ROLE_OWNER, 'Store Owner')
        
        # Create Admin account
        self.create_user('Admin1', 'Admin1', UserProfile.ROLE_ADMIN, 'Store Admin')

    def create_user(self, username, password, role, display_name):
        # Check if user with this role already exists
        existing_profile = UserProfile.objects.filter(role=role).first()
        if existing_profile:
            self.stdout.write(self.style.WARNING(f'{role} account already exists ({existing_profile.user.username}).'))
            return

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(f'User "{username}" already exists but no {role} profile. Creating profile...'))
            user = User.objects.get(username=username)
        else:
            # Create user with appropriate privileges
            is_superuser = role == UserProfile.ROLE_OWNER
            is_staff = role in {UserProfile.ROLE_OWNER, UserProfile.ROLE_ADMIN}
            
            user = User.objects.create_user(
                username=username,
                password=password,
                is_superuser=is_superuser,
                is_staff=is_staff
            )
            self.stdout.write(self.style.SUCCESS(f'Created user: {username}'))

        # Create UserProfile with the specified role
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': role,
                'display_name': display_name
            }
        )

        self.stdout.write(self.style.SUCCESS(f'Successfully set up {role} account: {username}'))
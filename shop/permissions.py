"""Role-based permission decorators and utilities for API endpoints."""

from functools import wraps
from django.http import JsonResponse
from rest_framework import permissions
from .models import UserProfile


class IsOwner(permissions.BasePermission):
    """Only allow Owner role access."""
    message = "You must be an Owner to access this resource."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.role == UserProfile.ROLE_OWNER


class IsAdminOrOwner(permissions.BasePermission):
    """Allow Owner and Admin roles."""
    message = "You must be an Admin or Owner to access this resource."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.role in [UserProfile.ROLE_ADMIN, UserProfile.ROLE_OWNER]


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Only Owner can edit, others can read."""
    message = "You don't have permission to modify this resource."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, 'profile', None)
        return profile and profile.role == UserProfile.ROLE_OWNER


def require_owner(view_func):
    """Decorator to require Owner role for a view."""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required.'}, status=401)
        
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role != UserProfile.ROLE_OWNER:
            return JsonResponse({'error': 'Permission denied. Owner access required.'}, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapped_view


def require_admin_or_owner(view_func):
    """Decorator to require Admin or Owner role for a view."""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required.'}, status=401)
        
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role not in [UserProfile.ROLE_ADMIN, UserProfile.ROLE_OWNER]:
            return JsonResponse({'error': 'Permission denied. Admin or Owner access required.'}, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapped_view

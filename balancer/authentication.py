"""Local dashboard writes still require CSRF protection, including anonymous API calls."""

from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.request import Request


class CsrfAuthentication(BaseAuthentication):
    def authenticate(self, request: Request) -> None:
        SessionAuthentication().enforce_csrf(request)

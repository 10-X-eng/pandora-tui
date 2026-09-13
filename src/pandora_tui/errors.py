class AppError(Exception):
    """A deliberately sanitized message safe to display to a user."""


class AuthenticationError(AppError):
    pass

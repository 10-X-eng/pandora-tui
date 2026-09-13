import http.cookiejar
import json
import urllib.error
import urllib.request
from .errors import AppError, AuthenticationError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise AppError("Pandora redirected an API request. Please sign in again.")


class Transport:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(self.cookies))

    def request(self, url, data=None, headers=None):
        request = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise AuthenticationError(f"Pandora rejected this session (HTTP {error.code}). Sign in again.") from None
            raise AppError(f"Pandora returned HTTP {error.code}. Try again shortly.") from None
        except (urllib.error.URLError, OSError):
            raise AppError("Cannot reach Pandora. Check your connection and try again.") from None
        return raw

    def json(self, url, data, headers):
        try:
            result = json.loads(self.request(url, data, headers))
        except (ValueError, UnicodeError):
            raise AppError("Pandora returned an unexpected response.") from None
        if not isinstance(result, dict):
            raise AppError("Pandora returned an unexpected response.")
        return result

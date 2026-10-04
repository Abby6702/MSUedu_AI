"""Per-route request size limits. The whole site accepts at most 1 MB per request
(MAX_CONTENT_LENGTH), except the session file upload, which accepts a little more than the
largest allowed file. This lives in the request class, not in the view, because the CSRF check
reads the form data BEFORE any view runs."""
import re

from flask import Request

FILE_BODY_LIMIT = 5 * 1024 * 1024 + 256 * 1024      # the biggest allowed file plus form overhead
UPLOAD_PATH = re.compile(r"^/sessions/\d+/files$")


class AppRequest(Request):
    @property
    def max_content_length(self):
        if self.method == "POST" and UPLOAD_PATH.match(self.path):
            return FILE_BODY_LIMIT
        return super().max_content_length
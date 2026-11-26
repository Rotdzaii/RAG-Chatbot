"""Server-side access to a private Supabase Storage bucket."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from httpx import Client, HTTPError, InvalidURL, Response, URL

from config import settings


def _error_status(response: Response) -> int:
    if response.status_code == 400:
        # Older Storage gateways report the actual error status in the body.
        response.read()
        try:
            return int(response.json()["statusCode"])
        except (ValueError, TypeError, KeyError):
            pass
    return response.status_code


class SupabaseSourceStorage:
    def __init__(self, client: Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @contextmanager
    def _request(self, method: str, path: str, **kwargs) -> Iterator[Response]:
        try:
            with self._client.stream(method, path, **kwargs) as response:
                if not response.is_success:
                    status = _error_status(response)
                    if status == 404:
                        raise FileNotFoundError("Supabase Storage resource not found")
                    if status == 409:
                        raise FileExistsError("Supabase Storage resource already exists")
                    raise OSError(f"Supabase Storage returned HTTP {response.status_code}")
                yield response
        except HTTPError as error:
            raise OSError("Supabase Storage request failed") from error

    def verify_private_bucket(self) -> None:
        with self._request("GET", f"bucket/{self._bucket}") as response:
            response.read()
            try:
                if response.json()["public"] is False:
                    return
            except (ValueError, TypeError, KeyError):
                pass
        raise OSError("Supabase source file bucket must be private")

    def store(self, key: str, mime_type: str, content: bytes) -> None:
        with self._request(
            "POST", f"object/{self._bucket}/{key}", content=content,
            headers={"Content-Type": mime_type, "x-upsert": "false"},
        ) as response:
            response.read()

    def read(self, key: str, byte_size: int) -> bytes:
        content = bytearray()
        with self._request("GET", f"object/authenticated/{self._bucket}/{key}") as response:
            for part in response.iter_bytes(chunk_size=64 * 1024):
                if len(content) + len(part) > byte_size:
                    raise OSError("Stored source file exceeds its recorded size")
                content.extend(part)
        return bytes(content)

    def remove(self, key: str) -> None:
        with self._request("DELETE", f"object/{self._bucket}", json={"prefixes": [key]}) as response:
            response.read()


@cache
def get_supabase_source_storage() -> SupabaseSourceStorage:
    secret = settings.supabase_storage_secret_key
    key = secret.get_secret_value().strip() if secret is not None else ""
    try:
        url = URL((settings.supabase_url or "").strip())
    except InvalidURL as error:
        raise OSError("Invalid Supabase Storage URL") from error
    if url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment:
        raise OSError("Supabase Storage requires an HTTPS project URL")
    if not key.startswith("sb_secret_"):
        raise OSError("Supabase Storage requires a server secret key")

    client = Client(
        base_url=url.copy_with(path=f"{url.path.rstrip('/')}/storage/v1/"),
        headers={"apikey": key, "Accept-Encoding": "identity"},
        timeout=20.0,
    )
    storage = SupabaseSourceStorage(client, settings.rag_source_file_bucket)
    try:
        storage.verify_private_bucket()
    except OSError:
        client.close()
        raise
    return storage

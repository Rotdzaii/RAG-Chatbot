import socket
import unittest
from unittest.mock import Mock, patch

from rag.url_sources import (
    FetchedSource,
    SourceFetchError,
    SourceTooLarge,
    SourceURLValidationError,
    UnsupportedSourceType,
    _PinnedHTTPSConnection,
    _public_addresses,
    fetch_source,
    normalize_source_url,
)


class URLSourcesTests(unittest.TestCase):
    def test_allows_only_exact_vlu_https_hosts_without_credentials_or_port(self) -> None:
        self.assertEqual(
            normalize_source_url("https://www.vlu.edu.vn/academics/majors/marketing"),
            "https://www.vlu.edu.vn/academics/majors/marketing",
        )
        for url in (
            "http://www.vlu.edu.vn/page",
            "https://www.vlu.edu.vn.evil.test/page",
            "https://evil.test/www.vlu.edu.vn",
            "https://user@www.vlu.edu.vn/page",
            "https://www.vlu.edu.vn:443/page",
            "https://www.vlu.edu.vn/page#fragment",
            "https://www.vlu.edu.vn/pa\tge",
            " https://www.vlu.edu.vn/page",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(SourceURLValidationError):
                normalize_source_url(url)

    def test_rejects_mixed_or_private_dns_answers_before_connecting(self) -> None:
        for answers in (
            [],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("168.63.129.16", 443))],
            [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443)),
            ],
            [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("168.63.129.16", 443)),
            ],
            [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0))],
            [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 443, 0, 0))],
        ):
            with (
                self.subTest(answers=answers),
                patch("rag.url_sources.socket.getaddrinfo", return_value=answers),
                self.assertRaises(SourceFetchError),
            ):
                _public_addresses("www.vlu.edu.vn")

    def test_uses_only_public_ipv4_dns_answers(self) -> None:
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        ]
        with patch("rag.url_sources.socket.getaddrinfo", return_value=answers) as resolve:
            self.assertEqual(
                _public_addresses("www.vlu.edu.vn"), ["8.8.8.8", "1.1.1.1"]
            )
        resolve.assert_called_once_with(
            "www.vlu.edu.vn", 443, family=socket.AF_INET, type=socket.SOCK_STREAM
        )

    def test_rejects_blocked_address_before_connection(self) -> None:
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("168.63.129.16", 443))
        ]
        with (
            patch("rag.url_sources.socket.getaddrinfo", return_value=answers),
            patch("rag.url_sources._PinnedHTTPSConnection") as connection,
            self.assertRaises(SourceFetchError),
        ):
            fetch_source("https://www.vlu.edu.vn/page")
        connection.assert_not_called()

    def test_pins_checked_ip_and_verifies_original_hostname(self) -> None:
        raw_socket = Mock()
        context = Mock()
        context.wrap_socket.return_value = Mock()
        with (
            patch("rag.url_sources.ssl.create_default_context", return_value=context),
            patch("rag.url_sources.socket.create_connection", return_value=raw_socket) as connect,
        ):
            connection = _PinnedHTTPSConnection("www.vlu.edu.vn", "8.8.8.8")
            connection.connect()
        connect.assert_called_once_with(("8.8.8.8", 443), timeout=8)
        context.wrap_socket.assert_called_once_with(
            raw_socket, server_hostname="www.vlu.edu.vn"
        )

    def _fake_connection(self, *, status=200, content_type="text/html", body=b"<p>ok</p>"):
        response = Mock()
        response.status = status
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }
        response.getheader.side_effect = lambda name, default=None: headers.get(name, default)
        response.read.side_effect = [body, b""]
        connection = Mock()
        connection.sock = Mock()
        connection.getresponse.return_value = response
        return connection

    def test_fetches_supported_page_with_checked_address_and_bounded_read(self) -> None:
        connection = self._fake_connection()
        with (
            patch("rag.url_sources._public_addresses", return_value=["8.8.8.8"]),
            patch("rag.url_sources._PinnedHTTPSConnection", return_value=connection) as pinned,
        ):
            fetched = fetch_source("https://www.vlu.edu.vn/academics/marketing")
        self.assertEqual(
            fetched,
            FetchedSource(
                url="https://www.vlu.edu.vn/academics/marketing",
                filename="marketing.html",
                mime_type="text/html",
                content=b"<p>ok</p>",
            ),
        )
        pinned.assert_called_once_with("www.vlu.edu.vn", "8.8.8.8")
        connection.request.assert_called_once()
        self.assertEqual(connection.request.call_args.args[:2], ("GET", "/academics/marketing"))
        connection.close.assert_called_once_with()

    def test_does_not_follow_redirect(self) -> None:
        connection = self._fake_connection(status=302)
        with (
            patch("rag.url_sources._public_addresses", return_value=["8.8.8.8"]),
            patch("rag.url_sources._PinnedHTTPSConnection", return_value=connection),
            self.assertRaises(SourceFetchError),
        ):
            fetch_source("https://www.vlu.edu.vn/page")
        connection.request.assert_called_once()
        connection.close.assert_called_once_with()

    def test_rejects_unsupported_type_and_oversized_response(self) -> None:
        for headers, expected in (
            ({"Content-Type": "image/png"}, UnsupportedSourceType),
            ({"Content-Type": "text/html", "Content-Length": str(11 * 1024 * 1024)}, SourceTooLarge),
        ):
            connection = self._fake_connection()
            connection.getresponse.return_value.getheader.side_effect = (
                lambda name, default=None: headers.get(name, default)
            )
            with (
                patch("rag.url_sources._public_addresses", return_value=["8.8.8.8"]),
                patch("rag.url_sources._PinnedHTTPSConnection", return_value=connection),
                self.assertRaises(expected),
            ):
                fetch_source("https://www.vlu.edu.vn/page")
            connection.close.assert_called_once_with()

    def test_rejects_stream_that_exceeds_limit_without_content_length(self) -> None:
        connection = self._fake_connection(body=b"12345")
        connection.getresponse.return_value.getheader.side_effect = (
            lambda name, default=None: "text/plain" if name == "Content-Type" else default
        )
        with (
            patch("rag.url_sources.MAX_URL_BYTES", 4),
            patch("rag.url_sources._public_addresses", return_value=["8.8.8.8"]),
            patch("rag.url_sources._PinnedHTTPSConnection", return_value=connection),
            self.assertRaises(SourceTooLarge),
        ):
            fetch_source("https://www.vlu.edu.vn/page")
        connection.getresponse.return_value.read.assert_called_once_with(5)
        connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

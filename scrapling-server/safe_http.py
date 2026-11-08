"""Pinned HTTPS, no environment proxies, cookies, JavaScript or automatic redirects."""
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
import zlib
from urllib.parse import urljoin, urlsplit

MAX_BODY = 2 * 1024 * 1024
USER_AGENT = "NaechsterSchrittScrapling/1.0"


class FetchError(Exception):
    def __init__(self, code: str, *, http_status=None, detail=None):
        self.code = code
        self.http_status = http_status
        self.detail = detail
        super().__init__(code)


# Total time of one worker run. Keep in sync with netlify/lib/scrapling.mjs (RUN_SECONDS) and src/lib/scrapling-search.ts.
RUN_SECONDS = 240


class Budget:
    def __init__(self, seconds=RUN_SECONDS, documents=40):
        self.deadline = time.monotonic() + seconds
        self.remaining = documents
        self.lock = threading.Lock()

    def claim(self):
        with self.lock:
            if time.monotonic() >= self.deadline:
                raise FetchError("timeout")
            if self.remaining <= 0:
                raise FetchError("request_limit")
            self.remaining -= 1
            return min(8, max(0.1, self.deadline - time.monotonic()))


def target(raw, hosts, resolve=socket.getaddrinfo):
    url = urlsplit(raw)
    if (url.scheme != "https" or url.hostname not in hosts or url.username or url.password
            or url.port not in (None, 443) or "\\" in raw or any(ord(c) < 32 for c in raw)):
        raise FetchError("unsafe_target")
    try:
        answers = resolve(url.hostname, 443, type=socket.SOCK_STREAM)
        addresses = [answer[4][0] for answer in answers]
        def unsafe(ip):
            address = ipaddress.ip_address(ip)
            return not address.is_global or address.is_multicast or address.is_reserved or "%" in ip or (isinstance(address, ipaddress.IPv6Address) and
                    (address.sixtofour is not None or address.teredo is not None))
        if not addresses or any(unsafe(ip) for ip in addresses):
            raise FetchError("unsafe_target", detail="Adresse nicht öffentlich: " + ", ".join(addresses)[:80])
    except (ValueError, OSError) as error:
        raise FetchError("unsafe_target", detail=f"DNS {type(error).__name__} {url.hostname}") from None
    return url, addresses[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # DNS is NOT queried again for the socket; TLS SNI and certificate use the original host.
        sock = socket.socket(socket.AF_INET6 if ":" in self.address else socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.address, 443))
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class Transport:
    def __init__(self, budget, resolve=socket.getaddrinfo, connection=PinnedHTTPS):
        self.budget, self.resolve, self.connection = budget, resolve, connection
        self.last = {}

    def get(self, raw, hosts, authorize=None, *, json_body=None, accept_json=False, accept_javascript=False,
            robots_request=False, json_api=False, accept_xml=False):
        if accept_xml and (accept_json or accept_javascript or json_api or robots_request or json_body is not None):
            raise FetchError("unsupported")
        if json_api and (not accept_json or json_body is not None):
            raise FetchError("unsupported")
        if accept_javascript and (accept_json or json_body is not None):
            raise FetchError("unsupported")
        if robots_request and (accept_json or accept_javascript or json_body is not None
                or urlsplit(raw).path != "/robots.txt" or urlsplit(raw).query or urlsplit(raw).fragment):
            raise FetchError("unsupported")
        # Only server-owned adapters call this option; no method/body is accepted
        # from the search API. Workday's public search uses a read-only POST.
        payload = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        if payload is not None and len(payload) > 4096:
            raise FetchError("unsupported")
        current = raw
        for _ in range(4):
            if authorize:
                authorize(current)
            timeout = self.budget.claim()  # Includes robots and every redirect hop.
            url, address = target(current, hosts, self.resolve)
            delay = max(0, self.last.get(url.hostname, 0) + 1 - time.monotonic())
            if delay:
                time.sleep(min(delay, timeout))
            if time.monotonic() >= self.budget.deadline:
                raise FetchError("timeout")
            connection = self.connection(url.hostname, address, min(timeout, self.budget.deadline - time.monotonic()))
            self.last[url.hostname] = time.monotonic()
            try:
                headers = {"User-Agent": USER_AGENT,
                           "Accept": "application/json" if accept_json else "text/html,application/xhtml+xml,text/plain",
                           "Accept-Encoding": "identity"}
                if accept_javascript:
                    headers["Accept"] = "application/javascript,text/javascript"
                if accept_xml:
                    headers["Accept"] = "application/xml,text/xml"
                if robots_request:
                    headers["Accept"] = "*/*"
                if json_api:
                    headers["Accept"] = "application/vnd.api+json"
                if payload is not None:
                    headers["Content-Type"] = "application/json"
                connection.request("POST" if payload is not None else "GET",
                                   url.path + ("?" + url.query if url.query else ""),
                                   body=payload, headers=headers)
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    # Do not forward a search POST or API request to a redirect.
                    # HTML redirects retain the existing pinned/robots checks.
                    if payload is not None or accept_json or accept_javascript or accept_xml or robots_request:
                        raise FetchError("unsupported", http_status=301 if robots_request and response.status == 301 else None)
                    location = response.getheader("Location")
                    if not location:
                        raise FetchError("unsupported", detail="Weiterleitung ohne Ziel")
                    current = urljoin(current, location)
                    continue
                if response.status in (401, 403, 429):
                    raise FetchError("blocked", http_status=response.status, detail=f"HTTP {response.status} von {url.hostname}")
                if response.status in (404, 410):
                    raise FetchError("gone", http_status=response.status)
                if response.status != 200:
                    raise FetchError("upstream_error", http_status=response.status)
                encoding = response.getheader("Content-Encoding", "identity").lower()
                # Manche Server liefern trotz "identity" gzip; das wird begrenzt entpackt, nichts anderes.
                if encoding not in ("identity", "gzip"):
                    raise FetchError("unsupported", detail=f"Content-Encoding {encoding[:20]}")
                kind = response.getheader("Content-Type", "").lower()
                kinds = (("application/vnd.api+json", "application/json") if json_api else
                         ("application/javascript", "text/javascript") if accept_javascript else
                         ("application/json",) if accept_json else
                         ("application/xml", "text/xml") if accept_xml else
                         ("text/html", "application/xhtml+xml", "text/plain") + (("text/txt",) if url.path == "/robots.txt" else ()))
                if not any(t in kind for t in kinds):
                    raise FetchError("unsupported", detail=f"Content-Type {kind[:60] or 'leer'}")
                chunks, size = [], 0
                while True:
                    if time.monotonic() >= self.budget.deadline:
                        raise FetchError("timeout")
                    chunk = response.read(32768)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise FetchError("too_large")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if encoding == "gzip":
                    try:
                        unpacker = zlib.decompressobj(16 + zlib.MAX_WBITS)
                        body = unpacker.decompress(body, MAX_BODY + 1)
                    except zlib.error:
                        raise FetchError("unsupported", detail="gzip fehlerhaft") from None
                    if len(body) > MAX_BODY or unpacker.unconsumed_tail:
                        raise FetchError("too_large")
                return current, body.decode("utf-8", errors="replace")
            except (OSError, http.client.HTTPException) as error:
                raise FetchError("timeout" if time.monotonic() >= self.budget.deadline else "network_error",
                                 detail=f"{type(error).__name__} {url.hostname}") from None
            finally:
                connection.close()
        raise FetchError("redirect_limit")

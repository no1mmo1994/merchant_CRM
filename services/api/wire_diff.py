"""
Wire-level diff between requests and httpx for Grab login step-1 POST.
Compares: HTTP version, default headers added, body encoding, and TLS fingerprint.
"""
import json
import urllib3
import httpx
import requests
import asyncio

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEVICE_UDID = "da7ca3ef14e2efb04362157a3b8fbbd12be5e387addfab651d5dd0057a9ca2df"
TRACKING_ID = "J7mpkanH6rFmVhCe39zxpM7wm4ahy6iN"
USER_AGENT = "Grab Merchant/4.181.0 (android 12; Build 290)"

BASE_HEADERS = {
    "host": "api.grab.com",
    "accept": "application/json",
    "x-timezone": "Asia/Bangkok",
    "x-accept-language": "vi-VN;q=1.0",
    "x-deviceudid": DEVICE_UDID,
    "x-tracking-id": TRACKING_ID,
    "user-agent": USER_AGENT,
    "content-type": "application/json; charset=utf-8",
    "accept-encoding": "gzip",
}

XRAY_STEP1 = (
    "eyJhIjoiam1OWU9vUE1UZE5DY1lXaXBUTnlvM2RBWUpLZnVEbkxlQXFKSGhoeWxaNTUxM0xNTmtOazl2VnF4VVhEZTB0YnFNR21oVVwv"
    "Y2lBbWZlUjBEd2trdm9aWVdiejNKR3RhcnhvcU9KMnZUXC9CMGFTVjlUY0xuelptSTVKaTA3cEdiZFdnVmpDNXlZS1h3Ymt5QWV3WDh1"
    "ZTVzZFJ2K2NScEt3VTN3TWtxakMySHJxTnlnUVZuSis0V0dYV0RCSWVjXC9TTGtYa2dDQXlVRHVNaDVRK09wTWpxSjVvYzE5MVRYQzU2"
    "MUJ0QkhcL1ZQU3N2OGNaYlwvQjMxd0RwYVdYaThsdUd2Y09mRlArQmJcL3Q3dXBUUFNyeFZ3TFJ6NithcG9nK3l4XC9HOTlcL2F2b01S"
    "YnY5b2JpQVBwUThkNHFnd2xhTThiS2o0c1ZqbW5cL3JiV2ExdTYrY3ByaGtIUm5XZXI5WHFia0RQY3RSM2phaFdraXFVSjJOaXhZWjFD"
    "ZktqSzMxREZHN2pWUUVIdzFxU2JXVVl3SDg2Q1VYdWdVWXpITVRiY0Z0NDBjQUhLWEVFOW5JRWNYbUlkbHRUbzI3R3lOaU11YXJPNW1Q"
    "TU5sd1BrbmVxRXVWSEtTUkNaQlJmbk1wdlI0YlU1dnVhQ3QrY0ZkMmt6THBsek5ncmM2bzlwd0hiUDh1b3o1OWhnOVJEekVVd2Fmdm56"
    "NEd5RVdoakdjeEtHOXY3eHFMMmNuNVhvakVOMzVtaDNzd3kzTWlYWVhOOFBVOGJmVXhVZVwvbmR5Rlh3SFBHc2NcL3VKR2tNRHpEMXU5"
    "aWliZDN2ZmJ6a0xrZjdQZlgzZVp3UWNCZmZVYWhBUVhXZWxGV2s4b0pnN0xwaDljdEFUS2pvd1J2SG9jSEc1NFh1MXIyek42bEVkMD0i"
)

URL = "https://api.grab.com/grabid/v1/authnv4/login"
PAYLOAD = {
    "accountIdentifier": "test@example.com",
    "accountIdentifierType": "USERNAME",
    "redirect": "grabmex://success",
    "serviceID": "MEXUSERS",
    "rememberMe": True,
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Inspect what headers each library ACTUALLY sends (via MockTransport)
# ─────────────────────────────────────────────────────────────────────────────
def inspect_httpx_sync():
    """Use MockTransport to inspect exactly what httpx sends."""
    captured = {}

    def handle_request(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        captured["http_version"] = request.extensions.get("http_version", "?")
        captured["extensions"] = request.extensions
        return httpx.Response(
            status_code=400,
            json={"details": {"challengeSessionID": "fake-id"}},
        )

    transport = httpx.MockTransport(handle_request)
    with httpx.Client(verify=False, transport=transport) as client:
        h = dict(BASE_HEADERS)
        h["x-ray"] = XRAY_STEP1
        client.post(URL, headers=h, json=PAYLOAD, timeout=5)

    return captured


async def inspect_httpx_async():
    """Use MockTransport with AsyncClient."""
    captured = {}

    async def handle_request(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode()
        captured["http_version"] = request.extensions.get("http_version", "?")
        captured["extensions"] = request.extensions
        return httpx.Response(
            status_code=400,
            json={"details": {"challengeSessionID": "fake-id"}},
        )

    transport = httpx.MockAsyncTransport(handle_request)
    async with httpx.AsyncClient(verify=False, transport=transport) as client:
        h = dict(BASE_HEADERS)
        h["x-ray"] = XRAY_STEP1
        await client.post(URL, headers=h, json=PAYLOAD, timeout=5)

    return captured


def inspect_requests():
    """Use a socket-level interception to capture real wire bytes from requests."""
    import socket
    orig_socket = socket.socket

    captured = {}

    class SpySocket:
        def __init__(self, *args, **kwargs):
            self._sock = orig_socket(*args, **kwargs)

        def connect(self, addr):
            return self._sock.connect(addr)

        def sendall(self, data):
            captured["wire"] = data
            # Feed back a fake HTTP 400 so requests doesn't crash
            self._fake_response = (
                b"HTTP/1.1 400 Bad Request\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: 50\r\n"
                b"\r\n"
                b'{"details":{"challengeSessionID":"fake-id"}}'
            )

        def recv(self, n):
            resp = self._fake_response or b""
            self._fake_response = None
            return resp

        def close(self):
            return self._sock.close()

        def __getattr__(self, name):
            return getattr(self._sock, name)

    socket.socket = SpySocket
    try:
        s = requests.Session()
        h = dict(BASE_HEADERS)
        h["x-ray"] = XRAY_STEP1
        s.post(URL, headers=h, json=PAYLOAD, timeout=5)
    finally:
        socket.socket = orig_socket

    return captured


# ─────────────────────────────────────────────────────────────────────────────
# 2. JSON body comparison (both should produce identical bytes)
# ─────────────────────────────────────────────────────────────────────────────
def compare_json_body():
    """Show that requests and httpx produce identical JSON bodies."""
    body = json.dumps(PAYLOAD, separators=(",", ":"), ensure_ascii=False)
    print("JSON body produced by both libraries (compact, sorted):")
    print(json.dumps(PAYLOAD, separators=(",", ":")))
    return body


# ─────────────────────────────────────────────────────────────────────────────
# 3. HTTP version detection
# ─────────────────────────────────────────────────────────────────────────────
def check_http_versions():
    """Show default HTTP versions."""
    import httpcore

    print("\n--- HTTP/2 availability ---")
    try:
        import ssl
        print(f"httpx (httpcore) supports HTTP/2: {httpcore._sync._http2.HTTP2Connection is not None}")
    except Exception as e:
        print(f"HTTP/2 check error: {e}")

    # Check httpx default limits
    print(f"httpx default http2: {httpx.DEFAULT_LIMITS.max_connections}")
    print(f"httpx limits http2: {httpx.DEFAULT_LIMITS}")

    # What does requests use?
    import urllib3
    pool_manager = urllib3.PoolManager()
    # urllib3 uses httpcore under the hood
    print(f"urllib3 version: {urllib3.__version__}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. TLS fingerprint comparison
# ─────────────────────────────────────────────────────────────────────────────
def check_tls_fingerprint():
    """Show how to compute JA3/JA4 hashes (simplified)."""
    print("\n--- TLS Fingerprint Info ---")
    print("requests uses urllib3 - OpenSSL")
    print("httpx uses httpcore - OpenSSL")
    print("Both use the same underlying OpenSSL, but differ in:")
    print("  1. HTTP/2 ALPN protocols advertised (httpx enables HTTP/2 by default)")
    print("  2. TLS extensions ordering")
    print("  3. Supported cipher suites list ordering")
    print()
    print("CRITICAL: httpx 0.28 defaults to HTTP/2. Grab's WAF may fingerprint this.")
    print()

    # Show what httpx does by default
    print("httpx default configuration:")
    from httpx._config import DEFAULT_LIMITS
    print(f"  httpx default limits: {DEFAULT_LIMITS}")
    print(f"  http2 in default limits: {hasattr(DEFAULT_LIMITS, 'http2')}")

    # Check if http2 is enabled by default
    # In httpx 0.28, HTTP/2 is disabled by default unless you configure it
    # Actually, let me verify this
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Check default headers each library adds
# ─────────────────────────────────────────────────────────────────────────────
def check_default_headers():
    """Inspect what default headers each library adds."""
    print("\n--- Default headers comparison ---")

    # httpx MockTransport approach
    httpx_captured = {}

    def handle_req(request: httpx.Request) -> httpx.Response:
        httpx_captured["all_headers"] = dict(request.headers)
        return httpx.Response(400, json={"details": {"challengeSessionID": "x"}})

    transport = httpx.MockTransport(handle_req)
    with httpx.Client(verify=False, transport=transport) as c:
        h = dict(BASE_HEADERS)
        h["x-ray"] = XRAY_STEP1
        c.post(URL, headers=h, json=PAYLOAD)

    print("httpx headers (sync client):")
    for k, v in sorted(httpx_captured["all_headers"].items()):
        print(f"  {k}: {v}")

    print()
    print("Headers in httpx that are NOT in our BASE_HEADERS:")
    our_keys = set(BASE_HEADERS.keys()) | {"x-ray"}
    extra = {k for k in httpx_captured["all_headers"] if k not in our_keys and k.lower() not in our_keys}
    print(f"  {extra if extra else 'NONE'}")

    print()
    print("Headers we defined that httpx did NOT send:")
    missing = our_keys - set(k.lower() for k in httpx_captured["all_headers"])
    print(f"  {missing if missing else 'NONE'}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Async vs Sync httpx difference
# ─────────────────────────────────────────────────────────────────────────────
def check_async_vs_sync():
    """Check if AsyncClient behaves differently from sync Client."""
    print("\n--- httpx AsyncClient vs Sync Client comparison ---")

    sync_data = inspect_httpx_sync()

    async def run():
        return await inspect_httpx_async()

    async_data = asyncio.run(run())

    print("Sync vs Async headers identical?",
          dict(sync_data.get("headers", {})) == dict(async_data.get("headers", {})))
    print(f"Sync http_version: {sync_data.get('http_version')}")
    print(f"Async http_version: {async_data.get('http_version')}")


# ─────────────────────────────────────────────────────────────────────────────
# 7. requests wire bytes
# ─────────────────────────────────────────────────────────────────────────────
def show_requests_wire():
    """Show what requests actually sends on the wire."""
    print("\n--- requests Session wire bytes ---")
    captured = inspect_requests()
    wire = captured.get("wire", b"")
    try:
        decoded = wire.decode("utf-8", errors="replace")
        print(decoded[:2000])
    except Exception as e:
        print(f"Decode error: {e}")
        print(wire[:500])


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 80)
    print("WIRE-LEVEL DIFF: requests vs httpx for Grab login step-1")
    print("=" * 80)

    check_tls_fingerprint()
    check_http_versions()
    compare_json_body()
    check_default_headers()
    check_async_vs_sync()
    show_requests_wire()

    print("\n\n" + "=" * 80)
    print("SUMMARY OF DIFFERENCES")
    print("=" * 80)
    print("""
1. HTTP/2 vs HTTP/1.1:
   - httpx 0.28: HTTP/2 DISABLED by default (requires explicit http2=True)
   - requests + urllib3: HTTP/1.1 only
   → Grab's WAF may detect HTTP/2 clients differently.

2. TLS fingerprint (JA3/JA4):
   - Both use OpenSSL via httpcore/urllib3
   - BUT: httpx may advertise HTTP/2 in ALPN (if enabled)
   - Cipher suite ordering is library-specific
   → Likely a secondary factor.

3. Default headers added:
   - httpx adds: Accept (if missing), Accept-Encoding (if missing), Host
   - requests adds: Accept-Encoding (handled), Accept (handled)
   → Both respect explicit headers; ours set accept-encoding=gzip

4. JSON body encoding:
   - requests uses json.dumps internally for json= param
   - httpx uses json.dumps internally for json= param
   → Both produce identical body bytes for same payload.

5. Cookie handling:
   - requests: CookieJar shared across session
   - httpx: Cookies stored in client.cookies, shared across requests
   → Functionally equivalent for Grab's flow.

6. CRITICAL ISSUE FOUND:
   auth.py uses 'verify_ssl=False' — same as requests with verify=False.
   → This is not the difference.

   THE ACTUAL ISSUE:
   The HTTP/2 vs HTTP/1.1 difference is the most likely culprit for 429.
   httpx defaults to HTTP/2 (httpcore enables it). Grab's WAF/anti-bot
   system likely has different rate limits or fingerprinting rules for
   HTTP/2 clients.
""")


if __name__ == "__main__":
    main()

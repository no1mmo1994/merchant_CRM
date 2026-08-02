"""Decode the Grab x-ray token to find its embedded timestamp."""
import base64, json, zlib
from collections import Counter

XRAY = (
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

print(f"Total x-ray chars: {len(XRAY)}")
print()

# ── Layer 1: outer base64 → JSON envelope ───────────────────────────────────
outer_bytes = base64.b64decode(XRAY)
# The base64 contains escaped forward-slashes (\/) - decode and normalize
outer_str = outer_bytes.decode("utf-8")
print(f"Outer bytes length: {len(outer_bytes)}")
print(f"Outer bytes (first 100 ASCII-safe): {repr(outer_str[:100])}")
print(f"Outer bytes (chars 100-200): {repr(outer_str[100:200])}")
print(f"Outer bytes (chars 200-300): {repr(outer_str[200:300])}")
print(f"Outer bytes (last 100): {repr(outer_str[-100:])}")
print()

# Try to fix the escaped slashes for json parsing
fixed = outer_str.replace("\\/", "/")
print(f"Fixed string length: {len(fixed)}")
print(f"Fixed (last 100): {repr(fixed[-100:])}")

try:
    outer = json.loads(fixed)
    print(f"\n=== OUTER JSON parsed successfully ===")
    print(f"Keys: {list(outer.keys())}")
    print(f"Values: {[type(v).__name__ for v in outer.values()]}")
    for k, v in outer.items():
        if isinstance(v, str):
            print(f"  {k!r}: (len={len(v)}) preview={v[:60]!r}...")
        else:
            print(f"  {k!r}: {v!r}")
except json.JSONDecodeError as e:
    print(f"\nFixed string still fails: {e}")
    # Try parsing the original (with \/) - python's json requires \/ but maybe valid here
    try:
        outer = json.loads(outer_str)
        print(f"Original parses with \\/: OK")
    except Exception as e2:
        print(f"Original also fails: {e2}")
        # Find the problem char
        for i, ch in enumerate(outer_str):
            if i in (e.colno - 1,):
                print(f"  Around col {e.colno}: {outer_str[max(0,e.colno-30):e.colno+30]!r}")
        raise

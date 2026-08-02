"""Re-run the dashboard's login flow with the same x-ray token as login1-done.py.

If this works, the dashboard and login1-done.py are equivalent at the HTTP layer.
If this fails but login1-done.py succeeds, we have a real divergence to find.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Make the API's `app/` importable as if we ran uvicorn from services/api
API_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(API_ROOT))

from grab.auth import StaticXRayProvider, login_three_step  # noqa: E402


async def main() -> None:
    # Same hardcoded token from Login/login1-done.py step 1
    xray = (
        "eyJhIjoiRkZRTGxQZVpPTktTMTlWK2M2UGVRWnZXbm1LN0NRXC9ndVZwcEptN2MwWGI0"
        "TFgzcnNEUTBzNm12eXZab0NnaTVFeE0xOGNoeEFnNWpQd3Q1VWFGYXVRaExZbnQ2bCtO"
        "bG5Ub0NwZStpR1I2c1V6SUpxWkQ5STBoVXk5OTB0bUs4UjVxR3EyNm9XQVZUTUJ6b2Rs"
        "TFFPNmh4cGZ2S2FoQ3I4aVdFTEEycElKeGM5RVBnRWQ0VUpOcll3UEZWY2gxZEtvMm5N"
        "N0lQZHpPcXVJWlVLTWpNc2JEcUM3YklhS09ZRnBjN2dmTEJ0VmM0UXlPYmU5UFVmaHBI"
        "S3VQNXE1SzJETVZoZWJqV1F5Nm05TXJUNXc4SXQ2NnpYOVB5ZSsyelMxWE1NVUdCOVZv"
        "dTlDMFVzMHlZSXZQK3BBSjhzc1ZNK0dKQ3dEY25Ia2NKZnNXYWlRb1lhZjhBeXVlOUl1"
        "NklDUjNEaUFNMHdEUm9hYStpb0FoXC9RSVc5amdTN0hTUFBlQjlTNEdRaldQNVRnSUxk"
        "RkF5TUY1a0xjaEoyMlJGVGxTd0g3T2Zwb2VlUFpcL0JPN3B2aE5OZkpWb1UwRWhPazQ0"
        "MFNCeW9cL2lOM28ySnhKS2VsanZLc2EwOE5SN0FTK2d5c3h5OVR2UXg3dStFQittT2p5"
        "MlwvaHFNOXNobHc0eWJDQzRrY3pJekVRWXF2elFTOEwxZXEzXC9wRENISlNYczlsaGFi"
        "a1NoMldcL1lmNTVhNXl6YSsxZ2wxWHNVa3BQNVU0TFJFUVF6SlE4b1lQTStpN1hmTGxu"
        "eDlNRmRKcFpyOVp1cVY2TkF1cHhPbDE2XC9ST2pNeXFJQWRzQ3lCR1VhSmNpUjVsYklI"
        "OTVwXC92RDVWNXJsSGJLVXI2UzlRU0YraXF3RGJOc2tLZWc9IiwiYyI6IkZZYlQ0UmNT"
        "dzN1SDh5aDBkUXd5Y25kazFNK1NBcmt3a0dkMVBPOW5xc2ZWWThTRkVoVzljaW9INmJz"
        "RThyaElkKzFqem56MzJzaDI0TnZjUFhUck1vNmJ0Um9ERzlXUEcwOEIrMFlzTWljWkJR"
        "XC9YNGRLbXdoRU05aUVLdXBFTlBDVHA1SVwvYW5JMXJ3TzUwMzRXUTFcL2VVdFJ5YVNO"
        "WHVIV2ZJU1dLREhFU3lkaVVmWGg2TXJEVHk2bjloYXJyQlhcL3ppbmZKU3Jxdzh1MUVU"
        "dHhBSHdqWGZ6Yk9HSXJQTTE5ZEp6QStxZ3RFWkZlWjVWNkxpdXpTaDgrYVwvY2lmRlR0"
        "SlQ4R2Vpa2VKRWt0NStITll6NGFBWWM0WFA4U3YrUlJIXC9UTFpJTW1CeEpObHJIVW5u"
        "M2pNeUdQcUd3TlRScVcyZW12c3pVSFk2cFZoRVZLTll4cXp4ekhOdklRdWJna0t1WWd2"
        "MWNHSDZ1MkkxTFp3T3VsTDBSXC80SExYOEIrWitPRXZVbHZhODNTVFlMakpXaGJFOXhG"
        "cThIbWxwNVlmRlBOWTMrMDZ2RytHRjRuZlFWQ1NhU2hrcmRjaFJWMjdBMmRERkY0WUZa"
        "cmVTM2FXdDJQS3ZqRUhDVHVlQWYzWWZhN2NCZ21VNHRjSlY4XC9vNk1ESlZpcytWU3Nj"
        "YzR4aHBuM1VzMlM5TUdrNDVBNTJjOUlabDNQKzFSYnJ3b25SOVVzMDBHNDcrSm8zZ0hq"
        "OTdFZU01SmRNaXhaK0lUamNFYkkzUUlEZnFGeEd1K1wvVWNKSlhTWjVNbjMxbjhkVFdk"
        "R2lLMjhKcW1ZMENQRGc0cz0iLCJpcyI6InQiLCJ0YW1wZXJlZCI6ImYiLCJpIjoibTEi"
        "LCJ2Ijoidy40Ljc3LjAuMTg3IiwiayI6NDE4MzM5OCwia3YiOiIzIiwib2kiOiJEMnY0"
        "Z0YzYzZyIiwiZ3NpZCI6ImNvbS5ncmFiLm1leC5hcHBsaWNhdGlvbi5NZXhBcHBsaWNh"
        "dGlvbkA5ZWQ0ZDAzIn0="
    )
    provider = StaticXRayProvider(step1_token=xray, step3_token=xray)
    try:
        result = await login_three_step(
            email="ceo.truongbaongu@gmail.com",
            password="Baongu@6868",
            xray=provider,
            verify_ssl=False,
        )
    except Exception as exc:
        # Mirror the dashboard's error-shape, but also dump attributes.
        print("FAILED:", exc)
        for attr in ("step", "http_status", "grab_reason", "grab_message", "request_id"):
            try:
                print(f"  {attr} = {getattr(exc, attr, None)!r}")
            except Exception:
                pass
        raw = getattr(exc, "raw_body", "") or ""
        if raw:
            print(f"  raw_body = {raw[:500]}")
        return
    print("OK displayToken:", result.display_token[:30] + "…")
    print("OK authnToken:  ", result.authn_token[:30] + "…")


if __name__ == "__main__":
    asyncio.run(main())

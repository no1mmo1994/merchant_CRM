"""Cross-test: run the dashboard's request shape through requests (not httpx).

If this succeeds -> TLS fingerprint is the root cause (httpx's httpcore != urllib3).
If this still 429s -> rate limit hit by prior calls, or header content differs.
"""

from __future__ import annotations

import json
import urllib3

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

XRAY = (
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
    "MWNHSDZ1MkkxTFp3Q3VsTDBSXC80SExYOEIrWitPRXZVbHZhODNTVFlMakpXaGJFOXhG"
    "cThIbWxwNVlmRlBOWTMrMDZ2RytHRjRuZlFWQ1NhU2hrcmRjaFJWMjdBMmRERkY0WUZa"
    "cmVTM2FXdDJQS3ZqRUhDVHVlQWYzWWZhN2NCZ21VNHRjSlY4XC9vNk1ESlZpcytWU3Nj"
    "YzR4aHBuM1VzMlM5TUdrNDVBNTJjOUlabDNQKzFSYnJ3b25SOVVzMDBHNDcrSm8zZ0hq"
    "OTdFZU01SmRNaXhaK0lUamNFYkkzUUlEZnFGeEd1K1wvVWNKSlhTWjVNbjMxbjhkVFdk"
    "R2lLMjhKcW1ZMENQRGc0cz0iLCJpcyI6InQiLCJ0YW1wZXJlZCI6ImYiLCJpIjoibTEi"
    "LCJ2Ijoidy40Ljc3LjAuMTg3IiwiayI6NDE4MzM5OCwia3YiOiIzIiwib2kiOiJEMnY0"
    "Z0YzYzZyIiwiZ3NpZCI6ImNvbS5ncmFiLm1leC5hcHBsaWNhdGlvbi5NZXhBcHBsaWNh"
    "dGlvbkA5ZWQ0ZDAzIn0="
)

BASE_HEADERS = {
    "host": "api.grab.com",
    "accept": "application/json",
    "x-timezone": "Asia/Bangkok",
    "x-accept-language": "vi-VN;q=1.0",
    "x-deviceudid": "da7ca3ef14e2efb04362157a3b8fbbd12be5e387addfab651d5dd0057a9ca2df",
    "x-tracking-id": "J7mpkanH6rFmVhCe39zxpM7wm4ahy6iN",
    "user-agent": "Grab Merchant/4.181.0 (android 12; Build 290)",
    "content-type": "application/json; charset=utf-8",
    "accept-encoding": "gzip",
}


def main() -> None:
    email = "ceo.truongbaongu@gmail.com"
    password = "Baongu@6868"
    session = requests.Session()
    base_url = "https://api.grab.com"

    # --- Step 1 ---
    h1 = dict(BASE_HEADERS)
    h1["x-ray"] = XRAY
    r1 = session.post(
        f"{base_url}/grabid/v1/authnv4/login",
        headers=h1,
        json={
            "accountIdentifier": email,
            "accountIdentifierType": "USERNAME",
            "redirect": "grabmex://success",
            "serviceID": "MEXUSERS",
            "rememberMe": True,
        },
        verify=False,
    )
    print(f"Step 1: HTTP {r1.status_code}")
    if r1.status_code != 400:
        print(f"  FAIL: {r1.text[:300]}")
        return
    step1_data = r1.json()
    challenge_session_id = (step1_data.get("details") or {}).get("challengeSessionID")
    if not challenge_session_id:
        print(f"  FAIL: no challengeSessionID: {step1_data}")
        return
    print(f"  OK: challengeSessionID = {challenge_session_id}")

    # --- Step 2 ---
    h2 = dict(BASE_HEADERS)
    r2 = session.post(
        f"{base_url}/grabid/v1/challengesession/challengeSession/verifyChallenge",
        headers=h2,
        json={
            "challengeSessionID": challenge_session_id,
            "challengeType": "PWD_V2",
            "payload": {"code": password},
        },
        verify=False,
    )
    print(f"Step 2: HTTP {r2.status_code}")
    if r2.status_code != 200:
        print(f"  FAIL: {r2.text[:300]}")
        return
    print("  OK")

    # --- Step 3 ---
    h3 = dict(BASE_HEADERS)
    h3["x-ray"] = XRAY
    r3 = session.post(
        f"{base_url}/grabid/v1/authnv4/login",
        headers=h3,
        json={
            "accountIdentifier": email,
            "accountIdentifierType": "USERNAME",
            "redirect": "grabmex://success",
            "serviceID": "MEXUSERS",
            "challengeSessionId": challenge_session_id,
            "rememberMe": True,
        },
        verify=False,
    )
    print(f"Step 3: HTTP {r3.status_code}")
    if r3.status_code != 200:
        print(f"  FAIL: {r3.text[:300]}")
        return
    step3_data = r3.json()
    display_token = step3_data.get("displayToken", "")
    authn_token = step3_data.get("authnToken", "")
    print(f"  OK: displayToken={display_token[:30]}...")
    print(f"  OK: authnToken={authn_token[:30]}...")


if __name__ == "__main__":
    main()

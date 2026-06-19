import os
import base64
import hmac
import hashlib
import time
import requests
import dotenv
from amexcerts import certificate_path

dotenv.load_dotenv()

# Configuration
root_ca_path = certificate_path()
APP_ID = os.getenv("APP_ID")
VERSION = os.getenv("VERSION")
ENV = os.getenv("ENV")
SECRET = os.getenv(f"SECRET_{ENV}")
TOKEN_URL = os.getenv(f"JWT_TOKEN_URL_{ENV}")


def generate_hmac_signature(secret):
    timestamp = str(int(time.time() * 1000))
    message = f"{APP_ID}-{VERSION}-{timestamp}"
    secret_bytes = base64.b64decode(secret)
    signature = hmac.new(secret_bytes, message.encode(), hashlib.sha256).digest()
    signature_base64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return signature_base64, timestamp


def get_a2a_jwt_token():
    signature, timestamp = generate_hmac_signature(SECRET)
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Version": VERSION,
        "X-Auth-Timestamp": timestamp,
        "X-Auth-Signature": signature,
        "X-Auth-AppID": APP_ID,
    }
    payload = {
        "scope": [
            "/aifirewall/genai/microsoft/v1/askamex/chat/**::post",
            "/genai/microsoft/v1/askamex/chat/**::post",
            "/genai/microsoft/v1/model/validations/loadtest/mock/eag/echo/llmmock/**::post",
            "/aifirewall/genai/microsoft/v1/model/validations/loadtest/mock/eag/echo/llmmock/**::post",
            "/genai/microsoft/v1/smdlc/**::post",
            "/aifirewall/genai/microsoft/v1/smdlc/**::post",
            "/genai/microsoft/v1/model/validations/finops/**::post",
            "/aifirewall/genai/microsoft/v1/model/validations/finops/**::post",
            "/genai/microsoft/v1/marketing/campaigns/headlines/**::post",
            "/aifirewall/genai/microsoft/v1/marketing/campaigns/headlines/**::post",
            "/genai/tims/v1/models/zephyr-7b-beta/**::post",
            "/aifirewall/genai/tims/v1/models/zephyr-7b-beta/**::post",
            "/genai/microsoft/v1/finance/competitive_intelligence/**::post",
            "/aifirewall/genai/microsoft/v1/finance/competitive_intelligence/**::post",
            "/genai/microsoft/v1/finance/risk_control/**::post",
            "/aifirewall/genai/microsoft/v1/finance/risk_control/**::post",
            "/genai/google/v1/launchpad/models/llama3/**::post",
            "/aifirewall/genai/google/v1/launchpad/models/llama3/**::post",
            "/genai/microsoft/v1/servicing_cie/**::post",
            "/aifirewall/genai/microsoft/v1/servicing_cie/**::post",
            "/genai/microsoft/v1/github_pr_agent/**::post",
            "/genai/microsoft/v1/servicingintentclassification/**::post",
            "/aifirewall/genai/microsoft/v1/github_pr_agent/**::post",
            "/genai/google/v1/models/gemini-2.0-flash-001/**::post",
            "/genai/google/v1/models/gemini-2.0-flash-lite-001/**::post",
            "/genai/google/v1/models/gemini-2.5-pro-preview-05-06/**::post",
            "/genai/google/v1/models/llama32-90b-instruct/**::post",
            "/genai/google/v1/models/gemini-3.1-pro-preview/**::post",
            "/aifirewall/genai/google/v1/models/gemini-3.1-pro-preview/**::post"
        ]
    }

    if TOKEN_URL is None:
        raise ValueError(
            "JWT_TOKEN_URL is not set. Please check your environment variables."
        )
    response = requests.post(
        TOKEN_URL, headers=headers, json=payload, verify=root_ca_path
    )
    response.raise_for_status()
    return response.json()["authorization_token"]

"""
test_euri_connection.py
────────────────────────
A quick one-time test to confirm your Euri API key works correctly.

Run this AFTER you have added your EURI_API_KEY to your .env file:
  $ python test_euri_connection.py

This file can be deleted after the connection is confirmed.
"""

from openai import OpenAI
from dotenv import load_dotenv
import os

# Load your .env file
load_dotenv()

EURI_API_KEY = os.getenv("EURI_API_KEY", "")
EURI_BASE_URL = "https://api.euron.one/api/v1/euri"

if not EURI_API_KEY:
    print("ERROR: EURI_API_KEY is not set in your .env file.")
    print("Please add it and try again.")
    exit(1)

print("Testing Euri API connection...")
print(f"Base URL : {EURI_BASE_URL}")
print(f"API Key  : {EURI_API_KEY[:8]}...{EURI_API_KEY[-4:]}")
print("-" * 50)

# ── Test 1: Text generation ────────────────────────────────────────────────
print("\n[TEST 1] Text generation with gemini-2.5-pro...")
try:
    client = OpenAI(api_key=EURI_API_KEY, base_url=EURI_BASE_URL)
    response = client.chat.completions.create(
        model="gemini-2.5-pro",
        messages=[
            {"role": "user", "content": "Say 'Euri text connection successful!' and nothing else."}
        ],
        max_tokens=4096,  # gemini-2.5-pro is a thinking model — needs 4096 minimum
    )
    print("SUCCESS:", response.choices[0].message.content)
except Exception as e:
    print("FAILED:", str(e))

# ── Test 2: Image generation ───────────────────────────────────────────────
print("\n[TEST 2] Image generation with gemini-2-pro-image-preview...")
try:
    client = OpenAI(api_key=EURI_API_KEY, base_url=EURI_BASE_URL)
    response = client.images.generate(
        model="gemini-2-pro-image-preview",
        prompt="A simple blue square. Minimalist.",
        size="1024x1024",
        n=1,
    )
    print("SUCCESS: Image URL:", response.data[0].url or "(base64 data received)")
except Exception as e:
    print("FAILED:", str(e))

print("\n" + "-" * 50)
print("Connection test complete.")

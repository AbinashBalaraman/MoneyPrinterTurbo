"""Test and verification suite for opencode_endpoint package."""

import sys
import os

# Add parent directory so we can import opencode_endpoint as a package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opencode_endpoint import OpenCodeClient


def test_opencode():
    print("=" * 60)
    print("  Testing OpenCode Endpoint Integration")
    print("=" * 60)

    client = OpenCodeClient()
    print(f"[OK] Client initialized with base_url: {client.base_url}")
    print(f"[OK] Default model: {client.default_model}")
    print(f"[OK] Default reasoning: {client.default_reasoning}")

    # 1. Test Model Listing & Auto-Discovery
    print("\n--- 1. Testing Auto Model Discovery ---")
    all_models = client.list_models(refresh=True)
    print(f"[PASS] Successfully fetched {len(all_models)} total models.")

    free_models = client.list_models(only_free=True)
    print(f"[PASS] Successfully filtered {len(free_models)} free models:")
    for fm in free_models:
        print(f"   • {fm.id:<34} (Endpoint: {fm.endpoint_type}, Default Reasoning: {fm.default_reasoning})")

    # 2. Test Reasoning Options Auto-Fetch
    print("\n--- 2. Testing Reasoning Auto-Fetch ---")
    muse_reasoning = client.get_reasoning_options("muse-spark-1.3-contributor-free")
    print(f"Muse Spark 1.3: {muse_reasoning['supported_tiers']} (Recommended: {muse_reasoning['default_tier']})")
    assert muse_reasoning["default_tier"] == "xhigh", "Expected default reasoning to be xhigh for Muse Spark"

    deepseek_reasoning = client.get_reasoning_options("deepseek-v4-flash-free")
    print(f"DeepSeek v4:    {deepseek_reasoning['supported_tiers']} (Recommended: {deepseek_reasoning['default_tier']})")
    assert deepseek_reasoning["default_tier"] == "high", "Expected default reasoning to be high for DeepSeek"
    print("[PASS] Reasoning auto-detection verified.")

    # 3. Test Live Chat with xhigh reasoning
    print("\n--- 3. Testing Live Query (Muse Spark 1.3 + xhigh reasoning) ---")
    prompt = "In 1 concise sentence, what is an event loop in computer science?"
    print(f"Prompt: {prompt}")
    resp = client.chat(prompt, model="muse-spark-1.3-contributor-free", reasoning_effort="xhigh")
    print(f"\n[Response Received]:\n{resp.strip()}\n")
    assert len(resp.strip()) > 0, "Response should not be empty"
    print("[PASS] Live OpenCode test succeeded!")
    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    test_opencode()

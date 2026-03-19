"""
Test grok2api chat/completions endpoint.

Usage:
    python debugs/test_chat_completions.py [--base-url URL] [--api-key KEY] [--model MODEL]

Runs three checks:
  1. Health check
  2. Non-streaming chat/completions
  3. Streaming chat/completions (SSE)
"""

import argparse
import json
import sys
import urllib.request
import urllib.error


def health_check(base_url: str) -> bool:
    url = f"{base_url}/health"
    print(f"[1/3] Health check: GET {url}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            ok = resp.status == 200 and body.get("status") == "ok"
            print(f"  Status: {resp.status}, Body: {body}")
            print(f"  Result: {'PASS' if ok else 'FAIL'}")
            return ok
    except Exception as e:
        print(f"  Error: {e}")
        print("  Result: FAIL")
        return False


def test_chat_non_stream(base_url: str, api_key: str, model: str) -> bool:
    url = f"{base_url}/v1/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Say 'hello' and nothing else."}],
            "stream": False,
            "temperature": 0,
        }
    ).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    print(f"\n[2/3] Non-streaming chat/completions: POST {url}")
    print(f"  Model: {model}, Stream: false")
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
            status_code = resp.status
            content = ""
            choices = body.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
            print(f"  Status: {status_code}")
            print(f"  Response content: {content[:200]}")
            ok = status_code == 200 and len(content) > 0
            print(f"  Result: {'PASS' if ok else 'FAIL'}")
            return ok
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"  HTTP Error: {e.code} {e.reason}")
        print(f"  Body: {err_body[:500]}")
        print("  Result: FAIL")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        print("  Result: FAIL")
        return False


def test_chat_stream(base_url: str, api_key: str, model: str) -> bool:
    url = f"{base_url}/v1/chat/completions"
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "Say 'world' and nothing else."}],
            "stream": True,
            "temperature": 0,
        }
    ).encode()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    print(f"\n[3/3] Streaming chat/completions: POST {url}")
    print(f"  Model: {model}, Stream: true")
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            status_code = resp.status
            print(f"  Status: {status_code}")

            collected = []
            chunk_count = 0
            for raw_line in resp:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                if line == "data: [DONE]":
                    chunk_count += 1
                    break
                if line.startswith("data: "):
                    chunk_count += 1
                    try:
                        data = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            collected.append(text)
                    except json.JSONDecodeError:
                        pass

            full_text = "".join(collected)
            print(f"  Chunks received: {chunk_count}")
            print(f"  Collected text: {full_text[:200]}")
            ok = status_code == 200 and chunk_count > 0
            print(f"  Result: {'PASS' if ok else 'FAIL'}")
            return ok
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"  HTTP Error: {e.code} {e.reason}")
        print(f"  Body: {err_body[:500]}")
        print("  Result: FAIL")
        return False
    except Exception as e:
        print(f"  Error: {e}")
        print("  Result: FAIL")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test grok2api chat/completions")
    parser.add_argument("--base-url", default="http://127.0.0.1:34567")
    parser.add_argument("--api-key", default="sk-grok2api")
    parser.add_argument("--model", default="grok-3")
    args = parser.parse_args()

    print(f"=== grok2api chat/completions test ===")
    print(f"Base URL: {args.base_url}")
    print(f"Model:    {args.model}")
    print()

    results = []
    results.append(("Health check", health_check(args.base_url)))
    results.append(
        ("Non-streaming", test_chat_non_stream(args.base_url, args.api_key, args.model))
    )
    results.append(
        ("Streaming", test_chat_stream(args.base_url, args.api_key, args.model))
    )

    print("\n=== Summary ===")
    all_pass = True
    for name, ok in results:
        tag = "PASS" if ok else "FAIL"
        print(f"  {name}: {tag}")
        if not ok:
            all_pass = False

    print(f"\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()

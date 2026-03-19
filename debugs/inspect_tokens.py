"""
Inspect token pool status in grok2api instance.

Usage (run inside the grok2api container):
    python /app/debugs/inspect_tokens.py

Usage (from host, for CLI-managed instance):
    docker exec grok2api-default python /app/debugs/inspect_tokens.py
"""

import json
import sys
import os

TOKEN_PATH = os.environ.get("TOKEN_PATH", "/app/data/token.json")


def main():
    try:
        with open(TOKEN_PATH) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Token file not found: {TOKEN_PATH}")
        sys.exit(1)

    pool_names = ["ssoBasic", "sso", "ssoSuper"]
    for pool_name in pool_names:
        tokens = data.get(pool_name, [])
        if not tokens:
            print(f"[{pool_name}] empty")
            continue
        print(f"[{pool_name}] {len(tokens)} tokens:")
        status_counts = {}
        for i, t in enumerate(tokens):
            status = t.get("status", "unknown")
            fail_count = t.get("fail_count", 0)
            token_preview = t.get("token", "")[:50]
            status_counts[status] = status_counts.get(status, 0) + 1
            print(
                f"  [{i}] status={status}, fail_count={fail_count}, token={token_preview}..."
            )
        print(f"  Summary: {status_counts}")
    print()


if __name__ == "__main__":
    main()

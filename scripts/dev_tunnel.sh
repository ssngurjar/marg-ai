#!/usr/bin/env bash
# Expose the local API over public HTTPS so Meta can reach the WhatsApp webhook (s03 §7).
#
# Uses a Cloudflare quick tunnel: no account needed, a real certificate (Meta rejects self-signed
# ones), and a new random URL on every start. Save "<url>/webhooks/whatsapp" in the App Dashboard
# (WhatsApp → Configuration) each time. Stop with Ctrl+C.
#
# Usage: scripts/dev_tunnel.sh [port]   (default 8000, the uvicorn port used in development)
set -euo pipefail

port="${1:-8000}"

if ! command -v cloudflared >/dev/null 2>&1; then
    echo "cloudflared is not installed: brew install cloudflared" >&2
    exit 1
fi

if ! curl --silent --fail --max-time 2 "http://127.0.0.1:${port}/healthz" >/dev/null; then
    echo "Nothing answers on http://127.0.0.1:${port}/healthz. Start the API first." >&2
    exit 1
fi

echo "Tunnelling http://127.0.0.1:${port}. Callback URL: the trycloudflare.com address below + /webhooks/whatsapp"
exec cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${port}"

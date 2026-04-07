#!/bin/bash
# ============================================================
# generate_key.sh
# Run this ONCE on your Ubuntu machine to generate a stable
# Chrome extension key and patch your manifest.json.
#
# Usage:
#   chmod +x generate_key.sh
#   ./generate_key.sh /path/to/your/extension/folder
#
# Output:
#   - key.pem        (keep secret, never commit to git)
#   - manifest.json  (updated with the "key" field)
#   - Prints your stable extension ID
# ============================================================

set -e

EXTENSION_DIR="${1:-.}"
MANIFEST="$EXTENSION_DIR/manifest.json"

if [ ! -f "$MANIFEST" ]; then
  echo "❌  manifest.json not found in: $EXTENSION_DIR"
  exit 1
fi

echo "🔑  Generating RSA-2048 private key..."
openssl genrsa 2048 2>/dev/null \
  | openssl pkcs8 -topk8 -nocrypt -out "$EXTENSION_DIR/key.pem"

echo "📤  Extracting public key (DER → base64)..."
PUBLIC_KEY_B64=$(openssl rsa \
  -in "$EXTENSION_DIR/key.pem" \
  -pubout \
  -outform DER 2>/dev/null \
  | openssl base64 -A)

# ---- Derive the extension ID the same way Chrome does --------
# SHA-256 of the DER public key → first 16 bytes → map to a-p
echo "🔢  Computing extension ID..."
EXT_ID=$(openssl rsa \
  -in "$EXTENSION_DIR/key.pem" \
  -pubout \
  -outform DER 2>/dev/null \
  | sha256sum \
  | head -c 32 \
  | tr '0-9a-f' 'a-p')

# ---- Inject "key" into manifest.json -------------------------
# Uses Python (available on every Ubuntu) for safe JSON editing
python3 - <<PYEOF
import json, sys

path = "$MANIFEST"
with open(path) as f:
    data = json.load(f)

data["key"] = "$PUBLIC_KEY_B64"

with open(path, "w") as f:
    json.dump(data, f, indent=2)

print("✅  manifest.json updated with key field.")
PYEOF

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  Your stable extension ID:                           ║"
printf "║  %-52s ║\n" "$EXT_ID"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "📋  Next steps:"
echo "  1. Load the extension in Chrome: chrome://extensions → Load unpacked"
echo "  2. Confirm the ID matches what's shown above."
echo "  3. Keep key.pem safe — deleting it means you can never regenerate the same ID."
echo "  4. Add key.pem to your .gitignore!"
echo ""
echo "🪟  Windows shortcut URL template:"
echo "    chrome-extension://$EXT_ID/fullpage.html"

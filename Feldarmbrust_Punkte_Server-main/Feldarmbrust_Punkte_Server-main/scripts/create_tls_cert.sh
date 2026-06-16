#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <laptop-ip-or-hostname>"
  echo "Example: $0 192.168.1.100"
  exit 1
fi

HOST="$1"
OUT_DIR="${2:-certs}"

mkdir -p "$OUT_DIR"

cat > "$OUT_DIR/openssl-san.cnf" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
x509_extensions = v3_req
distinguished_name = dn

[dn]
CN = $HOST

[v3_req]
subjectAltName = @alt_names
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = localhost
DNS.2 = $HOST
IP.1 = 127.0.0.1
IP.2 = $HOST
EOF

openssl req \
  -x509 \
  -nodes \
  -days 825 \
  -newkey rsa:2048 \
  -keyout "$OUT_DIR/server.key" \
  -out "$OUT_DIR/server.crt" \
  -config "$OUT_DIR/openssl-san.cnf"

chmod 600 "$OUT_DIR/server.key"

echo "Created:"
echo "  $OUT_DIR/server.crt"
echo "  $OUT_DIR/server.key"
echo
echo "Start server with:"
echo "  FELDARMBRUST_TLS_CERTFILE=$OUT_DIR/server.crt FELDARMBRUST_TLS_KEYFILE=$OUT_DIR/server.key python start_server.py"

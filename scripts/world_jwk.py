"""Print the public JWK(S) for a World private_key_jwt client key, for portal registration.

    python scripts/world_jwk.py ./secrets/world_client_key.pem --kid scooby-2026-11

Reads a PEM private key (or public key) and prints {"keys": [{kty, n, e, kid, alg: RS256, use: sig}]}.
Only public parameters are printed. World requires RSA keys of 2048–8192 bits.
"""
import argparse
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('pem')
    ap.add_argument('--kid', required=True)
    a = ap.parse_args()
    data = Path(a.pem).read_bytes()
    try:
        key = serialization.load_pem_private_key(data, password=None).public_key()
    except ValueError:
        key = serialization.load_pem_public_key(data)
    if not isinstance(key, rsa.RSAPublicKey) or not 2048 <= key.key_size <= 8192:
        sys.exit('An RSA key of 2048-8192 bits is required.')
    jwk = json.loads(RSAAlgorithm.to_jwk(key))
    jwk = {'kty': 'RSA', 'n': jwk['n'], 'e': jwk['e'], 'kid': a.kid, 'alg': 'RS256', 'use': 'sig'}
    print(json.dumps({'keys': [jwk]}, indent=2))


if __name__ == '__main__':
    main()

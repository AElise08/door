"""Assinatura do transporte, não assinatura da aprovação pelo dono (v1)."""
import base64
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def generate():
    private = Ed25519PrivateKey.generate()
    return (private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption()).hex(),
            private.public_key().public_bytes(serialization.Encoding.Raw,
                                             serialization.PublicFormat.Raw).hex())


def encode(private_hex, request):
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    return base64.b64encode(raw).decode(), key.sign(raw).hex()


def verify(public_hex, raw, signature):
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(bytes.fromhex(signature), raw)
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False

from __future__ import annotations

import base64
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from playwright.async_api import Page

_DEFAULT_PAGE_ENCRYPT_JS = """(plaintext) => {
    if (typeof encryptPassword === 'function') {
        return encryptPassword(plaintext);
    }
    if (typeof window !== 'undefined' && typeof window.encryptPassword === 'function') {
        return window.encryptPassword(plaintext);
    }
    if (typeof JSEncrypt !== 'undefined') {
        const keyEl = document.querySelector('[data-public-key], #publicKey, #rsaPublicKey');
        const keyMeta = document.querySelector('meta[name="public-key"]');
        const key = keyEl?.getAttribute('data-public-key')
            || keyEl?.textContent?.trim()
            || keyMeta?.getAttribute('content');
        if (key) {
            const enc = new JSEncrypt();
            enc.setPublicKey(key);
            const out = enc.encrypt(plaintext);
            if (out) return out;
        }
    }
    throw new Error(
        'No page encryption function found. Provide expression or use password_mode="rsa".'
    );
}"""


def _load_public_key(public_key: str) -> RSAPublicKey:
    key_text = public_key.strip()
    if "BEGIN" in key_text:
        loaded = serialization.load_pem_public_key(key_text.encode("utf-8"))
    else:
        der = base64.b64decode(key_text)
        loaded = serialization.load_der_public_key(der)
    if not isinstance(loaded, RSAPublicKey):
        raise ValueError("public_key must be an RSA public key")
    return loaded


def encrypt_rsa(plaintext: str, public_key: str) -> str:
    if not public_key.strip():
        raise ValueError("public_key is required for password_mode='rsa'")
    key = _load_public_key(public_key)
    ciphertext = key.encrypt(
        plaintext.encode("utf-8"),
        padding.PKCS1v15(),
    )
    return base64.b64encode(ciphertext).decode("ascii")


async def encrypt_via_page(
    page: Page,
    plaintext: str,
    *,
    expression: str | None = None,
) -> str:
    script = expression.strip() if expression else _DEFAULT_PAGE_ENCRYPT_JS
    result = await page.evaluate(script, plaintext)
    if result is None:
        raise ValueError("Page encryption returned null")
    return str(result)

"""Who a user is, without storing who they are (decision A1, data-model.md §3).

A user is identified by a salted hash of their channel address. The address itself is kept only
encrypted (AES-256-GCM), bound to its hash, and decrypted just before a message is sent.
"""

import base64
import binascii
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from app.core.errors import ConfigError, InvalidAddressCiphertext

NONCE_BYTES = 12
KEY_BYTES = 32
MIN_SALT_BYTES = 32


class UserIdentity:
    def __init__(self, salt: SecretStr, encryption_key: SecretStr) -> None:
        self._salt = _decode_salt(salt)
        self._cipher = AESGCM(_decode_key(encryption_key))

    def user_hash(self, channel: str, address: str) -> str:
        """hex(HMAC-SHA256(salt, "<channel>:<address>")). The same person always hashes the same."""
        message = f"{channel}:{address}".encode()
        return hmac.new(self._salt, message, hashlib.sha256).hexdigest()

    def encrypt_address(self, user_hash: str, address: str) -> bytes:
        """nonce ‖ ciphertext ‖ tag. The user_hash is the associated data, binding it to its row."""
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._cipher.encrypt(nonce, address.encode(), user_hash.encode())

    def decrypt_address(self, user_hash: str, ciphertext: bytes) -> SecretStr:
        """Raises InvalidAddressCiphertext if the ciphertext isn't this user's (or is damaged)."""
        if len(ciphertext) <= NONCE_BYTES:
            raise InvalidAddressCiphertext("address ciphertext is too short")
        nonce, sealed = ciphertext[:NONCE_BYTES], ciphertext[NONCE_BYTES:]
        try:
            plaintext = self._cipher.decrypt(nonce, sealed, user_hash.encode())
        except InvalidTag as exc:
            raise InvalidAddressCiphertext(
                "address ciphertext doesn't match this user or the key"
            ) from exc
        return SecretStr(plaintext.decode())


def _decode_salt(salt: SecretStr) -> bytes:
    try:
        decoded = bytes.fromhex(salt.get_secret_value())
    except ValueError as exc:
        raise ConfigError("USER_HASH_SALT must be hex") from exc
    if len(decoded) < MIN_SALT_BYTES:
        raise ConfigError(f"USER_HASH_SALT must be at least {MIN_SALT_BYTES} bytes")
    return decoded


def _decode_key(key: SecretStr) -> bytes:
    try:
        decoded = base64.b64decode(key.get_secret_value(), validate=True)
    except binascii.Error as exc:
        raise ConfigError("ADDRESS_ENCRYPTION_KEY must be base64") from exc
    if len(decoded) != KEY_BYTES:
        raise ConfigError(f"ADDRESS_ENCRYPTION_KEY must decode to {KEY_BYTES} bytes")
    return decoded

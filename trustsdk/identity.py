import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519


class Keypair:

    def __init__(self, private_key=None):
        self.private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

    def public_key_hex(self) -> str:
        return self.public_key.public_bytes_raw().hex()

    def private_key_hex(self) -> str:
        return self.private_key.private_bytes_raw().hex()

    @classmethod
    def from_hex(cls, private_key_hex: str) -> "Keypair":
        raw = bytes.fromhex(private_key_hex)
        if len(raw) != 32:
            raise ValueError("private key must be 32 bytes")
        return cls(ed25519.Ed25519PrivateKey.from_private_bytes(raw))

    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.private_key_hex())
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @classmethod
    def load(cls, path) -> "Keypair":
        return cls.from_hex(Path(path).read_text().strip())

    @classmethod
    def load_or_create(cls, path) -> "Keypair":
        path = Path(path)
        if path.exists():
            try:
                return cls.load(path)
            except (ValueError, OSError):
                pass
        keypair = cls()
        keypair.save(path)
        return keypair

    def sign(self, message: str) -> str:
        return self.private_key.sign(message.encode()).hex()

    @staticmethod
    def verify(public_key_hex: str, message: str, signature_hex: str) -> bool:
        if not public_key_hex or not signature_hex or message is None:
            return False
        try:
            raw = bytes.fromhex(public_key_hex)
            key_obj = ed25519.Ed25519PublicKey.from_public_bytes(raw)
            key_obj.verify(bytes.fromhex(signature_hex), message.encode())
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False


if __name__ == "__main__":
    kp = Keypair()
    print("agent ID:", kp.public_key_hex())
    sig = kp.sign("hello")
    print("real:", Keypair.verify(kp.public_key_hex(), "hello", sig))
    print("fake:", Keypair.verify(kp.public_key_hex(), "hacked", sig))

    restored = Keypair.from_hex(kp.private_key_hex())
    print("restored matches:", restored.public_key_hex() == kp.public_key_hex())
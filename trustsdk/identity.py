from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

class Keypair:

    def __init__(self):
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()

    def public_key_hex(self) -> str:
        return self.public_key.public_bytes_raw().hex()

    def sign(self, message : str) -> str:
        return self.private_key.sign(message.encode()).hex()

    @staticmethod
    def verify(public_key_hex : str, message : str, signature_hex :str) -> bool:
        if signature_hex is None:
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
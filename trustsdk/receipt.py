import json
from identity import Keypair


class Receipt:
    def __init__(self, task_id, task_type, deadline, delivered_at, accepted):
        self.task_id = task_id
        self.task_type = task_type
        self.deadline = deadline
        self.delivered_at = delivered_at
        self.accepted = accepted

    def to_text(self) -> str:
        data = {
            "task_id" : self.task_id,
            "task_type" : self.task_type,
            "deadline" : self.deadline,
            "delivered_at" : self.delivered_at,
            "accepted" : self.accepted
            }
        return json.dumps(data, sort_keys=True)

    def sign_by(self, keypair) -> str:
        return keypair.sign(self.to_text())
    


if __name__ == "__main__":
    kp = Keypair()
    r = Receipt("47", "summarize", 100.0, 95.0, True)
    sig = r.sign_by(kp)
    print("signature:", sig)
    print("valid:", Keypair.verify(kp.public_key_hex(), r.to_text(), sig))
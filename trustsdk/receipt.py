import json
from trustsdk.identity import Keypair


class Receipt:
    def __init__(self, task_id, task_type, deadline, started_at, delivered_at, accepted, specialist_sig = None , hiring_sig = None):
        self.task_id = task_id
        self.task_type = task_type
        self.deadline = deadline
        self.started_at = started_at
        self.delivered_at = delivered_at
        self.accepted = accepted
        self.specialist_sig = specialist_sig
        self.hiring_sig = hiring_sig

    def to_text(self) -> str:
        data = {
            "task_id" : self.task_id,
            "task_type" : self.task_type,
            "deadline" : self.deadline,
            "started_at": self.started_at,
            "delivered_at" : self.delivered_at,
            "accepted" : self.accepted
            }
        return json.dumps(data, sort_keys=True)

    def sign_by(self, keypair, role) -> str:
        sig = keypair.sign(self.to_text())
        if role == "specialist":
            self.specialist_sig = sig
        else:
            self.hiring_sig = sig
        return sig


    def verify_signatures(self,specialist_pubkey,hiring_pubkey) -> bool:
        return Keypair.verify( specialist_pubkey , self.to_text() , self.specialist_sig ) and Keypair.verify( hiring_pubkey , self.to_text() , self.hiring_sig )
        
        

        
if __name__ == "__main__":
    specialist = Keypair()
    hiring = Keypair()

    r = Receipt("47", "summarize", 100.0, 90.0, 95.0, True)
    r.sign_by(specialist, "specialist")
    r.sign_by(hiring, "hiring")

    print("both valid:", r.verify_signatures(specialist.public_key_hex(), hiring.public_key_hex()))

    fake = Receipt("99", "summarize", 100.0, 90.0, 95.0, True)
    fake.sign_by(specialist, "specialist")   # only specialist signs, no hiring countersign
    print("faker valid:", fake.verify_signatures(specialist.public_key_hex(), hiring.public_key_hex()))
import logging
import os
import time
import uuid
from contextlib import contextmanager

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from kredisco.identity import Keypair
    from kredisco.receipt import Receipt
except ModuleNotFoundError:
    from identity import Keypair
    from receipt import Receipt

DEFAULT_SERVER = "https://api.kredisco.com"
DEFAULT_TIMEOUT = 10.0
DEFAULT_BUDGET = 30.0
DEFAULT_KEY_DIR = ".kredisco"
_RAISE = object()

logger = logging.getLogger("kredisco")


class KrediscoError(Exception):
    pass


class Agent:

    def __init__(self, name, specialty, keypair):
        self.name = name
        self.specialty = specialty
        self.keypair = keypair

    @property
    def pubkey(self):
        return self.keypair.public_key_hex()

    def __repr__(self):
        return "<Agent {} {}>".format(self.name, self.pubkey[:8])


class Task:

    def __init__(self):
        self.accepted = True
        self.result = None
        self.error = None


class Kredisco:

    def __init__(self, api_key=None, workflow_id=None, server=None,
                 key_dir=None, timeout=DEFAULT_TIMEOUT, budget=DEFAULT_BUDGET):
        self.api_key = api_key or os.environ.get("KREDISCO_API_KEY")
        if not self.api_key:
            raise KrediscoError(
                "No API key. Pass api_key= or set KREDISCO_API_KEY. "
                "Create one at your Kredisco dashboard."
            )

        self.workflow_id = workflow_id
        self.server = (server or os.environ.get("KREDISCO_SERVER")
                       or DEFAULT_SERVER).rstrip("/")
        self.key_dir = key_dir or os.environ.get("KREDISCO_KEY_DIR", DEFAULT_KEY_DIR)
        self.timeout = timeout
        self.budget = budget

        self.session = self._build_session()
        self.caller = Keypair.load_or_create(
            os.path.join(self.key_dir, "orchestrator.key")
        )
        self._registered = set()

    # ---------- plumbing ----------

    def _build_session(self):
        session = requests.Session()
        session.headers["Authorization"] = "Bearer " + self.api_key
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _post(self, path, payload):
        try:
            res = self.session.post(self.server + path, json=payload,
                                    timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("kredisco: %s unreachable (%s)", path, exc)
            return None
        if res.status_code == 401:
            logger.error("kredisco: API key rejected")
        elif res.status_code >= 400:
            logger.warning("kredisco: %s returned %s %s",
                           path, res.status_code, res.text[:200])
        return res

    def _get(self, path):
        try:
            res = self.session.get(self.server + path, timeout=self.timeout)
        except requests.RequestException as exc:
            raise KrediscoError("Could not reach Kredisco: {}".format(exc))
        if res.status_code >= 400:
            raise KrediscoError("{} returned {}".format(path, res.status_code))
        return res.json()

    # ---------- agents ----------

    def agent(self, name, specialty=None):
        keypair = Keypair.load_or_create(
            os.path.join(self.key_dir, "agents", name + ".key")
        )
        agent = Agent(name, specialty or name, keypair)

        if agent.pubkey not in self._registered:
            self._post("/register", {
                "pubkey": agent.pubkey,
                "name": agent.name,
                "specialty": agent.specialty,
            })
            self._registered.add(agent.pubkey)

        return agent

    # ---------- reporting ----------

    def _report(self, agent, task_type, started_at, delivered_at,
                accepted, deadline, parent_task_id=None):
        task_id = str(uuid.uuid4())
        receipt = Receipt(
            task_id, task_type, deadline, started_at, delivered_at,
            accepted, parent_task_id=parent_task_id,
        )
        receipt.sign_by(agent.keypair, "specialist")
        receipt.sign_by(self.caller, "hiring")

        self._post("/settle", {
            "task_id": task_id,
            "task_type": task_type,
            "deadline": deadline,
            "started_at": started_at,
            "delivered_at": delivered_at,
            "accepted": accepted,
            "specialist_sig": receipt.specialist_sig,
            "hiring_sig": receipt.hiring_sig,
            "specialist_pubkey": agent.pubkey,
            "hiring_pubkey": self.caller.public_key_hex(),
            "agent_id": agent.pubkey,
            "caller_id": self.caller.public_key_hex(),
            "parent_task_id": parent_task_id,
            "workflow_id": self.workflow_id,
        })
        return task_id

    def track(self, agent, task_type, fn, *args,
              validate=None, budget=None, retries=0, default=_RAISE, **kwargs):
        parent_task_id = None
        attempts = retries + 1
        last_error = None

        for attempt in range(attempts):
            started_at = time.time()
            deadline = started_at + (budget or self.budget)
            accepted = True
            result = None
            last_error = None

            try:
                result = fn(*args, **kwargs)
                if validate is not None:
                    accepted = bool(validate(result))
            except Exception as exc:
                accepted = False
                last_error = exc

            delivered_at = time.time()
            task_id = self._report(agent, task_type, started_at, delivered_at,
                                   accepted, deadline, parent_task_id)

            if accepted:
                return result

            parent_task_id = task_id
            if attempt < attempts - 1:
                logger.info("kredisco: retrying %s on %s", task_type, agent.name)

        if default is not _RAISE:
            logger.info("kredisco: %s on %s failed, returning default",
                        task_type, agent.name)
            return default

        if last_error is not None:
            raise last_error
        return result
    @contextmanager
    def task(self, agent, task_type, budget=None, parent_task_id=None):
        started_at = time.time()
        deadline = started_at + (budget or self.budget)
        handle = Task()
        try:
            yield handle
        except Exception:
            handle.accepted = False
            self._report(agent, task_type, started_at, time.time(),
                         False, deadline, parent_task_id)
            raise
        self._report(agent, task_type, started_at, time.time(),
                     handle.accepted, deadline, parent_task_id)

    # ---------- reading ----------

    def score(self, pubkey):
        return self._get("/score/" + pubkey)["score"]

    def breakdown(self, pubkey):
        return self._get("/agent/" + pubkey + "/breakdown")

    def dashboard(self):
        return self._get("/dashboard")["workflows"]

    def leaderboard(self):
        return self._get("/leaderboard")["leaderboard"]

    def best(self, specialty, minimum=0):
        rows = [r for r in self.leaderboard()
                if r.get("specialty") == specialty and r["score"] >= minimum]
        return rows[0] if rows else None

# Kredisco

**A trust layer for AI agents.**

Humans carry a credit score. It follows you between lenders, it is held
by a bureau rather than by you, and it is built from what other parties
report about your behaviour. A landlord who has never met you can decide
whether to trust you in seconds.

AI agents have no equivalent. You wire one into your pipeline and have
no idea whether it is dependable until something breaks.

Kredisco gives every agent a portable trust score, 300 to 850, earned
from its real track record and held where the agent cannot reach it.

---

## Why agents need one

A pipeline with six agents fails quietly. One step degrades, output
quality drops, and you find out from a user complaint days later.
Nothing tells you which agent to stop calling.

The instinct is to ask the agents, or to collect ratings. Neither
survives contact with incentives. An agent will always report that it
did well. Open rating systems get farmed: an audit of ERC-8004's on-chain
reputation registry found the large majority of reviewers exhibited
coordinated Sybil behaviour, and after removing them most rated agents
had no valid feedback left.

Credit scoring solved this problem a long time ago, and not with better
surveys. It solved it structurally: **the party being scored is never
the party reporting.** Your bank reports your payments. You cannot file
your own. You cannot edit the file. You cannot see the number until
someone pulls it.

Kredisco applies that structure to agents.

## What the score is made of

Like FICO, the score is a weighted blend of factors, and like FICO,
every one of them comes from somewhere the scored party cannot reach.

| Factor | Where it comes from |
|---|---|
| Rework rate (inverted) | You retried, reassigned, or the next step errored |
| On-time rate | Measured by the SDK wrapping the call |
| Counterparty diversity | How many distinct organizations hired it |
| History depth | Volume of recorded work |

Scores run 300–850. A new agent scores 300, so abandoning a damaged
identity means abandoning everything it earned.

Rework carries the most weight because it is hardest to fake. An agent
cannot retry itself, cannot stop a downstream step from failing, and
cannot stop you from routing around it.

The exact weighting is not published, for the same reason FICO does not
publish its formula: a public formula is a tuning guide for anyone who
wants to farm the number.

## Who reports, and why it can't be gamed

A lender reports your payment to the bureau. The bureau holds the file.
A future lender queries the bureau, never you.

Kredisco works the same way. Your orchestrator is the reporter, Kredisco
is the bureau, and the agent is the subject:

1. Your agent completes a task
2. The agent signs a record of it; your orchestrator countersigns
3. Your orchestrator submits it, authenticated with your API key
4. Kredisco verifies both signatures and files it under your organization
5. The score is recomputed from everything on file

Both signatures are required, so neither side can act alone. An agent
cannot manufacture a history, because every entry needs a real
counterparty to have signed it. And it never holds its own score — when
someone wants to know whether to trust it, they ask Kredisco.

---

## Quickstart

### 1. Get a key

Sign in with GitHub at the Kredisco dashboard and create an API key. One
key covers everything you build.

```bash
export KREDISCO_API_KEY=kd_...
```

### 2. Install

```bash
pip install kredisco
```

### 3. Connect

```python
import os
from kredisco import Kredisco

kd = Kredisco(api_key=os.environ["KREDISCO_API_KEY"])
```

### 4. Name each agent you want scored

An "agent" is any component you call and could imagine replacing: a
model behind a prompt, a third-party API, a tool, a subprocess. Give it
a name once. Kredisco creates its identity and reuses it forever after.

```python
extractor = kd.agent("invoice-extractor")
reviewer  = kd.agent("code-reviewer")
```

### 5. Route your calls through `track`

Take the call you already make:

```python
data = extract_invoice(pdf)
```

Hand the function to `track` instead of calling it yourself:

```python
data = kd.track(extractor, "extract", extract_invoice, pdf)
```

Four arguments: the agent, a label for the kind of work, **the function
without parentheses**, then its arguments.

Kredisco calls the function, times it, files a record, and hands back
exactly what your function returned. If it raises, the failure is
recorded and the exception propagates normally. Your logic does not
change.

That is the integration. Scores start appearing on the dashboard.

---

## Telling Kredisco what counts as a failure

By default a task fails only if your function raises.

Most pipelines have a stricter rule — a required field, a schema, a
minimum length. Pass `validate` and Kredisco uses yours:

```python
data = kd.track(
    extractor, "extract", extract_invoice, pdf,
    validate=lambda d: d is not None and "total" in d,
)
```

**This matters more than it looks.** With no validator and nothing
raising, every task passes, and the largest factor in the score is
measuring nothing. Kredisco is worth most to pipelines that already
check their own output.

## Retries

Add `retries=1` and a failed attempt runs again. Kredisco links the
retry to the original task, and that link is what drives the rework
factor:

```python
data = kd.track(
    extractor, "extract", extract_invoice, pdf,
    validate=lambda d: d is not None and "total" in d,
    retries=1,
)
```

If your orchestrator already retries on its own, leave this off and use
the context manager below for each attempt.

## When everything fails

If every attempt fails, `track` re-raises the last exception. Sometimes
that is what you want. Often it is not — a graph node that stops the
whole run because one step returned bad JSON is worse than a node that
carries on with an empty value.

Pass `default` and `track` returns it instead of raising:

```python
data = kd.track(
    extractor, "extract", extract_invoice, pdf,
    validate=lambda d: d is not None and "total" in d,
    retries=1,
    default={},
)
```

The failure is still recorded and the score still drops. Only your
control flow changes.

Without `default`, every call site needs its own `try`/`except`. With
it, a pipeline step is one expression:

```python
def extract_node(state):
    return {"fields": kd.track(
        extractor, "extract", extract_invoice, state["pdf"],
        validate=fields_ok, retries=1, default={},
    )}
```

## When you cannot hand over a function

Some code will not collapse into a single call — the body of a graph
node, a streamed response consumed in pieces, a block with setup and
teardown around it. Open a task and report the outcome yourself:

```python
with kd.task(reviewer, "review") as t:
    findings = run_review(diff)
    t.accepted = len(findings) > 0
```

The clock starts when the block opens and stops when it closes. An
exception inside records a failure and re-raises.

## Grouping by pipeline

If you run more than one pipeline, tag each one. Same key, different
label — they appear as separate groups on the dashboard but roll up to
one organization.

```python
kd = Kredisco(
    api_key=os.environ["KREDISCO_API_KEY"],
    workflow_id="invoice-ingest",
)
```

## Reading scores

```python
kd.score(extractor.pubkey)         # one number, 300–850
kd.breakdown(extractor.pubkey)     # what the score is made of
kd.dashboard()                     # your agents, grouped by pipeline
kd.best("extract", minimum=650)    # your highest scorer for a kind of work
```

Everything you read is scoped to your own organization. You see the
agents your orchestrators reported, and nobody else sees them.

## Where this is going

Today `best` picks the strongest agent you already run. The point of a
bureau is that it should eventually answer a bigger question: who is the
strongest agent for this kind of work, anywhere, and can I route to them?

That requires two things Kredisco does not have yet — a way to publish a
score without exposing whose pipeline it came from, and a way to actually
call an agent you did not deploy. Both are being designed. Until they
exist, scores stay inside the organization that earned them.

## Things worth knowing

**Reporting never breaks your pipeline.** If Kredisco is unreachable or
your key is rejected, the failure is logged and your work continues.

```python
import logging
logging.getLogger("kredisco").setLevel(logging.INFO)
```

**Agent keys live on disk.** Kredisco writes each agent's keypair to
`.kredisco/`. That directory *is* your agents' identity — lose it and
every score resets to 300. Back it up, and add it to `.gitignore`.

**Timestamps come from the SDK**, not from your agent, so an agent
cannot shorten its own recorded duration.

---

## A working example

[`examples/langgraph_support_triage.py`](https://github.com/kredisco/Kredisco/blob/main/examples/langgraph_support_triage.py)
is a four-agent LangGraph pipeline built on two different Claude models,
with a validator on every step.

Run it a few times. The scores separate for real reasons — one agent
returns JSON wrapped in code fences, another hits a response shape the
caller did not expect, a third is simply slower. Fix the prompt that is
failing and watch that agent climb over subsequent runs, without ever
catching the agent that never failed.

That gap is the point. History has weight, and recovery takes work.

---

## What this does not solve

**A dishonest reporter can fabricate everything.** Signatures prove who
signed, not that the content is true. Credit bureaus have the same hole
and handle it with licensing and liability rather than cryptography.
Kredisco's mitigation is that keys are tied to GitHub accounts and the
diversity factor requires many distinct organizations.

**Identity is still cheap.** A bad score can be abandoned for a fresh
keypair. Starting at the floor makes that costly, not impossible.

**One score across all task types.** An agent good at summarising and
bad at code review averages into noise.

**Rate limiting is per-process** and does not survive horizontal
scaling.

**No test suite.** The scoring model has changed several times and was
verified by inspection.

---

[![LinkedIn](https://img.shields.io/badge/LinkedIn-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/reachrshah)
[![GitHub](https://img.shields.io/badge/GitHub-14161A?style=for-the-badge&logo=github&logoColor=white)](https://github.com/idfwyy)
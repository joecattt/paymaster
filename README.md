# paymaster — independent control and evidence for autonomous software

**Your card statement says $4,182 to OpenRouter. It does not say which agent,
under whose authority, or for which client. paymaster is the layer that does.**

**This is a reference implementation, not a complete financial control system.**

## One concrete example, end to end

This one is not hypothetical. It was reported by an operator of a pay-per-call
tool marketplace — a router that pays external sellers on a buyer's behalf under
per-payer spend ceilings — reviewing this repo in August 2026, and it is quoted
with the details that identify them removed:

> a local process spent about $11 in a day while our telemetry recorded three
> cents, because that process had no telemetry attached at all

- **actor** — a process nobody had instrumented. That is the normal case, not
  the edge case.
- **event** — a day of upstream API calls against a shared account.
- **rule** — a per-payer spend ceiling that the unmetered process was never
  routed through, so it was never evaluated against anything.
- **reader** — the operator, who has to tell a buyer what a call cost, and who
  discovered the shortfall by accident rather than by alarm.
- **why they care** — their own telemetry said three cents and was *internally
  consistent while being wrong by 366×*. Nothing in the system was positioned to
  contradict it, because everything in the system derived from the same source.

paymaster's answer to exactly this: `coverage.assess()` compares the sum of what
the ledger knows against the provider's **own** aggregate total, and returns
`UNACCOUNTED` with the size of the gap — proof that hidden spend exists, without
claiming to know what it was. `assess_per_key()` goes further and names which
principal the shortfall sits under. It is a smoke alarm, not a camera, and the
docstring says so in those words.

That is the shape of the whole product: the known transaction reconciles to the
millionth of a cent (`reconcile: MATCH`) while `coverage` separately reports
`UNACCOUNTED, gap: $0.1996` on the demo receipt. **"This transaction reconciles"
and "the account is fully covered" are different claims**, and a system that
blurs them will report three cents right up until someone emails you.

## "My card issuer already reconciles this. Why do I need you?"

The most important question anyone has asked about this project, and the answer
is partly *you don't*.

If your agent spends on a card, the issuer is authoritative on **amount**, gives
you real **control** (limits, freezes, merchant locks) and real **recourse**
(chargebacks). paymaster does none of that, holds no wallet, moves no money, and
**cannot get between your agent and that card.** If your question is "how much
did it spend and how do I cap it," use the card and stop reading.

What the statement cannot tell you, at any price:

| the card issuer knows | paymaster records |
|---|---|
| a merchant was paid $4,182 in August | 12,400 individual actions, each attributed to an authenticated principal |
| the account holder authorised the card | which policy version authorised *that* action, pinned by hash |
| the amount, at month granularity | provider-reported cost per call, cross-checked against an independent estimate |
| nothing about purpose | the intent declared at the time — recorded as evidence, never treated as truth |
| nothing about what it missed | an explicit coverage verdict when spend happened outside the governed route |

So: the card is the **control** plane, paymaster is the **attribution** plane.
They are not substitutes, and if you don't need per-action attribution you do
not need this.

## How it gets "in the middle" — and where it can't

It doesn't intercept anything. Actions reach it because the operator routes
them through it (SDK call, the CLI's `ingest`, or an MCP tool), then it
reconciles against the provider's own billing record. That routing is
**voluntary**, which means:

- **An agent holding raw provider credentials bypasses it entirely.** This is
  the real limit, it is not fixable in software here, and the receipt reports
  the resulting gap as `UNACCOUNTED` rather than hiding it.
- The gate is **shadow mode by design** — it records that it *would have*
  denied, and the action proceeds anyway. A would-DENY is not a prevented loss,
  and the receipt says which one it is.

The enforceable version of this is not a receipt at all — it is a spend path the
agent cannot route around: a virtual card per agent, a provider-side key with a
hard cap, or an on-chain allowance contract. paymaster is the evidence layer you
still need *after* choosing one of those, because none of them attribute an
action to a principal, a policy version, and a declared purpose.

## Origin

Created by Joseph Anthony Reyna (JoeCat) in 2026. This repository is the
original reference implementation of paymaster's receipt model. See
[ORIGIN.md](ORIGIN.md) for the full provenance record, [CHANGELOG.md](CHANGELOG.md)
for releases, and [AUTHORS.md](AUTHORS.md) for credit.

When software spends money on its own, someone must be able to prove afterward
what it was allowed to do, what it did, and what it actually cost — across
vendors, without trusting any single party's word. This repo is a working,
tested implementation of that evidence chain:

authenticated principal → policy-hashed decision → provider transaction →
external cost reconciliation → tamper-evident receipt — **with UNKNOWN as a
first-class state** whenever external reality hasn't answered yet.

The centerpiece demo is a receipt that **admits its own limit in the same
breath as its proof**: the known transaction reconciles to the millionth of a
cent (`reconcile: MATCH`) while the coverage field reports real spend outside
the governed route (`coverage: UNACCOUNTED, gap: $0.1996`). "The transaction we
know about reconciles" and "the account is fully covered" are different claims,
and the receipt refuses to blur them. When a provider response is lost, the
verdict is UNKNOWN — never an inferred $0.

## The nine fictions
The intellectual core — each one a mistake caught by experiment: would-DENY ≠
prevented loss · integrity ≠ completeness · declaration ≠ legitimacy ·
fail-closed ≠ safety · local record ≠ external truth · known-set reconciliation
≠ coverage · model consensus ≠ market evidence · **a capped result ≠ a
measurement** · **the conservative-looking tie-break ≠ the safe one**.

The last two were paid for by someone else — a marketplace operator who read
this spec and reported two live losses of that shape: a "tools used in 30 days"
figure that was really the length of a LIMIT-20 query (true number: 281), and a
price disagreement resolved by taking the higher value, which quietly held a
stale price for nine days after a tenfold cut. Full write-up in
[RECEIPT-SPEC.md §8](RECEIPT-SPEC.md).

## The centerpiece command

```
$ paymaster explain 22706
WHO        prove-nonzero  [asserted]
WHAT       RECONCILED via openrouter/openai/gpt-4o-mini
AUTHORITY  DENY (ORPHAN_NO_BUDGET) policy=85010f7c...  [derived: temporal link]
COST       $0.00000315  [reconciled, source=provider-record]
RECONCILE  MATCH vs provider record gen-1787476662...
GRADE      derived (weakest populated field)
GAPS       no consideration chain — direct API call
```

A real receipt for a real charge — note it reports the gate would have DENIED
an action that executed anyway (shadow mode), and grades the whole receipt by
its weakest link. An auditable answer to "what did the autonomous system just
do?", including the parts that are awkward.

## What it is NOT
- It does not move money, hold keys, or execute payments.
- It does not block anything (the gate is shadow-mode by design).
- **Agents holding raw provider credentials bypass it entirely.** It governs
  the routes you send through it, and says so.
- It cannot prove "all transactions accounted for" — only that the known set
  reconciles and whether aggregate drift shows unaccounted spend exists.

## Quickstart

```bash
git clone https://github.com/joecattt/paymaster.git
cd paymaster
python3 -m venv .venv && source .venv/bin/activate
pip install pytest jsonschema

# run the test suite (97 tests, offline, no network/spend)
PYTHONPATH=src python3 -m unittest discover -s tests -q

# see the full command list (starts empty — you feed it your own ledger)
PYTHONPATH=src ./bin/paymaster

# see a real receipt without touching your own data
cat examples/receipt-real-money.json
```

`bin/paymaster` is a standalone script (`src/` on `PYTHONPATH`, no packaging
step). It reads/writes state under `~/.local/state/paymaster` by default —
empty until you run `ingest` or `x402` against your own spend events.

## MCP server

An MCP client (Claude Desktop, Claude Code, any MCP host) can drive paymaster
directly. Every tool shells out to `bin/paymaster` — same binary as the CLI,
nothing reimplemented.

```bash
pip install "mcp>=1.6,<2"
PYTHONPATH=src python3 -m mcp_server.server
```

```json
{
  "mcpServers": {
    "paymaster": {
      "command": "python3",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/paymaster",
      "env": { "PYTHONPATH": "/path/to/paymaster/src" }
    }
  }
}
```

Exposed: `ingest`, `check`, `report`, `consider`, `coverage`, `verify`,
`explain`, `reconcile_counters` — the read/reconcile surface. Deliberately
**not** exposed: `grant`, `revoke-cap`, `enroll` (capability and key
management stay CLI-only, human-invoked) and `x402` (needs on-disk payment
files). An MCP client gets visibility into what an agent spent and whether it
reconciles — not the keys to mint or revoke authority.

## Trial and license

Said up front rather than sprung at the wall: **`ingest` and `check` stop
working after $50 of priced spend has passed through your ledger, unless you
activate a license ($49, one-time, not a subscription).** You get a warning at
80%, and `paymaster license status` tells you where you stand at any time.

Never gated, at any spend level: `report`, `verify`, `explain`, `coverage`,
`prove-nonzero` — the entire read and audit surface. A tool whose argument is
"check this yourself instead of trusting me" cannot put the checking behind a
paywall, so it doesn't.

Three things stated plainly, because you will find all of them anyway:

- **The license is a request, not a lock.** This is MIT source. Deleting the
  check is one edit, the license explicitly permits it, and `PAYMASTER_LICENSE=0`
  does it for you without editing anything. It is here to ask people who get
  real value from this to pay for it. It cannot make anyone.
- **Spend that cannot be priced does not count** against the trial. It is
  excluded, never guessed at $0 — the same rule the receipts follow.
- **Verification is offline.** Ed25519 signature, checked against a public key
  compiled into the source. No phone-home, no license server, nothing to
  contact and nothing that can lock you out later. A tool that demanded you
  trust an unverifiable remote check would be contradicting its own README.

```bash
paymaster license status            # where you stand
paymaster license activate <key>    # after buying
PAYMASTER_LICENSE=0 paymaster ingest  # the off switch
```

If a key won't activate: https://github.com/joecattt/paymaster/issues

## Scope, painfully clear

Point-by-point answers on trust model, rules, implementation and how this
differs from a card issuer, OPA, EAS or an on-chain allowance are in
[ANSWERS.md](ANSWERS.md) — including the one weakness the README understates:
the chain anchor is git-tracked, which proves repository continuity but is
witnessed by the same operator who writes the ledger.
This implementation demonstrates authorization, reconciliation, evidence
linkage, coverage-gap detection, and uncertainty handling. It does **not**
establish complete transaction coverage, does **not** control unmanaged
provider credentials, and does **not** claim production financial-control
completeness. Its git anchor proves repository continuity, not external
witness. See RECEIPT-SPEC.md for the full negative specification.

**Safe by default:** the test suite is offline and free. No command makes a
paid request without an explicit `--confirm-spend` flag.

MIT. Built by an independent researcher; adversarial review welcome — the spec
is looking for people who can break it.

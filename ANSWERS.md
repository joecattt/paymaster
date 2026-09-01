# ANSWERS

Direct answers to the questions a reviewer should ask before trusting any of
this. Written after Roberto Capodieci's review (2026-09-01), whose central
objection — *"if the agent has a credit card, how do you get in the middle? Why
would I need you?"* — is answered first, because everything else depends on it.

Where the answer is "not built" or "you don't need this", it says so.

---

## The central objection: why not just the card issuer?

Partly, you should. A card issuer is authoritative on amount, gives real control
(limits, freezes, merchant locks) and real recourse (chargebacks). paymaster has
none of that. It holds no wallet, moves no money, and **cannot interpose itself
between an agent and a card it does not sit in front of.**

It answers a different question. The statement says *a merchant was paid $4,182
in August*. It does not say which of eleven agents, under which policy version,
for which client, with what declared purpose. That attribution is the product.
If you don't need per-action attribution, you don't need this.

**How it gets in the path at all:** it doesn't intercept — the operator *routes*
through it (SDK, `ingest`, or an MCP tool). Voluntary routing means an agent
holding raw provider credentials bypasses it entirely. That is the real limit,
it is not solvable in this repo, and the receipt reports the resulting shortfall
as `coverage: UNACCOUNTED` instead of hiding it.

**The enforceable version is not a receipt.** It is a spend path the agent
cannot route around — a virtual card per agent, a provider-side key with a hard
cap, or an on-chain allowance contract. Choose one of those for control. This is
the evidence layer you still want afterward, because none of them attributes an
action to a principal, a policy version, and a stated purpose.

---

## Purpose and users

**Concrete example.** See the README opening: an agency rebilling AI usage to
eleven clients, one disputed $4,182 line item, receipts that attribute 12,400
calls to `agent-7` under a hash-pinned policy, with the provider's own reported
cost cross-checked against an independent estimate.

**Who pays, and what does a plain signed log not give them?** The party who must
*rely* on someone else's number — the client being rebilled, the auditor, the
insurer. Over a signed log you get: a decision bound to a policy *hash* so the
rule in force is pinned; a cost cross-checked against the provider's own record
rather than self-reported; `UNKNOWN` as a first-class verdict instead of an
inferred zero; and a coverage verdict that reports spend the system never saw.
The last one is the point — most tools of this shape imply completeness they
cannot support.

**Is the customer the operator or the relying party?** The relying party. The
operator will accept their own logs. That makes distribution hard and is stated,
not hidden.

---

## Trust model

**Who signs, and who can verify without trusting the operator?** The ledger is
append-only and hash-chained (`src/paymaster/ledger.py`): every line commits to
the previous line's hash, so edits and deletions are detectable, and `paymaster
verify` walks the chain and exits 2 if it breaks. Anyone with a copy of the
ledger can recompute it.

**If you are the man in the middle, what stops a fabricated or omitted receipt?**
Nothing stops fabrication of an event that never happened — with one asymmetry
worth having: a fabricated *cost* has to survive reconciliation against the
provider's own billing record, which the operator does not author.
Omission is the weaker side. The chain makes edits detectable, never omissions —
a call that never entered the ledger leaves no gap. Aggregate coverage checking
is the partial answer: when total account spend exceeds the governed set, the
receipt reports `UNACCOUNTED` with the size of the gap, which surfaces the
*existence* of hidden spend without identifying it.

**Known weakness — the anchor is self-witnessed.** The chain tail is witnessed
into a git-tracked `anchors.jsonl` and committed. That proves repository
continuity, and the README already says so, but git history is controlled by the
same operator who controls the ledger. It is **not** the independent witness
Roberto asked for. The sibling project
[hash2trace](https://github.com/joecattt/hash2trace) already anchors its chain
tip to Bitcoin via OpenTimestamps; porting that here is the single highest-value
next change to this repo, and until it lands, treat the anchor as an internal
consistency check rather than third-party proof.

**How do you know the action really happened?** Reconciliation against the
provider's record is the external check — the local estimate is computed
independently (published price × usage) and compared. `intent_declared` is
recorded as evidence and explicitly never treated as truth. Principal
attribution is graded: `authenticated` vs `asserted`, and the receipt is graded
by its weakest populated field.

---

## Rules and policy

**Who writes the rules?** The operator: budgets and capabilities
(`src/paymaster/budgets.py`, `capability.py`). The deciding policy is hashed
into every receipt (`policy_hash`), so changing the rules later cannot
retroactively change what a past receipt says authorised it.

**Deterministic, or an LLM?** Deterministic. No model sits in the decision or
reconciliation path; receipts are reproducible.

**What happens on failure?** Nothing is blocked. The gate is **shadow mode by
design**: it records `DENY` and the action proceeds. A would-DENY is not a
prevented loss — that is one of the "seven fictions" this implementation
explicitly refuses to trade on.

---

## Implementation

**Interface.** A standalone CLI (`bin/paymaster`, `PYTHONPATH=src`, no packaging
step) and an MCP server exposing the read/reconcile surface. Capability and key
management (`grant`, `revoke-cap`, `enroll`) are deliberately CLI-only and
human-invoked — an MCP client gets visibility, never the ability to mint
authority.

**Where state lives.** Entirely off-chain: a JSONL ledger under
`~/.local/state/paymaster`, plus the git-tracked anchors file. Nothing is
published to any chain today.

**Latency and cost.** Local file append and a hash — real-time. Reconciliation
against a provider record is post-hoc, whenever the provider's record becomes
available; until it does, the verdict is `UNKNOWN`, never an inferred `$0`.

**Token or fee mechanism?** Neither. MIT-licensed software, no token.

---

## Comparison and differentiation

**Versus a card issuer / virtual-card provider.** They control and settle; they
cannot attribute. See above. Complementary, not competing.

**Versus a provider dashboard (OpenAI, OpenRouter usage pages).** Same data,
same party, no independent cross-check, no policy binding, and no statement of
what is missing. paymaster's estimate is computed independently *and* compared
to the provider's own record — the whole point is that two parties agree, not
that one asserts.

**Versus OPA.** OPA decides and enforces in-line. paymaster records the decision
and does not enforce. They compose.

**Versus EAS / an on-chain attestation.** EAS is right when the attestation must
be publicly referenceable. Here the records are commercial spend data that
usually stays private; nothing is published today, which is a deliberate privacy
posture and simultaneously the reason the anchor is weak (see above).

**Versus a smart-contract allowance / escrow.** That is the genuinely enforceable
answer to "the agent can't route around it", and it is *better* than this for
control. It still does not tell you which agent, which policy version, or what
purpose — which is what these receipts carry.

**If ERC-4337 is the model, what is the EntryPoint and the bundler?**
Honest answer: there is no equivalent, and the name oversells. A 4337 paymaster
is inside the execution path and can refuse; this one is beside the path and
records. The word was borrowed for the *receipt* pattern — inspect, apply
policy, leave an auditable trail — not for the enforcement power, and the
comparison caused more confusion than it removed.

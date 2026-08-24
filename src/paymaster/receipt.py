"""Decision Receipt v1 — the product's central object (authorized increment).

A deterministic, machine-readable, evidence-graded answer to: WHO acted, under
WHAT authority, WHAT policy decided, WHAT alternatives were considered, WHAT
happened, WHAT evidence supports it, and WHAT remains unproven.

Rules this object enforces structurally:
- every field carries {value, source, grade}; the receipt's overall grade is
  the WEAKEST grade among populated material fields (RECEIPT-SPEC §3);
- absent evidence becomes an entry in `gaps`, never a guessed value;
- content is deterministic: receipt_id = sha256(canonical(body)); regenerating
  from the same inputs yields the same id; changed telemetry changes the id;
- a receipt can never be silently strengthened — grades are computed, not set.
"""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timedelta

RECEIPT_VERSION = "1.0"
GRADE_ORDER = ["missing", "derived", "asserted", "authenticated", "signed",
               "provider", "reconciled"]


def _f(value, source, grade):
    return {"value": value, "source": source, "grade": grade}


def _canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"))


def _parse_evidence(ev: str) -> dict:
    out = {}
    for part in (ev or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _nearest_decision(decisions, principal, provider, ts, tolerance_s=900):
    """Temporal linkage only — the decision log has no record FK. Anything
    found here is graded DERIVED and says so."""
    try:
        t0 = datetime.fromisoformat(ts)
    except ValueError:
        return None
    best, best_dt = None, timedelta(seconds=tolerance_s)
    for d in decisions:
        if d.get("principal_id") != principal or d.get("provider") != provider:
            continue
        try:
            dt = abs(datetime.fromisoformat(d["ts"]) - t0)
        except (ValueError, KeyError):
            continue
        if dt <= best_dt:
            best, best_dt = d, dt
    if best is not None:
        best = dict(best, _link_delta_s=round(best_dt.total_seconds(), 1))
    return best


def build(rec: dict, *, seq=None, decisions=(), consideration=None,
          coverage=None, capability=None) -> dict:
    """Assemble a Decision Receipt from a ledger record + optional linked
    evidence. Every input is existing telemetry — nothing is instrumented."""
    ev = _parse_evidence(rec.get("evidence", ""))
    gaps = []
    body = {
        "receipt_version": RECEIPT_VERSION,
        "who": {
            "principal": _f(rec["principal"], "ledger", rec["attribution"]),
            "principal_id": _f(rec["principal_id"], "ledger", rec["attribution"]),
        },
        "what": {
            "provider": _f(rec["provider"], "ledger", rec["attribution"]),
            "model": _f(rec.get("model", ""), "ledger", rec["attribution"]),
            "state": _f(rec["state"], "ledger", "asserted"),
            "tokens_in": _f(rec["tokens_in"], "provider-usage-field", "asserted"),
            "tokens_out": _f(rec["tokens_out"], "provider-usage-field", "asserted"),
            "ts": _f(rec["ts"], "ledger", "asserted"),
        },
        "authority": {},
        "alternatives": {},
        "economics": {},
        "integrity": {
            "record_id": _f(rec["id"], "ledger", "asserted"),
            "ledger_seq": _f(seq, "ledger", "asserted") if seq else _f(None, "ledger", "missing"),
        },
        "gaps": gaps,
    }

    # authority: temporal linkage to the decision log, honestly graded DERIVED
    d = _nearest_decision(decisions, rec["principal"], rec["provider"], rec["ts"])
    if d:
        src = f"decision-log(temporal-link +/-{d.get('_link_delta_s','?')}s)"
        body["authority"] = {
            "decision": _f(d["decision"], src, "derived"),
            "reason_code": _f(d["reason_code"], src, "derived"),
            "policy_hash": _f(d["policy_hash"], src, "derived"),
            "link_delta_s": _f(d.get("_link_delta_s"), "receipt", "derived"),
        }
        if d.get("_link_delta_s", 0) and d["_link_delta_s"] > 60:
            gaps.append(f"decision link is loose ({d['_link_delta_s']}s gap) — "
                        "temporal only, may mislink if actions cluster")
    else:
        gaps.append("no gate decision linked — action predates the gate, ran "
                    "off-route, or no temporal match within tolerance")

    # capability chain: a VERIFIED chain is the strongest authority evidence
    # available today (grade: authenticated — software HMAC, not hardware).
    if capability is not None:
        if capability.get("valid"):
            body["authority"]["capability"] = _f(capability.get("effective"),
                "capability-chain(verified)", capability.get("grade", "authenticated"))
        else:
            gaps.append(f"capability chain INVALID: {capability.get('reason')}")
    else:
        gaps.append("no capability chain — authority is policy-inferred, not presented")
    # attestation slot: reserved for hardware/TEE evidence. Always a gap today;
    # filling it is the market's job (EAT/TEE/NIST agent identity), not simulation.
    gaps.append("no execution attestation — runtime identity unproven (top ladder rungs empty)")

    # alternatives: consideration chain if the caller derived one from routing telemetry
    if consideration:
        body["alternatives"] = {
            "providers_considered": _f(consideration, "routing-telemetry", "derived")}
    else:
        gaps.append("no consideration chain — call did not pass through routed "
                    "fallback telemetry (direct API or single-provider)")

    # economics: reconciliation state from evidence + amounts
    if rec.get("usd") is not None:
        body["economics"]["amount_usd"] = _f(rec["usd"],
            "provider-record" if ev.get("reconciled") else "local",
            "reconciled" if ev.get("reconciled") == "MATCH" else "asserted")
    if ev.get("gen"):
        body["economics"]["provider_txn"] = _f(ev["gen"], "provider", "provider")
    if ev.get("reconciled"):
        body["economics"]["reconcile"] = _f(ev["reconciled"],
            "reconcile_external(provider cost API)", "reconciled")
        if ev.get("local_est"):
            try:
                body["economics"]["local_estimate"] = _f(float(ev["local_est"]),
                    "published-price x usage", "derived")
            except ValueError:
                pass
    else:
        gaps.append("no external reconciliation — provider's own cost record "
                    "not consulted for this action; amount is unverified")
    if rec.get("usd") is None and not ev.get("gen"):
        gaps.append("no economic evidence — non-priced action or free tier")

    # coverage context (optional, carries its own observation time)
    if coverage:
        body["economics"]["coverage"] = _f(coverage, "coverage-oracle(aggregate)", "derived")

    # overall grade = weakest populated material field
    grades = []
    for section in ("who", "what", "authority", "economics"):
        for f in body[section].values():
            if isinstance(f, dict) and f.get("grade") and f["grade"] != "missing":
                grades.append(f["grade"])
    body["evidence_grade"] = min(grades, key=GRADE_ORDER.index) if grades else "missing"

    body["receipt_id"] = hashlib.sha256(_canon(
        {k: v for k, v in body.items() if k != "receipt_id"}).encode()).hexdigest()
    return body


def render(r: dict) -> str:
    """Human answer to 'what the hell did the autonomous system just do?'"""
    L = []
    g = lambda s, k: (r.get(s, {}).get(k) or {}).get("value")
    gg = lambda s, k: (r.get(s, {}).get(k) or {}).get("grade", "?")
    L.append(f"WHO        {g('who','principal')}  [{gg('who','principal')}]")
    L.append(f"WHAT       {g('what','state')} via {g('what','provider')}"
             f"{('/' + g('what','model')) if g('what','model') else ''} at {g('what','ts')}")
    if r.get("authority"):
        L.append(f"AUTHORITY  {g('authority','decision')} ({g('authority','reason_code')}) "
                 f"policy={g('authority','policy_hash')}  [derived: temporal link]")
    if r["economics"].get("amount_usd"):
        amt = r["economics"]["amount_usd"]
        L.append(f"COST       ${amt['value']:.8f}  [{amt['grade']}, source={amt['source']}]")
    if r["economics"].get("reconcile"):
        L.append(f"RECONCILE  {g('economics','reconcile')} vs provider record "
                 f"{g('economics','provider_txn')}")
    L.append(f"GRADE      {r['evidence_grade']} (weakest populated field)")
    if r["gaps"]:
        L.append("GAPS       " + " | ".join(r["gaps"]))
    L.append(f"RECEIPT    v{r['receipt_version']} id={r['receipt_id'][:16]}…  (deterministic)")
    return "\n".join(L)

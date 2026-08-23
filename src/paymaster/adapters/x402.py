"""Adapter: x402 v2 payment payload + settlement -> SpendRecord.

Field names follow specs/x402-specification-v2.md VERBATIM (vendored in
vendor/ — the round-1 panel seat that invented 'OpenAPI-X.402' is exactly
the failure mode this file guards against):
  PaymentPayload: x402Version, resource, accepted{scheme, network, amount,
    asset, payTo, maxTimeoutSeconds, extra}, payload{signature,
    authorization{from, to, value, validAfter, validBefore, nonce}}
  SettleResponse: success, transaction, network, payer, amount, errorReason
Amounts are atomic units of `asset`; USDC has 6 decimals.
"""
from __future__ import annotations
from datetime import datetime, timezone

from ..schema import record, make_id

# asset contract -> (symbol, decimals). Extend as assets are actually used.
KNOWN_ASSETS = {
    "0x036CbD53842c5426634e7929541eC2318f3dCF7e": ("USDC", 6),  # Base Sepolia (spec example)
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913": ("USDC", 6),  # Base mainnet
}


def parse(payment_payload: dict, settle_response: dict, principal: str = "agent",
          allow_sponsored: bool = False):
    if payment_payload.get("x402Version") != 2:
        raise ValueError(f"unsupported x402Version: {payment_payload.get('x402Version')!r}")
    acc = payment_payload["accepted"]
    settled = settle_response.get("success") is True
    auth0 = payment_payload.get("payload", {}).get("authorization", {})
    # Spend binds to the SIGNED authorization.value — SettleResponse.amount is a
    # server assertion and must not be able to lower what the budget sees
    # (Ox review #3, 2026-08-22). A discrepancy is recorded, never trusted.
    atomic = int(auth0.get("value") or acc["amount"])
    discrepancy = ""
    settle_amt = settle_response.get("amount")
    if settle_amt is not None and int(settle_amt) != atomic:
        discrepancy = f";settle_amount={settle_amt}!=authorized={atomic}"
    payer = settle_response.get("payer")
    if payer and auth0.get("from") and payer.lower() != auth0["from"].lower():
        if not allow_sponsored:
            raise ValueError(f"payer {payer} != authorization.from {auth0['from']} "
                             "(sponsored settle? pass allow_sponsored=True to accept)")
        discrepancy += f";sponsored_payer={payer}"
    symbol, decimals = KNOWN_ASSETS.get(acc["asset"], (acc["asset"][:10], None))
    usd = None
    if symbol == "USDC" and decimals is not None:
        usd = atomic / 10 ** decimals  # 1 USDC treated as $1; stablecoin par assumption
    auth = auth0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if auth.get("validAfter"):
        ts = datetime.fromtimestamp(int(auth["validAfter"]), tz=timezone.utc)\
            .isoformat(timespec="seconds")
    tx = settle_response.get("transaction", "")
    # PAID is not DELIVERED: settlement moved money; nothing here proves the
    # purchased resource arrived. §9 settlement_pending is its own state.
    if settled:
        state = "PAID"
    elif settle_response.get("errorReason") == "settlement_pending":
        state = "PAYMENT_PENDING"
    else:
        state = "FAILED"
    return record(
        ts=ts,
        rail="x402",
        provider=f"x402:{acc['payTo']}",
        principal=principal,
        # The signing wallet IS the economic actor; the passed-in label is
        # display only. Signature-bound = the strong attribution tier.
        principal_id=auth.get("from", principal),
        attribution="signed",
        state=state,
        model=acc.get("network", ""),
        usd=usd,
        currency=symbol,
        evidence=(f"tx={tx}" if tx else "unsettled") + discrepancy,
        rid=make_id("x402", tx or auth.get("nonce", ""), acc["payTo"], atomic),
    )

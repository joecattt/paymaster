"""Pricing: converts token counts to dollars ONLY from an explicit table.

config/pricing.json rows carry `asOf` and `source`; a provider absent from
the table prices to None (unknown), never to a guess. Free tiers price to 0
with the free-tier note — that IS the honest number.
"""
from __future__ import annotations
import json
import os

DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "config", "pricing.json")


def load(path: str = DEFAULT) -> dict:
    with open(path) as f:
        return json.load(f)["providers"]


def price(rec: dict, table: dict):
    """Return usd for a record, or None if unpriceable. x402 records carry
    their own settled usd and are passed through untouched."""
    if rec["usd"] is not None:
        return rec["usd"]
    p = table.get(rec["provider"])
    if p is None:
        return None
    return (rec["tokens_in"] / 1e6) * p["usd_per_mtok_in"] + \
           (rec["tokens_out"] / 1e6) * p["usd_per_mtok_out"]

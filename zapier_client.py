"""
Zapier Webhook client for Budget App
======================================
Sends statement data to a Zapier "Catch Hook" webhook, which routes
it to your existing Linear connection inside Zapier.

Setup (one-time, ~30 seconds in Zapier):
  1. New Zap → Trigger: "Webhooks by Zapier" → "Catch Hook"
  2. Copy the webhook URL Zapier gives you
  3. Action: Linear → Create Issue (use your existing connection)
     Map fields:
       Title       → {{title}}
       Description → {{description}}
       Priority    → {{priority}}
       Label       → {{label}}
  4. Turn the Zap on
  5. Set the URL in your environment:
       export ZAPIER_WEBHOOK_URL="https://hooks.zapier.com/hooks/catch/..."

The agent fires one webhook call per issue type (statement, payment due,
past-due alert, overlimit alert).
"""

import os
import urllib.request
import urllib.error
import json
from datetime import date


def _post(url: str, payload: dict) -> bool:
    """POST JSON to a Zapier webhook URL. Returns True on success."""
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url,
        data    = data,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        print(f"    Zapier HTTP error {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"    Zapier error: {e}")
        return False


def post_statement_issues(webhook_url: str, stmt: dict):
    """
    Fire Zapier webhooks for a processed statement.
    Creates up to 4 issues in Linear via your existing Zapier→Linear Zap.
    """
    account  = stmt.get("account_name", "Unknown Account")
    last4    = stmt.get("account_last4", "????")
    holder   = stmt.get("holder", "")
    period   = f"{stmt.get('statement_period_start','')} → {stmt.get('statement_period_end','')}"
    balance  = stmt.get("new_balance",      0) or 0
    minpay   = stmt.get("min_payment",      0) or 0
    due      = stmt.get("due_date",         "")
    interest = stmt.get("interest_total",   0) or 0
    past_due = stmt.get("past_due",         0) or 0
    overlimit= stmt.get("overlimit",        0) or 0
    purchases= stmt.get("purchases_total",  0) or 0
    fees     = stmt.get("fees_total",       0) or 0
    txns     = stmt.get("transactions",     [])

    # Build markdown transaction table
    tx_rows = "\n".join(
        f"| {t.get('transaction_date','')} | {t.get('description','')} "
        f"| {'−' if (t.get('amount') or 0) < 0 else ''}${abs(t.get('amount') or 0):,.2f} "
        f"| {t.get('category','')} |"
        for t in txns
    )
    tx_table = (
        "| Date | Description | Amount | Category |\n"
        "|------|-------------|--------|----------|\n"
        + tx_rows
    ) if tx_rows else "_No transactions this period._"

    generated = date.today().strftime("%B %d, %Y")

    # ── 1. Statement processed ────────────────────────────────────────────────
    ok = _post(webhook_url, {
        "title":       f"Statement: {account} ...{last4} ({period})",
        "description": (
            f"## Statement Summary\n"
            f"**Account:** {account} ...{last4} ({holder})\n"
            f"**Period:** {period}\n"
            f"**Generated:** {generated}\n\n---\n\n"
            f"| Field | Amount |\n|-------|--------|\n"
            f"| Previous Balance | ${stmt.get('previous_balance',0) or 0:,.2f} |\n"
            f"| Payments | ${abs(stmt.get('payments_total',0) or 0):,.2f} |\n"
            f"| Purchases | ${purchases:,.2f} |\n"
            f"| Fees | ${fees:,.2f} |\n"
            f"| Interest | ${interest:,.2f} |\n"
            f"| **New Balance** | **${balance:,.2f}** |\n"
            f"| Minimum Payment | ${minpay:,.2f} |\n"
            f"| Due Date | {due} |\n\n---\n\n"
            f"## Transactions\n{tx_table}"
        ),
        "priority": "medium",
        "label":    f"{account} ...{last4}",
        "account":  account,
        "last4":    last4,
        "holder":   holder,
        "balance":  balance,
        "period":   period,
    })
    if ok:
        print(f"    ✓ Zapier: Statement issue triggered")

    # ── 2. Payment due reminder ───────────────────────────────────────────────
    ok = _post(webhook_url, {
        "title":       f"Payment Due: {account} ...{last4} — ${minpay:,.2f} by {due}",
        "description": (
            f"## Payment Reminder\n"
            f"**Account:** {account} ...{last4} ({holder})\n"
            f"**Amount Due:** ${minpay:,.2f}\n"
            f"**Due Date:** {due}\n"
            f"**Current Balance:** ${balance:,.2f}\n\n"
            f"> Pay at least the minimum by **{due}** to avoid late fees."
        ),
        "priority": "high",
        "label":    f"{account} ...{last4}",
        "account":  account,
        "last4":    last4,
        "holder":   holder,
        "min_payment": minpay,
        "due_date": due,
    })
    if ok:
        print(f"    ✓ Zapier: Payment due issue triggered")

    # ── 3. Past due alert (urgent) ────────────────────────────────────────────
    if past_due > 0:
        ok = _post(webhook_url, {
            "title":       f"🚨 PAST DUE: {account} ...{last4} — ${past_due:,.2f}",
            "description": (
                f"## Past Due Alert\n"
                f"**Account:** {account} ...{last4} ({holder})\n"
                f"**Past Due Amount:** ${past_due:,.2f}\n"
                f"**Full Minimum Payment:** ${minpay:,.2f} (includes past due)\n"
                f"**Due Date:** {due}\n\n"
                f"This account is past due. Payment required immediately to avoid "
                f"further fees and credit impact."
            ),
            "priority": "urgent",
            "label":    f"{account} ...{last4}",
            "account":  account,
            "last4":    last4,
            "past_due": past_due,
        })
        if ok:
            print(f"    ✓ Zapier: Past due URGENT issue triggered")

    # ── 4. Overlimit alert (urgent) ───────────────────────────────────────────
    if overlimit > 0:
        ok = _post(webhook_url, {
            "title":       f"🚨 OVERLIMIT: {account} ...{last4} — ${overlimit:,.2f} over",
            "description": (
                f"## Over Limit Alert\n"
                f"**Account:** {account} ...{last4} ({holder})\n"
                f"**Overlimit Amount:** ${overlimit:,.2f}\n"
                f"**Current Balance:** ${balance:,.2f}\n"
                f"**Credit Limit:** ${stmt.get('credit_limit',0) or 0:,.2f}\n\n"
                f"Account is over its credit limit. Pay down immediately to avoid "
                f"declined transactions."
            ),
            "priority": "urgent",
            "label":    f"{account} ...{last4}",
            "account":  account,
            "last4":    last4,
            "overlimit": overlimit,
        })
        if ok:
            print(f"    ✓ Zapier: Overlimit URGENT issue triggered")

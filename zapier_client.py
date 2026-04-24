"""
Zapier MCP client for Budget App
==================================
Calls Linear directly via the Zapier MCP server using your existing
Linear connection — no webhook URL needed.

Available Linear actions used:
  - create_issue      → statement summary, payment due, alerts
  - createProject     → ensures "Budget App" project exists
  - create_comment    → adds transaction table as a comment

Set in environment:
  export ZAPIER_API_KEY="MjIwM2QyNz..."
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import date

ZAPIER_MCP_URL = "https://mcp.zapier.com/api/mcp/mcp"


# ── low-level MCP call ────────────────────────────────────────────────────────
def _mcp(api_key: str, method: str, params: dict, call_id: int = 1) -> dict:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "method":  method,
        "params":  params,
        "id":      call_id,
    }).encode()

    req = urllib.request.Request(
        ZAPIER_MCP_URL,
        data    = payload,
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
            "Accept":        "application/json, text/event-stream",
        },
        method = "POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode()

    # Parse SSE-wrapped response
    matches = re.findall(r"data:\s*(\{.+)", raw)
    for line in matches:
        try:
            d = json.loads(line)
            if d.get("id") == call_id:
                if "error" in d:
                    raise RuntimeError(f"MCP error: {d['error']}")
                return d.get("result", {})
        except json.JSONDecodeError:
            pass
    raise RuntimeError(f"No matching response for id={call_id}. Raw: {raw[:300]}")


def _tool_call(api_key: str, tool: str, args: dict, call_id: int = 1) -> str:
    """Call a Zapier MCP tool and return the text content."""
    result = _mcp(api_key, "tools/call", {"name": tool, "arguments": args}, call_id)
    content = result.get("content", [])
    return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")


def _zapier_action(api_key: str, action_key: str, instructions: str, call_id: int = 1) -> str:
    """Execute a Zapier write action (Linear)."""
    return _tool_call(api_key, "execute_zapier_write_action", {
        "action_key":   action_key,
        "instructions": instructions,
    }, call_id)


# ── public entry point ────────────────────────────────────────────────────────
def post_statement_issues(api_key: str, stmt: dict):
    """
    Create Linear issues via Zapier MCP for a processed statement.
    Creates: statement summary, payment due reminder, past due alert, overlimit alert.
    """
    account  = stmt.get("account_name",    "Unknown Account")
    last4    = stmt.get("account_last4",   "????")
    holder   = stmt.get("holder",          "")
    period   = f"{stmt.get('statement_period_start','')} → {stmt.get('statement_period_end','')}"
    balance  = stmt.get("new_balance",     0) or 0
    minpay   = stmt.get("min_payment",     0) or 0
    due      = stmt.get("due_date",        "")
    interest = stmt.get("interest_total",  0) or 0
    past_due = stmt.get("past_due",        0) or 0
    overlimit= stmt.get("overlimit",       0) or 0
    purchases= stmt.get("purchases_total", 0) or 0
    fees     = stmt.get("fees_total",      0) or 0
    prev_bal = stmt.get("previous_balance",0) or 0
    payments = stmt.get("payments_total",  0) or 0
    txns     = stmt.get("transactions",    [])
    generated = date.today().strftime("%B %d, %Y")

    tx_lines = "\n".join(
        f"  {t.get('transaction_date','')}  {t.get('description',''):<40}  "
        f"{'−' if (t.get('amount') or 0) < 0 else ' '}${abs(t.get('amount') or 0):>8,.2f}  "
        f"{t.get('category','')}"
        for t in txns
    ) or "  No transactions this period."

    # ── 1. Statement Processed ────────────────────────────────────────────────
    stmt_body = (
        f"Create a Linear issue with:\n"
        f"Title: Statement: {account} ...{last4} ({period})\n"
        f"Priority: Medium\n"
        f"Description:\n"
        f"Account: {account} ...{last4} | Holder: {holder} | Generated: {generated}\n"
        f"Period: {period}\n\n"
        f"Previous Balance: ${prev_bal:,.2f}\n"
        f"Payments:         ${abs(payments):,.2f}\n"
        f"Purchases:        ${purchases:,.2f}\n"
        f"Fees:             ${fees:,.2f}\n"
        f"Interest:         ${interest:,.2f}\n"
        f"New Balance:      ${balance:,.2f}\n"
        f"Min Payment Due:  ${minpay:,.2f} by {due}\n\n"
        f"Transactions:\n{tx_lines}"
    )
    try:
        resp = _zapier_action(api_key, "create_issue", stmt_body, call_id=10)
        print(f"    ✓ Linear: Statement issue created")
        if "url" in resp.lower() or "linear.app" in resp.lower():
            url = re.search(r'https://linear\.app\S+', resp)
            if url:
                print(f"      {url.group()}")
    except Exception as e:
        print(f"    ✗ Linear statement issue: {e}")

    # ── 2. Payment Due Reminder ───────────────────────────────────────────────
    pay_body = (
        f"Create a Linear issue with:\n"
        f"Title: Payment Due: {account} ...{last4} — ${minpay:,.2f} by {due}\n"
        f"Priority: High\n"
        f"Description:\n"
        f"Account: {account} ...{last4} | Holder: {holder}\n"
        f"Amount Due: ${minpay:,.2f}\n"
        f"Due Date: {due}\n"
        f"Current Balance: ${balance:,.2f}\n\n"
        f"Pay at least the minimum by {due} to avoid late fees."
    )
    try:
        _zapier_action(api_key, "create_issue", pay_body, call_id=11)
        print(f"    ✓ Linear: Payment due reminder created")
    except Exception as e:
        print(f"    ✗ Linear payment issue: {e}")

    # ── 3. Past Due Alert (Urgent) ────────────────────────────────────────────
    if past_due > 0:
        past_body = (
            f"Create a Linear issue with:\n"
            f"Title: PAST DUE: {account} ...{last4} — ${past_due:,.2f}\n"
            f"Priority: Urgent\n"
            f"Description:\n"
            f"Account: {account} ...{last4} | Holder: {holder}\n"
            f"Past Due Amount: ${past_due:,.2f}\n"
            f"Full Minimum Payment: ${minpay:,.2f} (includes past due)\n"
            f"Due Date: {due}\n\n"
            f"URGENT: This account is past due. Payment required immediately "
            f"to avoid further fees and credit impact."
        )
        try:
            _zapier_action(api_key, "create_issue", past_body, call_id=12)
            print(f"    ✓ Linear: Past due URGENT issue created")
        except Exception as e:
            print(f"    ✗ Linear past due issue: {e}")

    # ── 4. Overlimit Alert (Urgent) ───────────────────────────────────────────
    if overlimit > 0:
        over_body = (
            f"Create a Linear issue with:\n"
            f"Title: OVERLIMIT: {account} ...{last4} — ${overlimit:,.2f} over limit\n"
            f"Priority: Urgent\n"
            f"Description:\n"
            f"Account: {account} ...{last4} | Holder: {holder}\n"
            f"Overlimit Amount: ${overlimit:,.2f}\n"
            f"Current Balance: ${balance:,.2f}\n"
            f"Credit Limit: ${stmt.get('credit_limit', 0) or 0:,.2f}\n\n"
            f"URGENT: Account is over its credit limit. Pay down immediately "
            f"to avoid declined transactions."
        )
        try:
            _zapier_action(api_key, "create_issue", over_body, call_id=13)
            print(f"    ✓ Linear: Overlimit URGENT issue created")
        except Exception as e:
            print(f"    ✗ Linear overlimit issue: {e}")

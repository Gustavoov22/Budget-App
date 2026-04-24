"""
Linear API client for Budget App
=================================
Creates and updates Linear issues whenever statements are processed.

Issue types created:
  - "Statement Processed" — one per PDF, with full summary
  - "⚠ Payment Due"       — reminder per account with due date & amount
  - "🚨 Past Due / Overlimit" — urgent priority when flagged

Set LINEAR_API_KEY in your environment:
  export LINEAR_API_KEY="lin_api_..."
  (Settings → API → Personal API keys in Linear)
"""

import os
import requests
from datetime import date

LINEAR_API = "https://api.linear.app/graphql"
PROJECT_NAME = "Budget App"


class LinearClient:
    def __init__(self):
        self.key = os.environ.get("LINEAR_API_KEY")
        if not self.key:
            raise EnvironmentError(
                "LINEAR_API_KEY not set.\n"
                "Get one at: Linear → Settings → API → Personal API keys\n"
                "Then: export LINEAR_API_KEY='lin_api_...'"
            )
        self.headers = {
            "Authorization": self.key,
            "Content-Type": "application/json",
        }
        self._team_id    = None
        self._project_id = None

    # ── low-level GraphQL ─────────────────────────────────────────────────────
    def _gql(self, query: str, variables: dict = None) -> dict:
        resp = requests.post(
            LINEAR_API,
            json={"query": query, "variables": variables or {}},
            headers=self.headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Linear API error: {data['errors']}")
        return data["data"]

    # ── team ─────────────────────────────────────────────────────────────────
    def get_team_id(self) -> str:
        if self._team_id:
            return self._team_id
        data = self._gql("{ teams { nodes { id name } } }")
        teams = data["teams"]["nodes"]
        if not teams:
            raise RuntimeError("No teams found in Linear workspace.")
        # Use the first team (most workspaces have one)
        self._team_id = teams[0]["id"]
        print(f"  Linear team: {teams[0]['name']} ({self._team_id})")
        return self._team_id

    # ── project ───────────────────────────────────────────────────────────────
    def get_or_create_project(self) -> str:
        if self._project_id:
            return self._project_id

        team_id = self.get_team_id()

        # Check if project already exists
        data = self._gql(
            """
            query($teamId: String!) {
              team(id: $teamId) {
                projects { nodes { id name } }
              }
            }
            """,
            {"teamId": team_id},
        )
        projects = data["team"]["projects"]["nodes"]
        for p in projects:
            if p["name"].lower() == PROJECT_NAME.lower():
                self._project_id = p["id"]
                print(f"  Linear project found: {PROJECT_NAME}")
                return self._project_id

        # Create it
        data = self._gql(
            """
            mutation($name: String!, $teamIds: [String!]!) {
              projectCreate(input: { name: $name, teamIds: $teamIds }) {
                success
                project { id name }
              }
            }
            """,
            {"name": PROJECT_NAME, "teamIds": [team_id]},
        )
        self._project_id = data["projectCreate"]["project"]["id"]
        print(f"  Linear project created: {PROJECT_NAME}")
        return self._project_id

    # ── label helper ─────────────────────────────────────────────────────────
    def get_or_create_label(self, name: str, color: str = "#0EA5E9") -> str | None:
        team_id = self.get_team_id()
        data = self._gql(
            """
            query($teamId: String!) {
              issueLabels(filter: { team: { id: { eq: $teamId } } }) {
                nodes { id name }
              }
            }
            """,
            {"teamId": team_id},
        )
        for lbl in data["issueLabels"]["nodes"]:
            if lbl["name"].lower() == name.lower():
                return lbl["id"]

        data = self._gql(
            """
            mutation($teamId: String!, $name: String!, $color: String!) {
              issueLabelCreate(input: { teamId: $teamId, name: $name, color: $color }) {
                success
                issueLabel { id }
              }
            }
            """,
            {"teamId": team_id, "name": name, "color": color},
        )
        if data["issueLabelCreate"]["success"]:
            return data["issueLabelCreate"]["issueLabel"]["id"]
        return None

    # ── create issue ──────────────────────────────────────────────────────────
    def create_issue(
        self,
        title: str,
        description: str,
        priority: int = 0,   # 0=No, 1=Urgent, 2=High, 3=Medium, 4=Low
        label_ids: list[str] | None = None,
    ) -> str:
        team_id    = self.get_team_id()
        project_id = self.get_or_create_project()
        variables  = {
            "teamId":      team_id,
            "projectId":   project_id,
            "title":       title,
            "description": description,
            "priority":    priority,
        }
        if label_ids:
            variables["labelIds"] = label_ids

        data = self._gql(
            """
            mutation(
              $teamId: String!, $projectId: String!, $title: String!,
              $description: String!, $priority: Int!, $labelIds: [String!]
            ) {
              issueCreate(input: {
                teamId: $teamId, projectId: $projectId, title: $title,
                description: $description, priority: $priority, labelIds: $labelIds
              }) {
                success
                issue { id identifier url }
              }
            }
            """,
            variables,
        )
        issue = data["issueCreate"]["issue"]
        return issue["url"]


# ── Public helpers called by budget_agent.py ─────────────────────────────────

def post_statement_issues(client: LinearClient, stmt: dict):
    """Create Linear issues for a processed statement."""
    account  = stmt.get("account_name", "Unknown Account")
    last4    = stmt.get("account_last4", "????")
    holder   = stmt.get("holder", "")
    period   = f"{stmt.get('statement_period_start','')} → {stmt.get('statement_period_end','')}"
    balance  = stmt.get("new_balance",  0)
    minpay   = stmt.get("min_payment",  0)
    due      = stmt.get("due_date",     "")
    interest = stmt.get("interest_total", 0)
    past_due = stmt.get("past_due",     0)
    overlimit= stmt.get("overlimit",    0)
    purchases= stmt.get("purchases_total", 0)
    fees     = stmt.get("fees_total",   0)
    txns     = stmt.get("transactions", [])

    # ── Label: account name ───────────────────────────────────────────────────
    label_colors = {"9420": "#0EA5E9", "4420": "#F97316"}
    color = label_colors.get(last4, "#6366F1")
    label_id = client.get_or_create_label(f"{account} ...{last4}", color)
    label_ids = [label_id] if label_id else []

    # ── Build transaction table (markdown) ────────────────────────────────────
    tx_rows = "\n".join(
        f"| {t.get('transaction_date','')} | {t.get('description','')} "
        f"| {'−' if t.get('amount',0) < 0 else ''}${abs(t.get('amount',0)):,.2f} "
        f"| {t.get('category','')} |"
        for t in txns
    )
    tx_table = (
        "| Date | Description | Amount | Category |\n"
        "|------|-------------|--------|----------|\n"
        + tx_rows
    ) if tx_rows else "_No transactions this period._"

    # ── 1. Statement processed issue ──────────────────────────────────────────
    stmt_desc = f"""## Statement Summary
**Account:** {account} ...{last4} ({holder})
**Period:** {period}
**Generated:** {date.today().strftime('%B %d, %Y')}

---

| Field | Amount |
|-------|--------|
| Previous Balance | ${stmt.get('previous_balance',0):,.2f} |
| Payments | ${abs(stmt.get('payments_total',0)):,.2f} |
| Purchases | ${purchases:,.2f} |
| Fees | ${fees:,.2f} |
| Interest | ${interest:,.2f} |
| **New Balance** | **${balance:,.2f}** |
| Minimum Payment | ${minpay:,.2f} |
| Due Date | {due} |

---

## Transactions
{tx_table}
"""
    url = client.create_issue(
        title       = f"Statement: {account} ...{last4} ({period})",
        description = stmt_desc,
        priority    = 3,   # Medium
        label_ids   = label_ids,
    )
    print(f"  Linear issue created → {url}")

    # ── 2. Payment due reminder ───────────────────────────────────────────────
    pay_desc = f"""## Payment Reminder
**Account:** {account} ...{last4} ({holder})
**Amount Due:** ${minpay:,.2f}
**Due Date:** {due}
**Current Balance:** ${balance:,.2f}

> Pay at least the minimum by **{due}** to avoid late fees.
"""
    url2 = client.create_issue(
        title       = f"Payment Due: {account} ...{last4} — ${minpay:,.2f} by {due}",
        description = pay_desc,
        priority    = 2,   # High
        label_ids   = label_ids,
    )
    print(f"  Linear issue created → {url2}")

    # ── 3. Alert issues (urgent) ──────────────────────────────────────────────
    if past_due > 0:
        alert_desc = f"""## 🚨 Past Due Alert
**Account:** {account} ...{last4} ({holder})
**Past Due Amount:** ${past_due:,.2f}
**Full Minimum Payment:** ${minpay:,.2f} (includes past due)
**Due Date:** {due}

This account is past due. Payment required immediately to avoid further fees and credit impact.
"""
        url3 = client.create_issue(
            title       = f"🚨 PAST DUE: {account} ...{last4} — ${past_due:,.2f}",
            description = alert_desc,
            priority    = 1,   # Urgent
            label_ids   = label_ids,
        )
        print(f"  Linear URGENT issue → {url3}")

    if overlimit > 0:
        over_desc = f"""## 🚨 Over Limit Alert
**Account:** {account} ...{last4} ({holder})
**Overlimit Amount:** ${overlimit:,.2f}
**Current Balance:** ${balance:,.2f}
**Credit Limit:** ${stmt.get('credit_limit',0):,.2f}

Account is over its credit limit. Pay down immediately to avoid declined transactions.
"""
        url4 = client.create_issue(
            title       = f"🚨 OVERLIMIT: {account} ...{last4} — ${overlimit:,.2f} over",
            description = over_desc,
            priority    = 1,   # Urgent
            label_ids   = label_ids,
        )
        print(f"  Linear URGENT issue → {url4}")

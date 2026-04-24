# Budget Agent — Setup Guide

## One-time setup

### 1. Install Python dependencies
```bash
cd ~/Library/CloudStorage/GoogleDrive-gustavobills7@gmail.com/My\ Drive/Budget\ Agent
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# Add to ~/.zshrc to make it permanent:
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
```

### 3. Set your Linear API key (optional but recommended)
1. Go to Linear → **Settings → API → Personal API keys** → Create key
2. Export it:
```bash
export LINEAR_API_KEY="lin_api_..."
echo 'export LINEAR_API_KEY="lin_api_..."' >> ~/.zshrc
```
The agent will automatically:
- Create a **"Budget App"** project in your Linear workspace
- Open a **Statement Processed** issue for every PDF (Medium priority)
- Open a **Payment Due** reminder with due date and amount (High priority)
- Open **Urgent** issues for any past due or overlimit accounts

### 4. Set up Google OAuth credentials (optional)
1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Choose **Desktop App**, name it "Budget Agent"
6. Download the JSON file
7. Save it as:
   `~/Library/CloudStorage/GoogleDrive-gustavobills7@gmail.com/My Drive/Budget Agent/google_credentials.json`

First run will open a browser window to authorize — after that it's automatic.

## Running the agent

1. Drop PDF statements into:
   `~/Library/CloudStorage/GoogleDrive-gustavobills7@gmail.com/My Drive/Statements Inbox/`

2. Run:
```bash
python ~/Library/CloudStorage/GoogleDrive-gustavobills7@gmail.com/My\ Drive/Budget\ Agent/budget_agent.py
```

3. Processed files are moved to `Statements Inbox/Processed/` automatically.

4. Open your **Budget Tracker** Google Sheet to see results.

## Google Sheet structure

| Sheet | Contents |
|-------|----------|
| **Transactions** | Every line item: date, description, amount, category, account |
| **Monthly Summary** | Per-statement totals: purchases, fees, interest, payments |

## Categories used
Food & Dining · Transport · Shopping · Bills & Utilities · Entertainment · Travel · Health · Church & Donations · Bank Fees · Interest · Payment · Other

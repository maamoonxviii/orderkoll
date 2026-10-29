# n8n workflow templates

Two workflows give Orderkoll **Approve / Reject buttons in Slack**. They are n8n JSON
exports without any secrets: you connect your own Slack and Odoo in n8n.

| File | What it does |
|---|---|
| `orderkoll-approval-request.json` | Odoo → n8n: checks Odoo's signature, posts the purchase order with Approve / Reject buttons to your Slack channel. |
| `orderkoll-slack-click.json` | Slack → n8n → Odoo: checks Slack's signature, sends the click to Odoo (signed), and updates the Slack message with the result. |

How the buttons stay safe: every request carries a random token that works **once** and
expires after 7 days; Odoo only stores a hash of it. Messages between Odoo and n8n are
signed with a shared secret (HMAC-SHA256) and refused when older than 5 minutes; a signed
click names the request it is for. A second click on the same request is refused ("Already
used"), and so is a click on a message whose order was edited after it was sent. Clicks from
another Slack workspace, or from someone not on the approver list, are refused. Document text
is escaped, so a purchase order cannot put links into the message.

## Setup

1. **Slack app** (api.slack.com/apps → your app): bot scopes `chat:write`,
   `chat:write.public`; under *Interactivity & Shortcuts* switch Interactivity on and set
   the Request URL to `https://<your n8n>/webhook/orderkoll-slack`. Copy the *Signing Secret*
   (Basic Information).
2. **n8n credentials** (create these four, with exactly these names):
   - *Orderkoll webhook secret*: type **Crypto**, field *Hmac Secret* = a long random
     string. Put the same string in Odoo (step 4).
   - *Orderkoll Slack signing secret*: type **Crypto**, *Hmac Secret* = Slack's signing secret.
   - *Orderkoll Slack bot*: type **Slack API**, the bot token (`xoxb-…`).
   - *Orderkoll Odoo basic auth*: type **Basic Auth**, only if a password prompt sits in
     front of your Odoo; otherwise remove the credential from the *Tell Odoo* node.
3. **Import** both JSON files (n8n → Workflows → Import from file). In the *Code* nodes
   replace `__SLACK_CHANNEL__` (e.g. `#po-approvals`), `__ODOO_BASE_URL__` (e.g.
   `https://odoo.example.com`, no trailing slash), `__SLACK_TEAM_ID__` (your workspace id,
   `T…`) and `__SLACK_APPROVER_IDS__` (comma-separated user ids, `U…`, of the people allowed
   to approve; leave empty to allow anyone in the workspace who sees the channel). Pick the
   credentials above in the nodes that ask for them, and activate both workflows.
4. **Odoo** → Orderkoll → Configuration → Settings → Approval: channel *n8n webhook*,
   webhook URL `https://<your n8n>/webhook/orderkoll-approval`, webhook secret = the same
   string as in step 2.

From then on every purchase order that passes all checks appears in the channel; *Approve*
creates the draft quotation in Odoo, *Reject* marks the document rejected. Approving in
Odoo itself keeps working as before.

`tools/build_n8n_workflows.py` regenerates the two files.

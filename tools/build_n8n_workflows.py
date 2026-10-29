#!/usr/bin/env python3
# Copyright 2026 Maamoon Mara
# License MIT (https://opensource.org/licenses/MIT).
"""Build the two n8n workflow templates in n8n/ (no secrets inside).

    python3 tools/build_n8n_workflows.py

Placeholders replaced when importing into an n8n instance (see n8n/README.md):
  __SLACK_CHANNEL__        e.g. #po-approvals
  __ODOO_BASE_URL__        e.g. https://odoo.example.com  (no trailing slash)
  __SLACK_TEAM_ID__        your Slack workspace id (T...): clicks from other workspaces are refused
  __SLACK_APPROVER_IDS__   comma-separated Slack user ids (U...) allowed to click; empty = anyone
                           in the workspace who can see the channel
Credentials are referenced by name: "Orderkoll webhook secret" (Crypto: HMAC secret, the
same value as Odoo's webhook secret), "Orderkoll Slack signing secret" (Crypto: HMAC
secret), "Orderkoll Slack bot" (Slack API) and, only if your Odoo sits behind basic auth,
"Orderkoll Odoo basic auth" (HTTP Basic Auth).
"""

import json
import pathlib
import uuid

OUT = pathlib.Path(__file__).resolve().parent.parent / "n8n"
NS = uuid.UUID("6f1c2a52-6a1f-4d2c-9a55-0b5a3f1e7a10")


def node_id(name):
    return str(uuid.uuid5(NS, name))


def cred(kind, name):
    return {kind: {"id": f"__CRED_{name.upper().replace(' ', '_')}__", "name": name}}


def node(name, ntype, version, pos, params, credentials=None, **extra):
    n = {
        "id": node_id(name),
        "name": name,
        "type": ntype,
        "typeVersion": version,
        "position": pos,
        "parameters": params,
    }
    if credentials:
        n["credentials"] = credentials
    n.update(extra)
    return n


def if_true(expr):
    return {
        "conditions": {
            "options": {
                "caseSensitive": True,
                "leftValue": "",
                "typeValidation": "strict",
                "version": 2,
            },
            "conditions": [
                {
                    "id": node_id(expr),
                    "leftValue": expr,
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }
            ],
            "combinator": "and",
        },
        "options": {},
    }


def hmac(name, value, prop, cred_name, pos):
    return node(
        name,
        "n8n-nodes-base.crypto",
        2,
        pos,
        {
            "action": "hmac",
            "type": "SHA256",
            "value": value,
            "dataPropertyName": prop,
            "encoding": "hex",
        },
        cred("crypto", cred_name),
    )


def link(*names):
    return {
        a: {"main": [[{"node": b, "type": "main", "index": 0}]]}
        for a, b in zip(names, names[1:], strict=False)
    }


BUILD_MESSAGE = r"""
// Odoo sends {ts, data, sig}: data is the payload as JSON text, sig = HMAC(ts + "." + data).
const it = $input.first().json;
const body = it.body || {};
const fresh = Math.abs(Date.now() / 1000 - Number(body.ts)) < 300;
if (!fresh || !body.sig || it.expected !== body.sig) {
  return [{ json: { ok: false } }];
}
const p = JSON.parse(body.data);
const d = p.document;
// Document text comes from emails anyone can send: escape it so it cannot become a link.
const esc = (v) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const money = (n) => Number(n || 0).toFixed(2);
const docUrl = '__ODOO_BASE_URL__/odoo/action-orderkoll_core.action_document/' + Number(d.id);
const shown = d.lines || [];
let lines = shown
  .map((l) => `• ${Number(l.quantity)} × ${esc(l.product || l.description)}`
    + ` @ ${money(l.unit_price)}`)
  .join('\n');
if (d.line_count > shown.length) lines += `\n…and ${d.line_count - shown.length} more`;
const head =
  `*Purchase order ${esc(d.po_number || d.name)}* from *${esc(d.customer)}*\n` +
  `Total ${money(d.total)} ${esc(d.currency)} · ${Number(d.line_count)} lines · every check passed`;
const blocks = [
  { type: 'section', text: { type: 'mrkdwn', text: head } },
  { type: 'section', text: { type: 'mrkdwn', text: (lines || '_no lines_').slice(0, 2900) } },
  { type: 'context', elements: [{ type: 'mrkdwn',
    text: `<${docUrl}|Open in Odoo> · button valid until ${esc(p.expires_at)} UTC` }] },
  {
    type: 'actions',
    elements: [
      { type: 'button', style: 'primary', action_id: 'orderkoll_approve', value: p.callback_url,
        text: { type: 'plain_text', text: 'Approve: create quotation' } },
      { type: 'button', style: 'danger', action_id: 'orderkoll_reject', value: p.callback_url,
        text: { type: 'plain_text', text: 'Reject' },
        confirm: {
          title: { type: 'plain_text', text: 'Reject this order?' },
          text: { type: 'mrkdwn', text: 'The document is marked rejected in Odoo.' },
          confirm: { type: 'plain_text', text: 'Reject' },
          deny: { type: 'plain_text', text: 'Cancel' },
        } },
    ],
  },
];
return [{ json: { ok: true, slack: {
  channel: '__SLACK_CHANNEL__',
  text: `PO ${esc(d.po_number || d.name)} from ${esc(d.customer)} is ready for approval`,
  blocks,
} } }];
""".strip()

RAW_BODY = r"""
// Slack signs "v0:" + timestamp + ":" + the raw form body; "Raw text" turned the webhook's
// raw body into text (works whatever binary-data mode n8n runs in).
const headers = $('From Slack').first().json.headers;
return [{ json: {
  raw: String($input.first().json.raw || ''),
  ts: headers['x-slack-request-timestamp'],
  sig: headers['x-slack-signature'],
} }];
""".strip()

CHECK_CLICK = r"""
const it = $input.first().json;
const fresh = Math.abs(Date.now() / 1000 - Number(it.ts)) < 300;
if (!fresh || !it.sig || 'v0=' + it.expected !== it.sig) return [{ json: { ok: false } }];
const m = it.raw.match(/(?:^|&)payload=([^&]*)/);
if (!m) return [{ json: { ok: false } }];
const payload = JSON.parse(decodeURIComponent(m[1].replace(/\+/g, ' ')));
const action = (payload.actions || [])[0];
const allowed = '__ODOO_BASE_URL__/orderkoll/approve/';
if (!action || !String(action.value || '').startsWith(allowed)) return [{ json: { ok: false } }];
// Only your workspace, and (if listed) only the named approvers, may decide.
if (!payload.team || payload.team.id !== '__SLACK_TEAM_ID__') return [{ json: { ok: false } }];
const uid = (payload.user && payload.user.id) || '';
const approvers = '__SLACK_APPROVER_IDS__'.split(',').map((x) => x.trim()).filter(Boolean);
if (approvers.length && !approvers.includes(uid)) {
  return [{ json: { ok: false, url: payload.response_url,
    notice: 'You are not on the approver list for purchase orders.' } }];
}
const name = (payload.user && (payload.user.name || payload.user.username)) || 'Slack user';
const who = `${name} (${uid})`;
const body = JSON.stringify({
  action: action.action_id === 'orderkoll_approve' ? 'approve' : 'reject',
  user: who,
  token: String(action.value).split('/').pop(),  // the signature covers which request this is
});
return [{ json: {
  ok: true, url: action.value, body, who,
  ts: String(Math.floor(Date.now() / 1000)),
  response_url: payload.response_url,
  original: payload.message || {},
} }];
""".strip()

SLACK_UPDATE = r"""
const r = $input.first().json;
const click = $('Check the click').first().json;
let res = r.body;
if (typeof res === 'string') {
  try { res = JSON.parse(res); } catch (e) { res = { message: res }; }
}
res = res || {};
const ok = r.statusCode === 200;
const esc = (v) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const text = ok
  ? `✅ ${esc(res.message)} (${esc(click.who)})`
  : `⚠️ ${esc(res.message || 'Odoo answered ' + r.statusCode)}`;
if (!ok) {
  const msg = { response_type: 'ephemeral', replace_original: false, text };
  return [{ json: { url: click.response_url, msg } }];
}
const blocks = (click.original.blocks || []).filter((b) => b.type !== 'actions');
blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text }] });
return [{ json: { url: click.response_url, msg: { replace_original: true, text, blocks } } }];
""".strip()


def approval_request():
    nodes = [
        node(
            "From Odoo",
            "n8n-nodes-base.webhook",
            2,
            [0, 0],
            {
                "httpMethod": "POST",
                "path": "orderkoll-approval",
                "responseMode": "responseNode",
                "options": {},
            },
            webhookId=node_id("webhook orderkoll-approval"),
        ),
        hmac(
            "Expected signature",
            "={{ $json.body.ts }}.{{ $json.body.data }}",
            "expected",
            "Orderkoll webhook secret",
            [220, 0],
        ),
        node(
            "Check and build message", "n8n-nodes-base.code", 2, [440, 0], {"jsCode": BUILD_MESSAGE}
        ),
        node("Signed by Odoo?", "n8n-nodes-base.if", 2.2, [660, 0], if_true("={{ $json.ok }}")),
        node(
            "Post to Slack",
            "n8n-nodes-base.httpRequest",
            4.2,
            [880, -100],
            {
                "method": "POST",
                "url": "https://slack.com/api/chat.postMessage",
                "authentication": "predefinedCredentialType",
                "nodeCredentialType": "slackApi",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.slack) }}",
                "options": {},
            },
            cred("slackApi", "Orderkoll Slack bot"),
        ),
        node(
            "Answer Odoo",
            "n8n-nodes-base.respondToWebhook",
            1.1,
            [1100, -100],
            {
                "respondWith": "json",
                "responseBody": "={{ JSON.stringify({ ok: $json.ok === true, "
                "slack_error: $json.error || null }) }}",
                "options": {"responseCode": "={{ $json.ok === true ? 200 : 502 }}"},
            },
        ),
        node(
            "Refuse",
            "n8n-nodes-base.respondToWebhook",
            1.1,
            [880, 120],
            {
                "respondWith": "json",
                "responseBody": "={{ JSON.stringify({ ok: false }) }}",
                "options": {"responseCode": 401},
            },
        ),
    ]
    connections = link(
        "From Odoo", "Expected signature", "Check and build message", "Signed by Odoo?"
    )
    connections["Signed by Odoo?"] = {
        "main": [
            [{"node": "Post to Slack", "type": "main", "index": 0}],
            [{"node": "Refuse", "type": "main", "index": 0}],
        ]
    }
    connections.update(link("Post to Slack", "Answer Odoo"))
    return {
        "name": "Orderkoll: approval request → Slack",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "active": False,
    }


def slack_click():
    nodes = [
        node(
            "From Slack",
            "n8n-nodes-base.webhook",
            2,
            [0, 0],
            {
                "httpMethod": "POST",
                "path": "orderkoll-slack",
                "responseMode": "responseNode",
                "options": {"rawBody": True},
            },
            webhookId=node_id("webhook orderkoll-slack"),
        ),
        # Slack wants an empty 200 within 3 s; answer first, then work.
        node(
            "Answer Slack",
            "n8n-nodes-base.respondToWebhook",
            1.1,
            [60, 120],
            {"respondWith": "noData", "options": {}},
        ),
        node(
            "Raw text",
            "n8n-nodes-base.extractFromFile",
            1.1,
            [110, 0],
            {
                "operation": "text",
                "binaryPropertyName": "data",
                "destinationKey": "raw",
                "options": {},
            },
        ),
        node("Raw body", "n8n-nodes-base.code", 2, [220, 0], {"jsCode": RAW_BODY}),
        hmac(
            "Slack signature",
            "=v0:{{ $json.ts }}:{{ $json.raw }}",
            "expected",
            "Orderkoll Slack signing secret",
            [440, 0],
        ),
        node("Check the click", "n8n-nodes-base.code", 2, [660, 0], {"jsCode": CHECK_CLICK}),
        node("Signed by Slack?", "n8n-nodes-base.if", 2.2, [880, 0], if_true("={{ $json.ok }}")),
        hmac(
            "Odoo signature",
            "={{ $json.ts }}.{{ $json.body }}",
            "expected",
            "Orderkoll webhook secret",
            [1100, -100],
        ),
        node(
            "Tell Odoo",
            "n8n-nodes-base.httpRequest",
            4.2,
            [1320, -100],
            {
                "method": "POST",
                "url": "={{ $json.url }}",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpBasicAuth",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {"name": "X-Orderkoll-Timestamp", "value": "={{ $json.ts }}"},
                        {"name": "X-Orderkoll-Signature", "value": "={{ $json.expected }}"},
                    ]
                },
                "sendBody": True,
                "contentType": "raw",
                "rawContentType": "application/json",
                "body": "={{ $json.body }}",
                "options": {"response": {"response": {"fullResponse": True, "neverError": True}}},
            },
            cred("httpBasicAuth", "Orderkoll Odoo basic auth"),
        ),
        node("Slack update", "n8n-nodes-base.code", 2, [1540, -100], {"jsCode": SLACK_UPDATE}),
        node(
            "Has a notice?", "n8n-nodes-base.if", 2.2, [1100, 120], if_true("={{ !!$json.notice }}")
        ),
        node(
            "Tell the clicker",
            "n8n-nodes-base.httpRequest",
            4.2,
            [1320, 120],
            {
                "method": "POST",
                "url": "={{ $json.url }}",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ response_type: 'ephemeral', "
                "replace_original: false, text: '⚠️ ' + $json.notice }) }}",
                "options": {},
            },
        ),
        node(
            "Update the message",
            "n8n-nodes-base.httpRequest",
            4.2,
            [1760, -100],
            {
                "method": "POST",
                "url": "={{ $json.url }}",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.msg) }}",
                "options": {},
            },
        ),
    ]
    connections = link(
        "From Slack",
        "Answer Slack",
        "Raw text",
        "Raw body",
        "Slack signature",
        "Check the click",
        "Signed by Slack?",
    )
    connections["Signed by Slack?"] = {
        "main": [
            [{"node": "Odoo signature", "type": "main", "index": 0}],
            [{"node": "Has a notice?", "type": "main", "index": 0}],
        ]
    }
    connections["Has a notice?"] = {
        "main": [[{"node": "Tell the clicker", "type": "main", "index": 0}], []]
    }
    connections.update(link("Odoo signature", "Tell Odoo", "Slack update", "Update the message"))
    return {
        "name": "Orderkoll: Slack button → Odoo",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
        "active": False,
    }


def main():
    OUT.mkdir(exist_ok=True)
    for fname, wf in (
        ("orderkoll-approval-request.json", approval_request()),
        ("orderkoll-slack-click.json", slack_click()),
    ):
        (OUT / fname).write_text(json.dumps(wf, indent=2, ensure_ascii=False) + "\n")
        print("wrote", OUT / fname)


if __name__ == "__main__":
    main()

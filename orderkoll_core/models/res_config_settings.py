# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    orderkoll_provider = fields.Char(
        string="LLM provider",
        config_parameter="orderkoll.provider",
        help="The provider named in your data processing agreement.",
    )
    orderkoll_model = fields.Char(
        string="LLM model",
        config_parameter="orderkoll.model",
        help="LiteLLM model string, e.g. mistral/mistral-large-latest or openai/gpt-4.1-mini. "
        "Nothing is sent anywhere until both the model and the API key are set.",
    )
    orderkoll_api_key = fields.Char(
        string="LLM API key",
        config_parameter="orderkoll.api_key",
        help="Bring your own key. Stored as a system parameter; shown masked.",
    )
    orderkoll_api_base = fields.Char(
        string="API base URL",
        config_parameter="orderkoll.api_base",
        help="Only for an OpenAI-compatible endpoint you host or rent (Azure, a local "
        "Ollama or vLLM, Cloudflare Workers AI...). Leave empty for the provider's own API.",
    )
    orderkoll_tolerance_pct = fields.Float(
        string="Price tolerance (%)", config_parameter="orderkoll.tolerance_pct", default=2.0
    )
    orderkoll_fuzzy_threshold = fields.Float(
        string="Name match threshold", config_parameter="orderkoll.fuzzy_threshold", default=0.88
    )
    orderkoll_duplicate_days = fields.Integer(
        string="Duplicate PO window (days)", config_parameter="orderkoll.duplicate_days", default=90
    )
    orderkoll_ignored_domains = fields.Char(
        string="Ignored sender domains",
        config_parameter="orderkoll.ignored_domains",
        default="gmail.com,outlook.com,hotmail.com,yahoo.com,icloud.com,live.com",
        help="Webmail domains that never identify a customer.",
    )
    orderkoll_approval_channel = fields.Selection(
        [("odoo", "In Odoo"), ("n8n", "n8n webhook (Slack)")],
        string="Approval channel",
        config_parameter="orderkoll.approval_channel",
        default="odoo",
    )
    orderkoll_webhook_url = fields.Char(
        string="n8n webhook URL", config_parameter="orderkoll.webhook_url"
    )
    orderkoll_webhook_secret = fields.Char(
        string="n8n webhook secret", config_parameter="orderkoll.webhook_secret"
    )
    orderkoll_heartbeat_url = fields.Char(
        string="Heartbeat URL",
        config_parameter="orderkoll.heartbeat_url",
        help="Pinged after every processing run (Healthchecks, Uptime Kuma push...). "
        "Your monitor alerts you when the pings stop.",
    )
    orderkoll_alert_telegram_token = fields.Char(
        string="Telegram bot token", config_parameter="orderkoll.alert_telegram_token"
    )
    orderkoll_alert_telegram_chat = fields.Char(
        string="Telegram chat id", config_parameter="orderkoll.alert_telegram_chat"
    )
    orderkoll_alert_webhook_url = fields.Char(
        string="Alert webhook URL",
        config_parameter="orderkoll.alert_webhook_url",
        help="Optional: a JSON POST per failed document (e.g. an n8n workflow).",
    )

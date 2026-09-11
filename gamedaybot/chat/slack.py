import requests
import json
import logging
import re

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackException(Exception):
    pass


class Slack:
    """
    A class used to send messages to a Slack channel.

    Two transports are supported:

    1. Incoming webhook (webhook_url): the classic single-channel webhook.
    2. Slack Web API (bot_token + channel): full messaging-service mode via
       chat.postMessage, using a Slack app bot token (xoxb-...) and a channel
       ID or name. Supports any channel the app's bot is a member of, plus
       Slack Block Kit table blocks for rich table rendering.

    If a bot_token and channel are both provided, the Web API is used;
    otherwise the message falls back to the webhook.

    Parameters
    ----------
    webhook_url : str
        The URL of the Slack webhook to send messages to.
    bot_token : str, optional
        A Slack app bot token (starts with xoxb-) for Web API mode.
    channel : str, optional
        The channel ID or name to post to when using Web API mode.

    Attributes
    ----------
    webhook_url : str
        The URL of the Slack webhook to send messages to.
    bot_token : str
        The Slack bot token, or None when running in webhook-only mode.
    channel : str
        The target channel for Web API mode, or None.

    Methods
    -------
    send_message(text: str)
        Sends a message to the Slack channel.
    """

    def __init__(self, webhook_url: str, bot_token=None, channel=None):
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.channel = channel

    def __repr__(self):
        return "Slack Webhook Url(%s)" % self.webhook_url

    def send_message(self, text: str):
        """
        Sends a message to the Slack channel.

        When running in Web API mode, the message text is inspected: if it
        contains a structured table (header line followed by pipe-separated
        rows), the table is rendered as a Slack Block Kit ``table`` block for
        rich rendering, and the plain-text code-block is included as a
        fallback ``text`` field.  Plain messages continue to use the
        triple-backtick code-block format that has always been used.

        Parameters
        ----------
        text : str
            The message to be sent to the Slack channel.

        Returns
        -------
        r : requests.Response
            The response object of the POST request.

        Raises
        ------
        SlackException
            If there is an error with the POST request.
        """
        message = "```{0}```".format(text)

        if self._use_web_api():
            return self._send_via_web_api(text, message)
        return self._send_via_webhook(message)

    def _use_web_api(self) -> bool:
        """True when a usable bot token and channel are both configured."""

        return (self.bot_token is not None and
                self.bot_token not in (1, "1", '') and
                self.channel is not None and
                self.channel not in (1, "1", ''))

    # ------------------------------------------------------------------
    # Block Kit table conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_table(text: str):
        """Parse a Slack-style pipe table from *text*.

        Accepts the GitHub-Flavoured Markdown pipe-table syntax that the
        repository's report generators already use::

            | Team One     | 10-3 |
            | Team Two     |  9-4 |

        Returns ``(headers, rows)`` where *headers* is a ``list[str]`` and
        *rows* is a ``list[list[str]]``, or ``None`` when the text does not
        contain a recognisable piped table.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        table_lines = []
        for ln in lines:
            if ln.startswith('|') and ln.endswith('|'):
                table_lines.append(ln)

        if len(table_lines) < 2:
            # Need at least a header + separator row.
            return None

        # Strip the outer pipes and split on the remaining pipes.
        def _cells(ln):
            ln = ln[1:-1] if ln.startswith('|') else ln
            return [c.strip() for c in ln.split('|')]

        rows = [_cells(ln) for ln in table_lines]
        # The GFM separator row (dashes) marks the boundary between header
        # and body.  If it's missing we fall back to treating the first row
        # as a header.
        if len(rows) >= 2 and all(re.match(r'^[:\-|]+$', c) for c in rows[1]):
            headers = rows[0]
            data_rows = rows[2:]
        else:
            headers = rows[0]
            data_rows = rows[1:]

        if not data_rows:
            return None
        return headers, data_rows

    def _build_table_block(self, headers, rows):
        """Build a Slack Block Kit ``table`` block dict from headers + rows."""
        block = {
            "type": "table",
            "block_id": "fantasy_table",
            "column_settings": [
                {"align": "left", "is_wrapped": False}
            ] * len(headers),
            "rows": [],
        }

        def _cell(value):
            """Wrap a cell value as a plain_text table cell."""
            return {"type": "plain_text", "text": value}

        # Header row
        block["rows"].append([_cell(h) for h in headers])
        # Data rows
        for row in rows:
            # Pad / truncate to header width
            row = (list(row) + [""] * len(headers))[:len(headers)]
            block["rows"].append([_cell(c) for c in row])

        return block

    def _format_as_table(self, text: str):
        """Try to convert *text* into a Slack table block.

        Returns the table block dict when the text contains a piped table,
        otherwise ``None``.
        """
        result = self._parse_table(text)
        if result is None:
            return None
        headers, rows = result
        return self._build_table_block(headers, rows)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _send_via_web_api(self, text: str, message: str):
        """Post via chat.postMessage using a bot token.

        When the message contains a structured table we additionally send a
        ``blocks`` array containing a Block Kit ``table`` block, giving Slack
        a native HTML table.  The ``text`` field (code-block wrapped) is always
        included as the fallback for clients that cannot render blocks.
        """
        payload = {
            "channel": self.channel,
            "text": message  # limit 40000
        }

        table_block = self._format_as_table(text)
        if table_block is not None:
            payload["blocks"] = [table_block]

        headers = {
            'Authorization': 'Bearer {0}'.format(self.bot_token),
            'content-type': 'application/json'
        }

        r = requests.post(SLACK_API_BASE + "/chat.postMessage",
                          data=json.dumps(payload), headers=headers)

        if r.status_code != 200:
            logger.error(r.content)
            raise SlackException(r.content)

        body = r.json()
        if not body.get("ok", False):
            logger.error(body)
            raise SlackException(json.dumps(body))

        return r

    def _send_via_webhook(self, message: str):
        """Post via a legacy incoming webhook."""

        template = {
            "text": message  # limit 40000
        }

        headers = {'content-type': 'application/json'}

        if self.webhook_url not in (1, "1", ''):
            r = requests.post(self.webhook_url,
                              data=json.dumps(template), headers=headers)

            if r.status_code != 200:
                logger.error(r.content)
                raise SlackException(r.content)

            return r

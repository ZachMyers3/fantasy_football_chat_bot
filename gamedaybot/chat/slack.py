import requests
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"

# Trophy emojis used by the ESPN bot's trophy report.
# Each trophy entry is an emoji-prefixed line (e.g. "👑 High score 👑").
TROPHY_EMOJIS = [
    "👑", "💩", "😱", "😅", "🍀", "😡",
    "📈", "📉", "🟢", "🔻", "🟰",
    "🤖", "🤡",
    # Emoji shortcodes may appear as text (e.g., from Slack rendering)
    ":chart_with_downwards_trend:",
]


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
       Slack Block Kit for rich message rendering (tables, headers, dividers,
       rich text, etc.).

    If a bot_token and channel are both provided, the Web API is used;
    otherwise the message falls back to the webhook (code-block only).

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_message(self, text: str):
        """
        Send a message to the Slack channel.

        When running in Web API mode, the message text is inspected and
        Block Kit blocks are generated for structured content:

        * **Trophy reports** → ``header`` + ``rich_text`` + ``divider`` blocks
        * **Waiver reports** → ``header`` + ``section`` blocks with mrkdwn
          (bold team names, strikethrough for dropped players)
        * **Piped tables** (GFM ``| col | col |``) → native Block Kit ``table``
        * **Scoreboards** (aligned columns) → converted to pipe table → ``table``
        * **Power Rankings** (aligned columns) → converted to pipe table →
          ``table`` + ``context`` explaining trend emojis
        * **Matchups** → table with Home/vs/Away columns
        * **Standings** → table with Rank/Record/Team columns

        The plain-text code-block is always included as the ``text`` field
        fallback for clients that cannot render blocks.  Plain messages
        without structured content use the triple-backtick code-block only.

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
    # Block Kit builders
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_table(text: str):
        """Parse a GFM pipe table from *text*.

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
            return None

        def _cells(ln):
            ln = ln[1:-1] if ln.startswith('|') else ln
            return [c.strip() for c in ln.split('|')]

        rows = [_cells(ln) for ln in table_lines]
        # The GFM separator row (dashes) marks header/body boundary.
        if len(rows) >= 2 and all(re.match(r'^[-:|]+$', c) for c in rows[1]):
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
            "block_id": "fantasy_table_0",
            "column_settings": [
                {"align": "left", "is_wrapped": False}
            ] * len(headers),
            "rows": [],
        }

        def _cell(value):
            # Slack's raw_text type rejects empty text ("must be more than
            # 0 characters").  Use a visible placeholder for empty cells.
            if not value or not value.strip():
                value = "—"
            return {"type": "raw_text", "text": value}

        block["rows"].append([_cell(h) for h in headers])
        for row in rows:
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
    # Trophy block formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _is_trophy_message(text: str) -> bool:
        """Heuristic: does the message look like a trophy report?"""
        stripped = text.strip()
        if not stripped.startswith("Trophies of the week"):
            return False
        lines = [ln for ln in stripped.splitlines() if ln.strip()]
        emoji_count = sum(1 for ln in lines if _starts_with_emoji(ln))
        return emoji_count > 0

    def _format_trophies(self, text: str) -> list:
        """Build Block Kit blocks for a trophy report message.

        Each trophy (emoji-prefixed header line) gets a ``header`` block
        followed by a ``rich_text`` block for the detail line.  Trophies
        are separated by ``divider`` blocks.
        """
        blocks = []
        lines = text.splitlines()
        title = lines[0] if lines else "Trophies of the week:"
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        })

        current_trophy_header = None
        current_detail = []
        trophy_count = 0

        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            is_header = any(stripped.startswith(emoji) for emoji in TROPHY_EMOJIS)
            if is_header:
                if current_trophy_header is not None:
                    trophy_count += 1
                    if trophy_count > 1:
                        blocks.append({"type": "divider"})
                    blocks.append({
                        "type": "header",
                        "text": {"type": "plain_text",
                                 "text": current_trophy_header, "emoji": True},
                    })
                    if current_detail:
                        detail_text = " ".join(current_detail)
                        blocks.append(self._rich_text_block(detail_text, trophy_count - 1))
                current_trophy_header = stripped
                current_detail = []
            else:
                if current_trophy_header is not None:
                    current_detail.append(stripped)

        if current_trophy_header is not None:
            trophy_count += 1
            if trophy_count > 1:
                blocks.append({"type": "divider"})
            blocks.append({
                "type": "header",
                "text": {"type": "plain_text",
                         "text": current_trophy_header, "emoji": True},
            })
            if current_detail:
                detail_text = " ".join(current_detail)
                blocks.append(self._rich_text_block(detail_text, trophy_count - 1))

        return blocks if len(blocks) > 1 else []

    def _rich_text_block(self, text: str, index: int = 0):
        """Build a ``rich_text`` block from plain text.

        The *index* parameter is used to generate a unique ``block_id`` for
        each trophy detail, satisfying Slack's requirement that block_ids be
        unique within a message.
        """
        return {
            "type": "rich_text",
            "block_id": f"trophy_detail_{index}",
            "elements": [{
                "type": "rich_text_section",
                "elements": [{"type": "text", "text": text}],
            }],
        }

    # ------------------------------------------------------------------
    # Waiver report block formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _is_waiver_report(text: str) -> bool:
        """Heuristic: does the message look like a waiver report?"""
        return text.strip().startswith("Waiver Report")

    def _format_waiver_report(self, text: str) -> list:
        """Build Block Kit blocks for a waiver report.

        Uses ``section`` blocks with ``mrkdwn`` text: bold team names,
        ADDED lines with bold prefix, DROPPED lines with strikethrough.
        """
        lines = text.splitlines()
        blocks = [{
            "type": "header",
            "text": {"type": "plain_text",
                     "text": lines[0] if lines else "Waiver Report", "emoji": True},
        }]

        current_team = None
        moves = []

        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("ADDED") or stripped.startswith("DROPPED"):
                moves.append(self._format_waiver_move(stripped))
            else:
                # New team name — flush the previous team if there is one
                if current_team is not None:
                    blocks.append(self._waiver_section(current_team, moves))
                current_team = stripped
                moves = []

        # Flush last team
        if current_team is not None:
            blocks.append(self._waiver_section(current_team, moves))

        return blocks

    @staticmethod
    def _waiver_section(team: str, moves: list) -> dict:
        """Build a ``section`` block for one team's waiver moves."""
        move_text = f"*{team}*\n" + "\n".join(moves) if moves else f"*{team}*"
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": move_text},
        }

    @staticmethod
    def _format_waiver_move(line: str) -> str:
        """Format a single ADDED/DROPPED line with mrkdwn styling."""
        if line.startswith("ADDED"):
            return f"➕ *ADDED* {line[6:]}"
        elif line.startswith("DROPPED"):
            return f"➖ ~DROPPED~ {line[8:]}"
        return line

    # ------------------------------------------------------------------
    # Scoreboard block formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _is_scoreboard(text: str) -> bool:
        """Heuristic: does the message look like a scoreboard?"""
        stripped = text.strip()
        return stripped.startswith(("Score Update",
                                    "Approximate Projected Scores"))

    def _format_scoreboard(self, text: str) -> list:
        """Build a Block Kit table block from a scoreboard-style message.

        Parses lines like ``DKNG 120.34 -  98.56 PNLF`` into a 5-column
        pipe table: | Home | Score |  | Score | Away |
        """
        lines = text.splitlines()
        header = lines[0] if lines else "Scoreboard"
        data_lines = [ln.strip() for ln in lines[1:] if ln.strip()]

        pipe_rows = ["| Home | Score | vs | Score | Away |",
                     "|------|-------|-----|-------|------|"]
        for line in data_lines:
            match = re.match(r'(\S+)\s+([\d.]+)\s+-\s+([\d.]+)\s+(\S+)', line)
            if match:
                pipe_rows.append(
                    f"| {match.group(1)} | {match.group(2)} | - "
                    f"| {match.group(3)} | {match.group(4)} |"
                )
            # Skip non-matching lines (e.g., secondary section headers) to avoid empty cells

        table_text = "\n".join(pipe_rows)
        table_block = self._format_as_table(table_text)
        if table_block is None:
            return []

        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": header, "emoji": True},
        }]
        blocks.append(table_block)
        return blocks

    # ------------------------------------------------------------------
    # Power rankings block formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _is_power_rankings(text: str) -> bool:
        """Heuristic: does the message look like a power rankings report?"""
        return text.strip().startswith("Power Rankings")

    def _format_power_rankings(self, text: str) -> list:
        """Build Block Kit blocks for a power rankings message.

        Creates a table block with columns: Rank, Score, Change, Playoff %, Team.
        Adds a context block explaining the trend emojis.
        """
        lines = text.splitlines()
        header = lines[0] if lines else "Power Rankings"
        data_lines = [ln.strip() for ln in lines[1:] if ln.strip()]

        pipe_rows = ["| # | Score | Change | Playoff % | Team |",
                     "|---|-------|--------|-----------|------|"]

        rank = 1
        for line in data_lines:
            # Match two possible formats:
            # 1. Week 1 (no previous week data): "0.00 (52.7) - tLAW"
            # 2. With trend: "99.99[🟢12.5%] (87.5) - DKNG"
            match = re.match(
                r'([\d.]+)\s*(?:\[([^\]]*)\]\s*)?\(([\d.]+)\)\s*-\s*(\S+)', line
            )
            if match:
                score = match.group(1)
                change = match.group(2) if match.group(2) else ""
                playoff_pct = match.group(3)
                team = match.group(4)
                pipe_rows.append(
                    f"| {rank} | {score} | {change} "
                    f"| {playoff_pct} | {team} |"
                )
                rank += 1
            # Skip non-matching lines to avoid empty cells

        table_text = "\n".join(pipe_rows)
        table_block = self._format_as_table(table_text)

        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": header, "emoji": True},
        }]
        if table_block:
            blocks.append(table_block)
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": ":green_circle: up — :red_circle: down — :large_blue_circle: same",
            }],
        })
        return blocks

    # ------------------------------------------------------------------
    # Matchups block formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _is_matchups(text: str) -> bool:
        """Heuristic: does the message look like a matchups report?"""
        return text.strip().startswith("Matchups")

    def _format_matchups(self, text: str) -> list:
        """Build Block Kit blocks for a matchups message.

        The matchups text has two sections separated by a blank line:
        1. Full team names: ``Team A vs Team B``
        2. Abbreviations with records: ``DKNG (0-0) vs (0-0) PNLF``

        Each section is rendered as its own table block for clarity.
        """
        lines = text.splitlines()
        header_text = lines[0] if lines else "Matchups"

        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        }]

        # Split into sections by blank lines; the first line is the header.
        sections = []
        current = []
        for line in lines[1:]:
            if not line.strip():
                if current:
                    sections.append(current)
                    current = []
            else:
                current.append(line.strip())
        if current:
            sections.append(current)

        table_index = 0
        for section_lines in sections:
            # Determine column set for this section
            pipe_rows = []
            for line in section_lines:
                match = re.match(r'(.+?)\s+(?:vs|@)\s+(.+)', line)
                if match:
                    home = match.group(1).strip()
                    away = match.group(2).strip()
                    # Extract records from abbrev section (e.g., "DKNG (0-0) vs (0-0) PNLF")
                    rec_match = re.match(r'(.+?)\s+\(([^)]*)\)\s+(?:vs|@)\s+\(([^)]*)\)\s+(.+)', line)
                    if rec_match:
                        # Abbreviations with records section
                        if not pipe_rows:
                            pipe_rows.append("| Home | Record | vs | Record | Away |")
                            pipe_rows.append("|------|--------|----|--------|------|")
                        pipe_rows.append(
                            f"| {rec_match.group(1)} | {rec_match.group(2)} | vs "
                            f"| {rec_match.group(3)} | {rec_match.group(4)} |"
                        )
                    else:
                        # Full team names section
                        if not pipe_rows:
                            pipe_rows.append("| Home | vs | Away |")
                            pipe_rows.append("|------|----|-----|")
                        pipe_rows.append(f"| {home} | vs | {away} |")

            if pipe_rows:
                table_text = "\n".join(pipe_rows)
                table_block = self._format_as_table(table_text)
                if table_block:
                    # Ensure unique block_id per table
                    table_block["block_id"] = f"fantasy_table_{table_index}"
                    blocks.append(table_block)
                    table_index += 1

        return blocks if len(blocks) > 1 else []

    # ------------------------------------------------------------------
    # Standings block formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _is_standings(text: str) -> bool:
        """Heuristic: does the message look like a standings report?"""
        return text.strip().startswith("Current Standings")

    def _format_standings(self, text: str) -> list:
        """Build Block Kit blocks for a standings message.

        Parses lines like ``1: (0-0) Scireland Smooth Brains`` into a
        4-column table: | # | Record | Team |
        """
        lines = text.splitlines()
        header = lines[0] if lines else "Current Standings"
        data_lines = [ln.strip() for ln in lines[1:] if ln.strip()]

        pipe_rows = ["| # | Record | Team |",
                     "|---|---|------|"]
        for line in data_lines:
            match = re.match(r'(\d+):\s*\(([\d-]+)\)\s+(.+)', line)
            if match:
                pipe_rows.append(
                    f"| {match.group(1)} | {match.group(2)} | {match.group(3).strip()} |"
                )
            # Skip non-matching lines

        table_text = "\n".join(pipe_rows)
        table_block = self._format_as_table(table_text)
        if table_block is None:
            return []

        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": header, "emoji": True},
        }]
        blocks.append(table_block)
        return blocks

    def _build_blocks(self, text: str) -> Optional[list]:
        """Build a Block Kit ``blocks`` array from *text*, or None.

        Tries each known message format in order of specificity.  Returns
        the blocks list if any formatter matched, otherwise ``None``.
        """
        # 1. Pipe table (highest priority — most structured)
        table_block = self._format_as_table(text)
        if table_block is not None:
            return [table_block]

        # 2. Trophy report
        if self._is_trophy_message(text):
            trophy_blocks = self._format_trophies(text)
            if trophy_blocks:
                return trophy_blocks

        # 3. Waiver report (non-table form)
        if self._is_waiver_report(text):
            waiver_blocks = self._format_waiver_report(text)
            if waiver_blocks:
                return waiver_blocks

        # 4. Scoreboard (aligned-column form, not pipe table)
        if self._is_scoreboard(text):
            sb_blocks = self._format_scoreboard(text)
            if sb_blocks:
                return sb_blocks

        # 5. Power rankings (aligned-column form, not pipe table)
        if self._is_power_rankings(text):
            pr_blocks = self._format_power_rankings(text)
            if pr_blocks:
                return pr_blocks

        # 6. Matchups
        if self._is_matchups(text):
            mu_blocks = self._format_matchups(text)
            if mu_blocks:
                return mu_blocks

        # 7. Standings
        if self._is_standings(text):
            st_blocks = self._format_standings(text)
            if st_blocks:
                return st_blocks

        return None

    # ------------------------------------------------------------------
    # Dispatch: actually send the message
    # ------------------------------------------------------------------

    def _send_via_web_api(self, text: str, message: str):
        """Post via chat.postMessage using a bot token.

        When the message contains structured content (tables, trophies,
        waiver reports, scoreboards, power rankings) we additionally send a
        ``blocks`` array containing Block Kit blocks, giving Slack a rich
        native rendering.  The ``text`` field (code-block wrapped) is always
        included as the fallback for clients that cannot render blocks.
        """
        payload = {
            "channel": self.channel,
            "text": message  # limit 40000
        }

        blocks = self._build_blocks(text)
        if blocks:
            payload["blocks"] = blocks

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
        """Post via a legacy incoming webhook.

        Incoming webhooks do not support the ``blocks`` array, so all
        messages are sent as plain code-block text regardless of content.
        """
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


# ------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------

def _starts_with_emoji(text: str) -> bool:
    """Return True if *text* starts with an emoji character."""
    if not text:
        return False
    # Check common trophy/reporting emojis used in ESPN fantasy messages
    trophy_emojis = [
        "👑", "💩", "😱", "😅", "🍀", "😡",
        "📈", "📉", "🟢", "🔻", "🟰",
        "🏆", "🎯", "🔥", "🧊", "⚡", "🛡️",
        "🔒", "🔧", "🟡", "🔴", "🔵", "🟠",
        "🟢", "🔻", "🟣", "🏁", "🏈", "🏈",
        "🤖", "🤡",
        # Emoji shortcodes that may appear as literal text
        ":chart_with_downwards_trend:",
    ]
    return any(text.startswith(emoji) for emoji in trophy_emojis)

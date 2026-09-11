import pytest
import sys
import os
import json
sys.path.insert(1, os.path.abspath('.'))
from gamedaybot.chat.slack import Slack, SlackException
from unittest.mock import patch, Mock


# ------------------------------------------------------------------
# Test fixtures and helpers
# ------------------------------------------------------------------

@pytest.fixture
def slack_web_api():
    """A Slack instance configured for Web API mode with mock token/channel."""
    return Slack(
        webhook_url="https://hooks.slack.com/services/test",
        bot_token="xoxb-test-token",
        channel="#general",
    )


@pytest.fixture
def slack_webhook():
    """A Slack instance configured for webhook-only mode."""
    return Slack(webhook_url="https://hooks.slack.com/services/test")


def make_mock_response(status_code=200, json_body=None):
    """Create a Mock response object similar to requests.Response."""
    resp = Mock()
    resp.status_code = status_code
    resp.content = b'{"ok": true}'
    resp.json.return_value = json_body if json_body else {"ok": True}
    return resp


def make_mock_client():
    """Create a mock requests.post that returns success."""
    mock_post = Mock(return_value=make_mock_response(200, {"ok": True, "channel": "C12345", "ts": "12345.67890"}))
    return mock_post


# ------------------------------------------------------------------
# 1. Basic webhook-only behaviour
# ------------------------------------------------------------------

class TestSlackFormatting:
    """Tests for basic Slack message formatting and webhook fallback."""

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_wrapped_in_code_blocks(self, mock_post, slack_webhook):
        """Every message sent via webhook should be wrapped in triple backticks."""
        mock_post.return_value = make_mock_response(200)
        slack_webhook.send_message("hello")
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert sent["text"] == "```hello```"

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_with_newlines_in_code_block(self, mock_post, slack_webhook):
        """Messages with newlines should still be wrapped in code blocks."""
        mock_post.return_value = make_mock_response(200)
        slack_webhook.send_message("line1\nline2")
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert sent["text"] == "```line1\nline2```"

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_scoreboard_code_block(self, mock_post, slack_webhook):
        """Scoreboard messages via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Score Update\nHome Team 120.50 -  98.25 Visitor Team"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]
        assert "Score Update" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_standings_code_block(self, mock_post, slack_webhook):
        """Standings messages via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Standings\n| Team | W | L | T | Pct |"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_waiver_report_code_block(self, mock_post, slack_webhook):
        """Waiver report messages via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Waiver Report\nTeam A\nADDED Player X"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]
        assert "Waiver Report" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_trophies_code_block(self, mock_post, slack_webhook):
        """Trophy messages via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Trophies of the week:\n👑 High score"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]
        assert "Trophies" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_power_rankings_code_block(self, mock_post, slack_webhook):
        """Power rankings via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Power Rankings\n1. Team A 99.99% - DKNG"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_matchups_code_block(self, mock_post, slack_webhook):
        """Matchup messages via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Matchup\nTeam A vs Team B"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_send_message_trades_code_block(self, mock_post, slack_webhook):
        """Trade alert messages via webhook should be code-block wrapped."""
        mock_post.return_value = make_mock_response(200)
        text = "Trade Alert\nTeam A acquires X from Team B"
        slack_webhook.send_message(text)
        sent = json.loads(mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else mock_post.call_args[1].get("data", "{}"))
        assert "```" in sent["text"]


# ------------------------------------------------------------------
# 2. Table block tests (existing)
# ------------------------------------------------------------------

class TestSlackTableBlocks:
    """Tests for Slack Block Kit table block generation."""

    def test_table_block_generated_from_pipe_table(self, slack_web_api):
        """A pipe-delimited table should be parsed into a Block Kit table block."""
        text = "| Team | W | L |\n|---|---|---|\n| DKNG | 5 | 2 |"
        block = slack_web_api._format_as_table(text)
        assert block is not None
        assert block["type"] == "table"
        assert len(block["rows"]) == 2  # header + 1 data row
        # All cells must use 'raw_text' type, not 'plain_text'
        for row in block["rows"]:
            for cell in row:
                assert cell["type"] == "raw_text"

    def test_columns_are_consistent(self, slack_web_api):
        """All rows should have the same number of columns as headers."""
        text = "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |"
        block = slack_web_api._format_as_table(text)
        assert block is not None
        num_cols = len(block["rows"][0])
        for row in block["rows"]:
            assert len(row) == num_cols

    def test_parse_table_no_pipes(self, slack_web_api):
        """Text without pipe characters should return None."""
        assert slack_web_api._parse_table("plain text") is None

    def test_parse_table_single_row(self, slack_web_api):
        """A single piped line is not a table."""
        assert slack_web_api._parse_table("| a | b |\n") is None

    def test_parse_table_dash_separator(self, slack_web_api):
        """Tables with --- separator row should correctly identify headers."""
        text = "| H1 | H2 |\n|----|----|\n| d1 | d2 |"
        result = slack_web_api._parse_table(text)
        assert result is not None
        headers, rows = result
        assert headers == ["H1", "H2"]
        assert rows == [["d1", "d2"]]

    def test_parse_table_no_separator(self, slack_web_api):
        """Tables without a separator should still parse (headers from first row)."""
        text = "| H1 | H2 |\n| d1 | d2 |"
        result = slack_web_api._parse_table(text)
        assert result is not None

    def test_table_block_scoreboard(self, slack_web_api):
        """Scoreboard text should be converted to a table block with correct columns."""
        text = "Score Update\nDKNG 120.34 -  98.56 PNLF"
        blocks = slack_web_api._format_scoreboard(text)
        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"
        table_block = blocks[1]
        assert table_block["type"] == "table"
        rows = table_block["rows"]
        assert len(rows) == 2  # header + data
        assert rows[0][0]["text"] == "Home"
        assert rows[1][0]["text"] == "DKNG"


# ------------------------------------------------------------------
# 3. Trophy block formatting tests
# ------------------------------------------------------------------

class TestSlackTrophyBlocks:
    """Tests for trophy report Block Kit formatting."""

    def test_trophy_report_gets_blocks(self, slack_web_api):
        """A trophy report message should produce header + rich_text blocks."""
        text = (
            "Trophies of the week:\n"
            "👑 High score 👑\n"
            "DKNG smashed the competition with 150.25 points!\n"
            "\n"
            "💩 Lowest score 💩\n"
            "PNLF barely reached 50 points."
        )
        blocks = slack_web_api._format_trophies(text)
        assert len(blocks) >= 2

    def test_trophy_divider_between_entries(self, slack_web_api):
        """Divider blocks should separate multiple trophy entries."""
        text = (
            "Trophies of the week:\n"
            "👑 High score 👑\n"
            "DKNG won big.\n"
            "💩 Lowest score 💩\n"
            "PNLF lost badly."
        )
        blocks = slack_web_api._format_trophies(text)
        dividers = [b for b in blocks if b.get("type") == "divider"]
        assert len(dividers) >= 1

    def test_trophy_header_blocks(self, slack_web_api):
        """Each trophy should get a header block with its emoji name."""
        text = (
            "Trophies of the week:\n"
            "👑 High score 👑\n"
            "DKNG won.\n"
        )
        blocks = slack_web_api._format_trophies(text)
        headers = [b for b in blocks if b.get("type") == "header"]
        assert len(headers) >= 2  # main title + trophy header

    def test_trophy_rich_text_detail(self, slack_web_api):
        """Trophy detail text should go in a rich_text block."""
        text = (
            "Trophies of the week:\n"
            "👑 High score 👑\n"
            "DKNG won big with 150 points!"
        )
        blocks = slack_web_api._format_trophies(text)
        rich_text_blocks = [b for b in blocks if b.get("type") == "rich_text"]
        assert len(rich_text_blocks) >= 1

    def test_empty_trophy_message_returns_empty(self, slack_web_api):
        """A trophy message with only the title but no trophy entries should return empty."""
        text = "Trophies of the week:\n"
        blocks = slack_web_api._format_trophies(text)
        assert blocks == []

    def test_trophy_emoji_detection(self, slack_web_api):
        """_starts_with_emoji should correctly detect trophy emojis."""
        from gamedaybot.chat.slack import _starts_with_emoji
        assert _starts_with_emoji("👑 High score") is True
        assert _starts_with_emoji("plain text") is False
        assert _starts_with_emoji("💩 Bad week") is True

    def test_trophy_send_message_via_web_api(self, slack_web_api):
        """Sending a trophy report via Web API should include blocks."""
        with patch("gamedaybot.chat.slack.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(
                200, {"ok": True, "channel": "C12345", "ts": "123.456"}
            )
            text = "Trophies of the week:\n👑 High score 👑\nDKNG won."
            slack_web_api.send_message(text)
            sent = json.loads(mock_post.call_args[1]["data"])
            assert "blocks" in sent
            assert len(sent["blocks"]) >= 2


# ------------------------------------------------------------------
# 4. Waiver report block formatting tests
# ------------------------------------------------------------------

class TestSlackWaiverBlocks:
    """Tests for waiver report Block Kit formatting."""

    def test_waiver_report_gets_blocks(self, slack_web_api):
        """A waiver report should produce header + section blocks."""
        text = (
            "Waiver Report\n"
            "Dynasty Kings\n"
            "ADDED Breece Hall (RB)\n"
            "DROPPED Alexander Mattison (RB)\n"
            "Primeurs\n"
            "ADDED Travis Kelce (TE)"
        )
        blocks = slack_web_api._format_waiver_report(text)
        assert len(blocks) >= 2
        # Header + 2 team sections = 3 blocks
        sections = [b for b in blocks if b.get("type") == "section"]
        assert len(sections) == 2

    def test_waiver_sections_per_team(self, slack_web_api):
        """Each team should get its own section block."""
        text = (
            "Waiver Report\n"
            "Team A\n"
            "ADDED Player1\n"
            "Team B\n"
            "DROPPED Player2"
        )
        blocks = slack_web_api._format_waiver_report(text)
        sections = [b for b in blocks if b.get("type") == "section"]
        assert len(sections) == 2

    def test_waiver_mrkdwn_styling(self, slack_web_api):
        """Added lines should use bold, dropped lines should use strikethrough."""
        text = (
            "Waiver Report\n"
            "Dynasty Kings\n"
            "ADDED Breece Hall"
        )
        blocks = slack_web_api._format_waiver_report(text)
        sections = [b for b in blocks if b.get("type") == "section"]
        section_text = sections[0]["text"]["text"]
        assert "*Dynasty Kings*" in section_text
        assert "ADDED" in section_text

    def test_waiver_dropped_strikethrough(self, slack_web_api):
        """DROPPED lines should use strikethrough (~text~)."""
        text = "Waiver Report\nTeam A\nDROPPED Player X"
        blocks = slack_web_api._format_waiver_report(text)
        sections = [b for b in blocks if b.get("type") == "section"]
        section_text = sections[0]["text"]["text"]
        assert "~DROPPED~" in section_text

    def test_waiver_team_with_no_moves(self, slack_web_api):
        """A team with no moves should still get a section block."""
        text = "Waiver Report\nTeam A"
        blocks = slack_web_api._format_waiver_report(text)
        sections = [b for b in blocks if b.get("type") == "section"]
        assert len(sections) == 1
        assert "*Team A*" in sections[0]["text"]["text"]

    def test_waiver_send_message_via_web_api(self, slack_web_api):
        """Sending a waiver report via Web API should include blocks."""
        with patch("gamedaybot.chat.slack.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(
                200, {"ok": True, "channel": "C12345", "ts": "123.456"}
            )
            text = "Waiver Report\nTeam A\nADDED Player X"
            slack_web_api.send_message(text)
            sent = json.loads(mock_post.call_args[1]["data"])
            assert "blocks" in sent
            assert len(sent["blocks"]) >= 2


# ------------------------------------------------------------------
# 5. Power rankings block formatting tests
# ------------------------------------------------------------------

class TestSlackPowerRankingsBlocks:
    """Tests for power rankings Block Kit formatting."""

    def test_power_rankings_gets_table_block(self, slack_web_api):
        """Power rankings text should produce a header + table + context blocks."""
        text = (
            "Power Rankings\n"
            "99.99[🟢12.5%] (87.5) - DKNG\n"
            "98.50[🔻3.2%] (80.0) - PNLF"
        )
        blocks = slack_web_api._format_power_rankings(text)
        assert len(blocks) >= 2
        table_blocks = [b for b in blocks if b.get("type") == "table"]
        assert len(table_blocks) == 1

    def test_power_rankings_has_context_block(self, slack_web_api):
        """Power rankings blocks should include a context block explaining emojis."""
        text = "Power Rankings\n99.99[🟢12.5%] (87.5) - DKNG"
        blocks = slack_web_api._format_power_rankings(text)
        contexts = [b for b in blocks if b.get("type") == "context"]
        assert len(contexts) == 1

    def test_power_rankings_table_has_correct_headers(self, slack_web_api):
        """The table block should have correct column headers."""
        text = "Power Rankings\n99.99[🟢] (87.5) - DKNG"
        blocks = slack_web_api._format_power_rankings(text)
        table_block = next(b for b in blocks if b.get("type") == "table")
        headers = [c["text"] for c in table_block["rows"][0]]
        assert "#" in headers
        assert "Team" in headers

    def test_power_rankings_parses_score_and_playoff(self, slack_web_api):
        """Score and playoff percentage should be parsed into table cells."""
        text = (
            "Power Rankings\n"
            "95.50[🔻5.0%] (70.0) - TeamA\n"
            "90.25[🟢3.0%] (65.0) - TeamB"
        )
        blocks = slack_web_api._format_power_rankings(text)
        table_block = next(b for b in blocks if b.get("type") == "table")
        rows = table_block["rows"]
        assert len(rows) == 3  # header + 2 teams
        # Check team A data row
        row1 = rows[1]
        assert row1[4]["text"] == "TeamA"
        assert row1[1]["text"] == "95.50"

    def test_power_rankings_header_block(self, slack_web_api):
        """The first block should be a header with 'Power Rankings'."""
        text = "Power Rankings\n99.99[🟢] (87.5) - DKNG"
        blocks = slack_web_api._format_power_rankings(text)
        assert blocks[0]["type"] == "header"
        assert "Power Rankings" in blocks[0]["text"]["text"]

    def test_power_rankings_send_message_via_web_api(self, slack_web_api):
        """Sending power rankings via Web API should include blocks."""
        with patch("gamedaybot.chat.slack.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(
                200, {"ok": True, "channel": "C12345", "ts": "123.456"}
            )
            text = "Power Rankings\n99.99[🟢] (87.5) - DKNG"
            slack_web_api.send_message(text)
            sent = json.loads(mock_post.call_args[1]["data"])
            assert "blocks" in sent


# ------------------------------------------------------------------
# 6. Scoreboard block formatting tests
# ------------------------------------------------------------------

class TestSlackScoreboardBlocks:
    """Tests for scoreboard Block Kit formatting."""

    def test_scoreboard_gets_table_block(self, slack_web_api):
        """Scoreboard messages should produce a header + table block."""
        text = (
            "Score Update\n"
            "DKNG  120.34 -  98.56 PNLF\n"
            "TEAM2  85.00 - 100.50 TEAM3"
        )
        blocks = slack_web_api._format_scoreboard(text)
        assert len(blocks) >= 2
        table_blocks = [b for b in blocks if b.get("type") == "table"]
        assert len(table_blocks) == 1

    def test_scoreboard_header_block(self, slack_web_api):
        """First block should be a header with the scoreboard title."""
        text = "Score Update\nDKNG 120.34 - 98.56 PNLF"
        blocks = slack_web_api._format_scoreboard(text)
        assert blocks[0]["type"] == "header"
        assert blocks[0]["text"]["text"] == "Score Update"

    def test_scoreboard_parses_home_away(self, slack_web_api):
        """Home and away team abbreviations should be parsed into table cells."""
        text = "Score Update\nDKNG  120.34 -  98.56 PNLF"
        blocks = slack_web_api._format_scoreboard(text)
        table_block = next(b for b in blocks if b.get("type") == "table")
        rows = table_block["rows"]
        assert rows[1][0]["text"] == "DKNG"
        assert rows[1][4]["text"] == "PNLF"

    def test_scoreboard_parses_scores(self, slack_web_api):
        """Home and away scores should be parsed into table cells."""
        text = "Score Update\nDKNG  120.34 -  98.56 PNLF"
        blocks = slack_web_api._format_scoreboard(text)
        table_block = next(b for b in blocks if b.get("type") == "table")
        rows = table_block["rows"]
        assert rows[1][1]["text"] == "120.34"
        assert rows[1][3]["text"] == "98.56"

    def test_scoreboard_send_message_via_web_api(self, slack_web_api):
        """Sending scoreboard via Web API should include blocks."""
        with patch("gamedaybot.chat.slack.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(
                200, {"ok": True, "channel": "C12345", "ts": "123.456"}
            )
            text = "Score Update\nDKNG 120.34 - 98.56 PNLF"
            slack_web_api.send_message(text)
            sent = json.loads(mock_post.call_args[1]["data"])
            assert "blocks" in sent


# ------------------------------------------------------------------
# 7. Block dispatch and edge case tests
# ------------------------------------------------------------------

class TestSlackBlockDispatch:
    """Tests for the block dispatch logic in _build_blocks."""

    def test_pipe_table_takes_priority(self, slack_web_api):
        """Pipe tables should be detected before trophy/waiver heuristics."""
        text = "| H1 | H2 |\n|----|----|\n| d1 | d2 |"
        blocks = slack_web_api._build_blocks(text)
        assert blocks is not None
        assert blocks[0]["type"] == "table"

    def test_trophy_message_detected(self, slack_web_api):
        """Messages starting with 'Trophies of the week' should be detected."""
        text = "Trophies of the week:\n👑 High score 👑\nDKNG won."
        assert slack_web_api._is_trophy_message(text) is True

    def test_waiver_report_detected(self, slack_web_api):
        """Messages starting with 'Waiver Report' should be detected."""
        text = "Waiver Report\nTeam A\nADDED Player X"
        assert slack_web_api._is_waiver_report(text) is True

    def test_scoreboard_detected(self, slack_web_api):
        """Scoreboard messages should be detected."""
        text = "Score Update\nDKNG 120.34 - 98.56 PNLF"
        assert slack_web_api._is_scoreboard(text) is True

    def test_power_rankings_detected(self, slack_web_api):
        """Power rankings messages should be detected."""
        text = "Power Rankings\n1. DKNG 99.99%"
        assert slack_web_api._is_power_rankings(text) is True

    def test_plain_message_no_blocks(self, slack_web_api):
        """Plain messages without structure should not produce blocks."""
        text = "Just a regular message with no special formatting."
        assert slack_web_api._build_blocks(text) is None

    def test_webhook_does_not_get_blocks(self, slack_webhook):
        """Webhook-only mode should not send blocks."""
        with patch("gamedaybot.chat.slack.requests.post") as mock_post:
            mock_post.return_value = make_mock_response(200)
            slack_webhook.send_message("Simple text message")
            sent = json.loads(mock_post.call_args[1]["data"])
            assert "blocks" not in sent
            assert "text" in sent


class TestSlackEmptyAndEdgeCases:
    """Tests for edge cases and error handling."""

    @patch("gamedaybot.chat.slack.requests.post")
    def test_empty_message_still_sends_text(self, mock_post, slack_web_api):
        """Empty messages should still send via code-block wrapping."""
        mock_post.return_value = make_mock_response(200, {"ok": True})
        slack_web_api.send_message("")
        sent = json.loads(mock_post.call_args[1]["data"])
        assert sent["text"] == "``````"

    @patch("gamedaybot.chat.slack.requests.post")
    def test_whitespace_only_message(self, mock_post, slack_web_api):
        """Whitespace-only messages should still send without error."""
        mock_post.return_value = make_mock_response(200, {"ok": True})
        slack_web_api.send_message("   \n\n  ")
        sent = json.loads(mock_post.call_args[1]["data"])
        assert "```" in sent["text"]

    @patch("gamedaybot.chat.slack.requests.post")
    def test_non_200_status_raises_exception(self, mock_post, slack_web_api):
        """HTTP errors from Slack API should raise SlackException."""
        mock_post.return_value = make_mock_response(500, {"ok": False, "error": "server_error"})
        with pytest.raises(SlackException):
            slack_web_api.send_message("test")

    @patch("gamedaybot.chat.slack.requests.post")
    def test_slack_api_error_raises_exception(self, mock_post, slack_web_api):
        """Slack API returning ok=false should raise SlackException."""
        mock_post.return_value = make_mock_response(200, {"ok": False, "error": "channel_not_found"})
        with pytest.raises(SlackException):
            slack_web_api.send_message("test")

    @patch("gamedaybot.chat.slack.requests.post")
    def test_webhook_non_200_raises_exception(self, mock_post, slack_webhook):
        """Webhook HTTP errors should raise SlackException."""
        mock_post.return_value = make_mock_response(500)
        with pytest.raises(SlackException):
            slack_webhook.send_message("test")

    @patch("gamedaybot.chat.slack.requests.post")
    def test_webhook_without_blocks(self, mock_post, slack_webhook):
        """Webhooks should only send text (no blocks key)."""
        mock_post.return_value = make_mock_response(200)
        slack_webhook.send_message("Plain webhook message")
        sent = json.loads(mock_post.call_args[1]["data"])
        assert "blocks" not in sent
        assert sent["text"] == "```Plain webhook message```"

    @patch("gamedaybot.chat.slack.requests.post")
    def test_web_api_auth_header(self, mock_post, slack_web_api):
        """Web API requests should include Authorization header with token."""
        mock_post.return_value = make_mock_response(200, {"ok": True})
        slack_web_api.send_message("test")
        headers = mock_post.call_args[1]["headers"]
        assert "Authorization" in headers
        assert "Bearer" in headers["Authorization"]

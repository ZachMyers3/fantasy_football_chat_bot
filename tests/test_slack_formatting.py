import pytest
import sys
import os
import json
sys.path.insert(1, os.path.abspath('.'))
from gamedaybot.chat.slack import Slack, SlackException

SLACK_API_BASE = "https://slack.com/api"


@pytest.fixture
def slack():
    return Slack("https://hooks.slack.com/services/placeholder", "xoxb-test", "#league")


@pytest.fixture
def mock_requests():
    import requests_mock
    with requests_mock.Mocker() as m:
        yield m


class TestSlackFormatting:
    """Verify that Slack wraps each message type in a triple-backtick code block."""

    # --- Message fixtures taken from README examples ------------------------

    TROPHIES = """Trophies of the week:
👑 High score 👑
Dynasty Kings with 187.34 points
💩 Low score 💩
Punt Life with 72.18 points"""

    SCOREBOARD = """Score Update
DKNG 120.34 -  98.56 PNLF
GRDG 145.22 - 134.18 VCTS
ALMT  87.50 - 102.44 BGLS

Approximate Projected Scores
DKNG 118.90 - 101.22 PNLF
GRDG 139.75 - 128.60 VCTS
ALMT  94.10 -  99.80 BGLS"""

    STANDINGS = """Current Standings
 1: (10-3 ) Dynasty Kings
 2: ( 9-4 ) Gridiron Gods
 3: ( 8-5 ) The Victors"""

    MATCHUPS = """Matchups
Dynasty Kings vs Punt Life
Gridiron Gods vs The Victors

DKNG (8-4)  vs  (5-7) PNLF
GRDG (7-5)  vs  (9-3) VCTS"""

    CLOSE_SCORES = """Projected Close Scores
DKNG 142.50 - 138.25 PNLF
GRDG 115.88 - 118.44 VCTS"""

    MONITOR = """Starting Players to Monitor
Dynasty Kings:
QB Lamar Jackson - Questionable
WR Cooper Kupp - Out
TE Dalton Kincaid - BYE"""

    WAIVER_REPORT = """Waiver Report 2026-10-15:
Dynasty Kings
ADDED QB - Josh Allen ($85, won by $40)
DROPPED QB - Gardner Minshew

Gridiron Gods
ADDED RB - Gus Edwards ($12, Punt Life outbid by $1)
DROPPED WR - Kendall Hinton"""

    POWER_RANKINGS = """Power Rankings (Playoff %)
99.99[🟢12.5%] (87.5) - DKNG
85.25[🔻 8.2%]  (62.5) - VCTS
78.10[🟢 1.4%] (50.0) - GRDG"""

    INIT_MESSAGE = "GameDayBot is online and ready to serve this league! 🏈"

    # --- Expected payload helper --------------------------------------------

    def _expect_format(self, slack, mock_requests, message):
        """Capture what would actually be POSTed to the Slack Web API."""
        mock_requests.post(
            SLACK_API_BASE + "/chat.postMessage",
            json={"ok": True},
        )
        slack.send_message(message)
        request_body = json.loads(mock_requests.last_request.text)
        assert request_body == {
            "channel": "#league",
            "text": "```{0}```".format(message),
        }

    # --- Per-type formatting tests -----------------------------------------

    def test_trophies_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.TROPHIES)

    def test_scoreboard_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.SCOREBOARD)

    def test_standings_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.STANDINGS)

    def test_matchups_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.MATCHUPS)

    def test_close_scores_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.CLOSE_SCORES)

    def test_monitor_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.MONITOR)

    def test_waiver_report_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.WAIVER_REPORT)

    def test_power_rankings_formatting(self, slack, mock_requests):
        self._expect_format(slack, slack.__class__ and mock_requests, self.POWER_RANKINGS)

    def test_init_message_formatting(self, slack, mock_requests):
        self._expect_format(slack, mock_requests, self.INIT_MESSAGE)


class TestSlackWebhookFallbackFormatting:
    """When only a webhook is configured (no bot token), messages still
    get wrapped in the code-block and POSTed to the webhook URL."""

    def test_webhook_wraps_message(self, mock_requests):
        slack = Slack("https://hooks.slack.com/services/test/T1/B1")
        mock_requests.post("https://hooks.slack.com/services/test/T1/B1", status_code=200)

        slack.send_message("Hello Slack")

        body = json.loads(mock_requests.last_request.text)
        assert body == {"text": "```Hello Slack```"}


class TestSlackErrorHandling:
    """Error paths for both transports."""

    def test_web_api_http_error(self, mock_requests):
        slack = Slack("https://hooks.slack.com/services/x", "xoxb-test", "#league")
        mock_requests.post(SLACK_API_BASE + "/chat.postMessage", status_code=403)
        with pytest.raises(SlackException):
            slack.send_message("boom")

    def test_web_api_ok_false(self, mock_requests):
        slack = Slack("https://hooks.slack.com/services/x", "xoxb-test", "#league")
        mock_requests.post(
            SLACK_API_BASE + "/chat.postMessage",
            json={"ok": False, "error": "channel_not_found"},
        )
        with pytest.raises(SlackException):
            slack.send_message("boom")

    def test_webhook_http_error(self, mock_requests):
        slack = Slack("https://hooks.slack.com/services/errcase")
        mock_requests.post("https://hooks.slack.com/services/errcase", status_code=500)
        with pytest.raises(SlackException):
            slack.send_message("boom")


class TestSlackTransportSelection:
    """Which transport does the Slack class pick for a given config?"""

    def test_uses_web_api_when_token_plus_channel(self, mock_requests):
        slack = Slack("https://hooks.slack.com/services/ignored", "xoxb-real", "#chan")
        mock_requests.post(SLACK_API_BASE + "/chat.postMessage", json={"ok": True})
        slack.send_message("hi")
        assert mock_requests.last_request.url == SLACK_API_BASE + "/chat.postMessage"
        assert mock_requests.last_request.headers["Authorization"] == "Bearer xoxb-real"

    def test_falls_back_to_webhook_when_no_token(self, mock_requests):
        slack = Slack("https://hooks.slack.com/services/fb", bot_token=1, channel=1)
        mock_requests.post("https://hooks.slack.com/services/fb", status_code=200)
        slack.send_message("hi")
        assert mock_requests.last_request.url == "https://hooks.slack.com/services/fb"
        assert "Authorization" not in mock_requests.last_request.headers

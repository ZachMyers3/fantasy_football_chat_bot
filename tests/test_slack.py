import pytest
import sys
import os
sys.path.insert(1, os.path.abspath('.'))
from gamedaybot.chat.slack import (Slack, SlackException, )


WEBHOOK_URL = "https://hooks.slack.com/services/A1B2C3/ABC1ABC2/abcABC1abcABC2"
BOT_TOKEN = "xoxb-test-placeholder-not-a-real-token"


@pytest.mark.usefixtures("mock_requests")
class TestSlack:
    '''Test SlackBot class'''

    def setup_method(self):
        self.test_text = "This is a test."

    def _make_webhook_bot(self):
        return Slack(WEBHOOK_URL)

    def _make_web_api_bot(self):
        return Slack(WEBHOOK_URL, bot_token=BOT_TOKEN, channel="#general")

    # --- legacy webhook transport ---

    def test_send_message(self, mock_requests):
        '''Does the message send successfully via webhook?'''
        mock_requests.post(WEBHOOK_URL, status_code=200)
        assert self._make_webhook_bot().send_message(self.test_text).status_code == 200

    def test_bad_webhook(self, mock_requests):
        '''Does the expected error raise when a webhook url is incorrect?'''
        mock_requests.post(WEBHOOK_URL, status_code=404)
        with pytest.raises(SlackException):
            self._make_webhook_bot().send_message(self.test_text)

    # --- Web API transport (chat.postMessage) ---

    def test_web_api_send_message(self, mock_requests):
        '''Does the message send successfully via chat.postMessage?'''
        mock_requests.post("https://slack.com/api/chat.postMessage",
                           status_code=200,
                           json={"ok": True, "channel": "C12345", "ts": "1234567890.123456"})
        bot = self._make_web_api_bot()
        response = bot.send_message(self.test_text)
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_web_api_no_token_falls_back_to_webhook(self, mock_requests):
        '''When bot_token is 1 (unset), Web API is not used.'''
        mock_requests.post(WEBHOOK_URL, status_code=200)
        bot = Slack(WEBHOOK_URL, bot_token=1, channel="#general")
        assert bot._use_web_api() is False
        assert bot.send_message(self.test_text).status_code == 200

    def test_web_api_no_channel_falls_back_to_webhook(self, mock_requests):
        '''When channel is 1 (unset), Web API is not used.'''
        mock_requests.post(WEBHOOK_URL, status_code=200)
        bot = Slack(WEBHOOK_URL, bot_token=BOT_TOKEN, channel=1)
        assert bot._use_web_api() is False
        assert bot.send_message(self.test_text).status_code == 200

    def test_web_api_uses_api_when_configured(self, mock_requests):
        '''When both bot_token and channel are set, the Web API endpoint is hit.'''
        api_mock = mock_requests.post("https://slack.com/api/chat.postMessage",
                                      status_code=200,
                                      json={"ok": True})
        bot = self._make_web_api_bot()
        assert bot._use_web_api() is True
        bot.send_message(self.test_text)
        assert api_mock.called
        assert api_mock.last_request.headers["Authorization"] == "Bearer {0}".format(BOT_TOKEN)

    def test_web_api_http_error(self, mock_requests):
        '''An HTTP error from chat.postMessage raises SlackException.'''
        mock_requests.post("https://slack.com/api/chat.postMessage", status_code=500)
        with pytest.raises(SlackException):
            self._make_web_api_bot().send_message(self.test_text)

    def test_web_api_api_error(self, mock_requests):
        '''A Slack API-level error (ok: false) raises SlackException.'''
        mock_requests.post("https://slack.com/api/chat.postMessage",
                           status_code=200,
                           json={"ok": False, "error": "invalid_auth"})
        with pytest.raises(SlackException):
            self._make_web_api_bot().send_message(self.test_text)

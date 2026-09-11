import requests
import json
import logging

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
       ID or name. Supports any channel the app's bot is a member of.

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
            return self._send_via_web_api(message)
        return self._send_via_webhook(message)

    def _use_web_api(self) -> bool:
        """True when a usable bot token and channel are both configured."""

        return (self.bot_token is not None and
                self.bot_token not in (1, "1", '') and
                self.channel is not None and
                self.channel not in (1, "1", ''))

    def _send_via_web_api(self, message: str):
        """Post via chat.postMessage using a bot token."""

        payload = {
            "channel": self.channel,
            "text": message  # limit 40000
        }

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

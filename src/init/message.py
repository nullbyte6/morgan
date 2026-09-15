"""Send messages through the configured provider, resolving contacts on demand."""
import json
import os
import re
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .config import HOME_PATH, load_config

CONTACTS_FILE = HOME_PATH / 'json' / 'contacts.json'


def _name(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                           if not unicodedata.combining(c)).split())


def _phone(value):
    number = re.sub(r'[\s().-]', '', value)
    if number.startswith('00'):
        number = '+' + number[2:]
    if not re.fullmatch(r'\+[1-9][0-9]{6,14}', number):
        raise ValueError('Specify an international phone number including + and country code')
    return number[1:]


def _result(status, **details):
    return json.dumps({'status': status, **details}, ensure_ascii=False)


class MessageService:
    def send(self, message: str = '', recipient: str = '') -> str:
        """Send using config.json to an exact contact name or international number.

        Missing or ambiguous details require asking the user and waiting.
        Submitted means API acceptance, not confirmed delivery.
        """
        if not recipient.strip():
            return _result('needs_input', question='Who should receive the message: a contact or international phone number?')
        if not message.strip():
            return _result('needs_input', question='What message should I send?')
        if len(message) > 4096:
            return _result('error', error='Text messages support at most 4096 characters')
        recipient = recipient.strip()
        try:
            if re.match(r'^[+0-9]', recipient):
                number = _phone(recipient)
            else:
                try:
                    contacts = json.loads(CONTACTS_FILE.read_text(encoding='utf-8-sig'))
                except FileNotFoundError:
                    return _result('needs_input', question='No contacts file exists. What international phone number should I use?')
                if not isinstance(contacts, list) or any(
                    not isinstance(c, dict) or not isinstance(c.get('name'), str)
                    or not isinstance(c.get('phone'), str) for c in contacts
                ):
                    raise ValueError('contacts.json must be a list of objects with name and phone text fields')
                matches = [c for c in contacts if _name(c['name']) == _name(recipient)]
                if not matches:
                    return _result('needs_input', question='Contact not found. Ask for the exact saved name or an international phone number.')
                if len(matches) > 1:
                    return _result('needs_input', question='Several contacts match. Ask the user to choose a phone number.', contacts=matches)
                number = _phone(matches[0]['phone'])
        except (OSError, ValueError) as error:
            return _result('error', error=str(error))
        config = load_config()
        service = config['message_service'].strip().casefold()
        if service != 'whatsapp':
            return _result('error', error='Unsupported message_service; currently only whatsapp is implemented')
        phone_id = config['whatsapp_phone_number_id'].strip()
        version = config['whatsapp_api_version'].strip()
        token = os.environ.get('ACCESS_TOKEN', '').strip()
        if not re.fullmatch(r'[0-9]+', phone_id):
            return _result('error', error="Set whatsapp_phone_number_id to Meta's sender phone number ID, not your telephone number")
        if not re.fullmatch(r'v[0-9]+\.0', version):
            return _result('error', error='Set whatsapp_api_version to a supported Meta Graph API version in vNN.0 format')
        if not token:
            return _result('error', error='Set the ACCESS_TOKEN environment variable for WhatsApp Cloud API')
        request = Request(
            f'https://graph.facebook.com/{version}/{phone_id}/messages',
            data=json.dumps({'messaging_product': service, 'to': number,
                             'type': 'text', 'text': {'body': message}}).encode('utf-8'),
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as error:
            return _result('error', error=f'WhatsApp API rejected the request (HTTP {error.code})')
        except (URLError, TimeoutError, OSError, ValueError):
            return _result('unknown', error='Could not confirm API acceptance. Do not retry automatically; the message may have been submitted.')
        messages = payload.get('messages') if isinstance(payload, dict) else None
        if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict) or not messages[0].get('id'):
            return _result('unknown', error='API response has no message ID. Do not claim success or retry automatically.')
        return _result('submitted', service=service, recipient='+' + number,
                       message_id=messages[0]['id'], delivery_confirmed=False)


def send_message(message: str = '', recipient: str = '') -> str:
    """Send message to a contact name or international number using config.json.

    If recipient or message is missing or ambiguous, ask the user and wait.
    Report submitted as API acceptance, never as confirmed delivery.
    """
    return MessageService().send(message=message, recipient=recipient)

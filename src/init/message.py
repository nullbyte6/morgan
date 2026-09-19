#  Copyright (c) 2026 Diego.
#
#  SPDX-License-Identifier: GPL-3.0-or-later
#
#  This file is part of arlo.
#
#  This program is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation, either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty
#  of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#  See the GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <https://www.gnu.org/licenses/>.
"""Send messages through the configured provider, resolving contacts on demand."""
from src.init.lang import tr
import json
import os
import re
import unicodedata
import base64
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .config import HOME_PATH, load_config

CONTACTS_FILE = HOME_PATH / 'json' / 'contacts.json'


def _name(value):
    return ' '.join(
        ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                if not unicodedata.combining(c)).split())


def _phone(value):
    number = re.sub(r'[\s().-]', '', value)
    if number.startswith('00'):
        number = '+' + number[2:]
    if not re.fullmatch(r'\+[1-9][0-9]{6,14}', number):
        raise ValueError(
            tr('message.specify_an_international_phone_number_including_and_country_code'))
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
            return _result('needs_input',
                           question=tr('message.who_should_receive_the_message_a_contact_or_international_phone'))
        if not message.strip():
            return _result('needs_input',
                           question=tr('message.what_message_should_i_send'))
        if len(message) > 4096:
            return _result('error',
                           error=tr('message.text_messages_support_at_most_4096_characters'))
        recipient = recipient.strip()
        try:
            if re.match(r'^[+0-9]', recipient):
                number = _phone(recipient)
            else:
                try:
                    contacts = json.loads(
                        CONTACTS_FILE.read_text(encoding='utf-8-sig'))
                except FileNotFoundError:
                    return _result('needs_input',
                                   question=tr('message.no_contacts_file_exists_what_international_phone_number_should_i'))
                if not isinstance(contacts, list) or any(
                        not isinstance(c, dict) or not isinstance(c.get('name'),
                                                                  str)
                        or not isinstance(c.get('phone'), str) for c in contacts
                ):
                    raise ValueError(
                        tr('message.contacts_json_must_be_a_list_of_objects_with_name_and_phone_text'))
                matches = [c for c in contacts if
                           _name(c['name']) == _name(recipient)]
                if not matches:
                    return _result('needs_input',
                                   question=tr('message.contact_not_found_ask_for_the_exact_saved_name_or_an_internation'))
                if len(matches) > 1:
                    return _result('needs_input',
                                   question=tr('message.several_contacts_match_ask_the_user_to_choose_a_phone_number'),
                                   contacts=matches)
                number = _phone(matches[0]['phone'])
        except (OSError, ValueError) as error:
            return _result('error', error=str(error))
        config = load_config()
        service = config['message_service'].strip().casefold()
        if service == 'twilio':
            return self._send_twilio(config, message, number)
        if service != 'whatsapp':
            return _result('error',
                           error=tr('message.unsupported_message_service_use_whatsapp_meta_or_twilio_whatsapp'))
        phone_id = config['whatsapp_phone_number_id'].strip()
        version = config['whatsapp_api_version'].strip()
        token = os.environ.get('ACCESS_TOKEN', '').strip()
        if not re.fullmatch(r'[0-9]+', phone_id):
            return _result('error',
                           error=tr('message.set_whatsapp_phone_number_id_to_meta_s_sender_phone_number_id_no'))
        if not re.fullmatch(r'v[0-9]+\.0', version):
            return _result('error',
                           error=tr('message.set_whatsapp_api_version_to_a_supported_meta_graph_api_version_i'))
        if not token:
            return _result('error',
                           error=tr('message.set_the_access_token_environment_variable_for_whatsapp_cloud_api'))
        request = Request(
            f'https://graph.facebook.com/{version}/{phone_id}/messages',
            data=json.dumps({'messaging_product': service, 'to': number,
                             'type': 'text', 'text': {'body': message}}).encode(
                'utf-8'),
            headers={'Authorization': f'Bearer {token}',
                     'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as error:
            return _result('error',
                           error=tr('message.whatsapp_api_rejected_the_request_http', value0=error.code))
        except (URLError, TimeoutError, OSError, ValueError):
            return _result('unknown',
                           error=tr('message.could_not_confirm_api_acceptance_do_not_retry_automatically_the'))
        messages = payload.get('messages') if isinstance(payload,
                                                         dict) else None
        if not isinstance(messages, list) or not messages or not isinstance(
                messages[0], dict) or not messages[0].get('id'):
            return _result('unknown',
                           error=tr('message.api_response_has_no_message_id_do_not_claim_success_or_retry_aut'))
        return _result('submitted', service=service, recipient='+' + number,
                       message_id=messages[0]['id'], delivery_confirmed=False)

    @staticmethod
    def _send_twilio(config, message, number):
        """Send a WhatsApp message through Twilio's Messages API."""
        account_sid = config['twilio_account_sid'].strip()
        auth_token = config['twilio_auth_token'].strip()
        from_number = config['twilio_from_number'].strip()
        if not re.fullmatch(r'AC[0-9a-fA-F]{32}', account_sid):
            return _result('error',
                           error=tr('message.set_twilio_account_sid_to_a_valid_twilio_account_sid'))
        if not auth_token:
            return _result('error',
                           error=tr('message.set_twilio_auth_token_to_the_twilio_auth_token'))
        if not from_number.casefold().startswith('whatsapp:'):
            return _result('error',
                           error=tr('message.set_twilio_from_number_with_the_whatsapp_prefix_e_g_whatsapp_141'))
        try:
            sender = _phone(from_number[len('whatsapp:'):])
        except ValueError:
            return _result('error',
                           error=tr('message.set_twilio_from_number_to_a_valid_twilio_whatsapp_sender_e_g_wha'))
        endpoint = f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json'
        body = urlencode({'From': 'whatsapp:+' + sender,
                          'To': 'whatsapp:+' + number,
                          'Body': message}).encode('utf-8')
        request = Request(endpoint, data=body, method='POST')
        credentials = base64.b64encode(
            f'{account_sid}:{auth_token}'.encode('utf-8')).decode('ascii')
        request.add_header('Authorization', f'Basic {credentials}')
        request.add_header('Content-Type', 'application/x-www-form-urlencoded')
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as error:
            return _result('error',
                           error=tr('message.twilio_api_rejected_the_request_http', value0=error.code))
        except (URLError, TimeoutError, OSError, ValueError):
            return _result('unknown',
                           error=tr('message.could_not_confirm_twilio_api_acceptance_do_not_retry_automatical'))
        message_id = payload.get('sid') if isinstance(payload, dict) else None
        if not message_id:
            return _result('unknown',
                           error=tr('message.twilio_response_has_no_message_id_do_not_claim_success_or_retry'))
        return _result('submitted', service='twilio', recipient='+' + number,
                       message_id=message_id, delivery_confirmed=False)


def send_message(message: str = '', recipient: str = '') -> str:
    """Send message to a contact name or international number using config.json.
    If recipient or message is missing or ambiguous, ask the user and wait.
    Report submitted as API acceptance, never as confirmed delivery.
    """
    return MessageService().send(message=message, recipient=recipient)

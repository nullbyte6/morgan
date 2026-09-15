import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src.init import message


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.contacts = Path(self.temp.name) / 'contacts.json'
        self.contacts.write_text(json.dumps([{'name': 'Mamá', 'phone': '+34600000000'}]), encoding='utf-8')
        self.config = {'message_service': 'whatsapp', 'whatsapp_phone_number_id': '12345', 'whatsapp_api_version': 'v23.0'}
        for p in (patch.object(message, 'CONTACTS_FILE', self.contacts),
                  patch.object(message, 'load_config', return_value=self.config),
                  patch.dict('os.environ', {'ACCESS_TOKEN': 'test-token'})):
            p.start()
            self.addCleanup(p.stop)
        self.post = patch.object(message, 'urlopen').start()
        self.addCleanup(patch.stopall)
        self.post.return_value.__enter__.return_value = io.StringIO('{"messages": [{"id": "test-id"}]}')

    def send(self, **kwargs):
        return json.loads(message.send_message(**kwargs))

    def test_contact_and_payload(self):
        self.assertEqual(self.send(message='Hola', recipient='mama')['status'], 'submitted')
        request = self.post.call_args.args[0]
        self.assertEqual(request.full_url, 'https://graph.facebook.com/v23.0/12345/messages')
        self.assertEqual(json.loads(request.data), {'messaging_product': 'whatsapp', 'to': '34600000000', 'type': 'text', 'text': {'body': 'Hola'}})
        self.assertEqual(self.post.call_args.kwargs['timeout'], 30)

    def test_direct_number_without_contacts(self):
        self.contacts.unlink()
        self.assertEqual(self.send(message='Hola', recipient='0034 600 000 000')['status'], 'submitted')

    def test_missing_unknown_ambiguous(self):
        for arguments in ({'message': 'Hola'}, {'recipient': 'Mamá'}, {'message': 'Hola', 'recipient': 'Nobody'}):
            self.assertEqual(self.send(**arguments)['status'], 'needs_input')
        self.contacts.write_text(json.dumps([{'name': 'Mama', 'phone': '+34600000000'}] * 2))
        self.assertEqual(self.send(message='Hola', recipient='mama')['status'], 'needs_input')
        self.post.assert_not_called()

    def test_invalid_phone_and_contacts(self):
        self.assertEqual(self.send(message='Hola', recipient='600000000')['status'], 'error')
        self.contacts.write_text('{}')
        self.assertEqual(self.send(message='Hola', recipient='Mama')['status'], 'error')
        self.post.assert_not_called()

    def test_missing_configuration_and_unsupported_service(self):
        for key, value in [('message_service', 'sms'), ('whatsapp_phone_number_id', ''), ('whatsapp_api_version', '')]:
            with patch.dict(self.config, {key: value}):
                self.assertEqual(self.send(message='Hola', recipient='+34600000000')['status'], 'error')
        with patch.dict('os.environ', {'ACCESS_TOKEN': ''}):
            self.assertEqual(self.send(message='Hola', recipient='+34600000000')['status'], 'error')
        self.post.assert_not_called()

    def test_timeout_does_not_retry(self):
        self.post.side_effect = TimeoutError()
        self.assertEqual(self.send(message='Hola', recipient='Mama')['status'], 'unknown')
        self.post.assert_called_once()

    def test_no_message_id_is_not_success(self):
        self.post.return_value.__enter__.return_value = io.StringIO('{}')
        self.assertEqual(self.send(message='Hola', recipient='Mama')['status'], 'unknown')

    def test_http_error(self):
        self.post.side_effect = message.HTTPError('https://example.invalid', 401, 'Unauthorized', {}, None)
        self.assertEqual(self.send(message='Hola', recipient='Mama')['status'], 'error')
        self.post.assert_called_once()

    def test_contacts_reloaded(self):
        self.contacts.write_text(json.dumps([{'name': 'Mama', 'phone': '+34611111111'}]))
        self.assertEqual(self.send(message='Hola', recipient='Mama')['recipient'], '+34611111111')

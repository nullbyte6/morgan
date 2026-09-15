import unittest
from src.init.config import validate_config


class MessageConfigTests(unittest.TestCase):
    def test_legacy_config_retains_custom_settings(self):
        config = validate_config({'phone_number': '+34600000000', 'custom': 'kept'})
        self.assertEqual(config['message_service'], 'whatsapp')
        self.assertEqual(config['whatsapp_phone_number_id'], '')
        self.assertEqual(config['custom'], 'kept')
        self.assertEqual(config['phone_number'], '+34600000000')

    def test_invalid_field_types(self):
        for key in ('message_service', 'whatsapp_phone_number_id', 'whatsapp_api_version'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_config({key: 123})

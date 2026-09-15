import unittest
from unittest.mock import patch
from pydantic_ai import Tool
from src.init.tools import TOOLS
from src.init.message import MessageService, send_message


class MessageIntegrationTests(unittest.TestCase):
    def test_registered_schema(self):
        tools = [Tool(function, sequential=True) for function in TOOLS]
        registered = [tool for tool in tools if tool.name == 'send_message']
        self.assertEqual(len(registered), 1)
        schema = registered[0].function_schema.json_schema
        self.assertEqual(set(schema['properties']), {'message', 'recipient'})
        self.assertFalse(schema.get('required'))

    def test_wrapper_delegates_to_service(self):
        with patch.object(MessageService, 'send', return_value='result') as send:
            self.assertEqual(send_message('Hola', 'Example'), 'result')
            send.assert_called_once_with(message='Hola', recipient='Example')

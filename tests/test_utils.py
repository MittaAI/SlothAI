import os
import sys
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(project_root)

from SlothAI.lib.util import handle_quotes, fields_from_template, extras_from_template, jinja_from_template

class TestSchemar(unittest.TestCase):

    def test_handle_quote(self):
        cases = [
            {
                "input": "featurebase's data",
                "output": "featurebase''s data",
            },
            {
                "input": ["featurebase's data", "other data", "other's data"],
                "output": ["featurebase''s data", "other data", "other''s data"],
            },
            {
                "input": 100,
                "output": 100,
            },
            {
                "input": [1, 2, 3],
                "output": [1, 2, 3],
            },
            {
                "input": "'featurebase's data'",
                "output": "''featurebase''s data''",
            },
            {
                "input": "featurebase''s data",
                "output": "featurebase''s data",
            },
        ]

        for case in cases:
            out = handle_quotes(case['input'])
            self.assertEqual(case['output'], out)

class TestTemplateUtils(unittest.TestCase):

    def test_fields_from_template(self):
        cases = [
            {
                "file": "template01.txt",
                "input_fields": [{"name": "key", "type": "string"}],
                "output_fields": [{"name": "outkey", "type": "string"}]
            },
            {
                "file": "template02.txt",
                "input_fields": [{"name": "key", "type": "string"}],
                "output_fields": [{"name": "outkey", "type": "string"}]
            },
            {
                "file": "template03.txt",
                "input_fields": None,
                "output_fields": None
            }
        ]

        for case in cases:
            with open(f"{current_dir}/data/test_utils/{case['file']}") as file:
                template = file.read()

            input_fields, output_fields = fields_from_template(template)

            if input_fields:            
                self.assertListEqual(input_fields, case['input_fields'])
            else:
                self.assertIsNone(case['input_fields'])

            if output_fields:
                self.assertListEqual(output_fields, case['output_fields'])
            else:
                self.assertIsNone(case['output_fields'])


    def test_extras_from_template(self):
        cases = [
            {
                "file": "template01.txt",
                "extras": '''[{
    'openai_token': None,
    'model': 'gpt-3.5-turbo',
    'callback_uri': 'http://localhost:8080/{{ user.uid }}/callback?token={{ user.token }}'
}]''' 
            },
            {
                "file": "template02.txt",
                "extras": "[{'openai_token': None, 'model': 'gpt-3.5-turbo', 'callback_uri': 'http://localhost:8080/{{ user.uid }}/callback?token={{ user.token }}'}]"
            },
            {
                "file": "template03.txt",
                "extras": None
            }
        ]

        for case in cases:
            with open(f"{current_dir}/data/test_utils/{case['file']}") as file:
                template = file.read()

            extras = extras_from_template(template)
            self.assertEqual(extras, case['extras'])

    def test_jinja_from_template(self):
        cases = [
            {
                "file": "template01.txt",
                "jinja": '''


{
    "outkey": {{ random_word() }}
}
'''
            },
            {
                "file": "template02.txt",
                "jinja": '''

{"outkey": {{ random_word() }}}
'''
            },
            {
                "file": "template03.txt",
                "jinja": '{"outkey": {{ random_word() }}}'
            },
            {
                "file": "template04.txt",
                "jinja": ""
            }
        ]

        for case in cases:
            with open(f"{current_dir}/data/test_utils/{case['file']}") as file:
                template = file.read()

            jinja = jinja_from_template(template)
            self.assertEqual(jinja, case['jinja'])



if __name__ == '__main__':
    unittest.main()
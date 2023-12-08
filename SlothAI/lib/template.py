import re
import ast
import json
from datetime import datetime

from SlothAI.lib.util import random_string

class MissingTemplateKey(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(f"Missing template key: {key}")

class InvalidTemplateInputFields(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(f"Invalid template input_fields: {error}")

class InvalidTemplateOutputFields(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(f"Invalid template input_fields: {error}")

class InvalidTemplateExtras(Exception):
    def __init__(self, error: str) -> None:
        super().__init__(f"Invalid template input_fields: {error}")

class Template():
    def __init__(self, id, name, user_id, text, created, input_fields, output_fields, extras, processor) -> None:
        self.id = id
        self.name = name
        self.user_id = user_id
        self.text = text
        self.created = created
        self.input_fields = input_fields # generally, derived from text
        self.output_fields = output_fields # generally, derived from text
        self.extras = extras # generally, derived from text
        self.processor = processor # generally, derived from text

    @classmethod
    def from_dict(self, dict):
        if 'name' not in dict:
            raise MissingTemplateKey('name')
        if 'user_id' not in dict and 'uid' not in dict:
            raise MissingTemplateKey('user_id or uid')
        if 'text' not in dict:
            raise MissingTemplateKey('text')
        if 'created' not in dict:
            raise MissingTemplateKey('created')

        # updates must contain keys above and derived fields will always be
        # recomputed. This makes it harder to updated a derived field without
        # updating the text of the actual template which could cause unexpected
        # results.
        input_fields, output_fields = self.fields_from_template(dict.get('text'))                
        extras = self.extras_from_template(dict.get('text'))
        processor = extras.get('processor', dict.get('processor', 'jinja2'))

        id = dict.get('id', random_string(16))
        uid = dict.get('user_id', dict.get('uid'))
        if isinstance(dict['created'], str):
            try:
                created = datetime.strptime(dict["created"], '%Y-%m-%dT%H:%M:%SZ')
            except Exception:
                created = dict['created']
        else:
            created = dict['created']

        return self(
            id=id,
            name=dict['name'],
            user_id=uid,
            text=dict['text'],
			created=created,
            input_fields=input_fields,
            output_fields=output_fields,
            extras=extras,
            processor=processor
        )

    def to_dict(self):
        if isinstance(dict['created'], str):
            created = self.created
        else:
            created = self.created.strftime('%Y-%m-%dT%H:%M:%SZ')

        return {
			"id": self.id,
			"user_id": self.user_id,
			"name": self.name,
			"text": self.text,
			"created": created,
			"input_fields": self.input_fields,
			"output_fields": self.output_fields,
			"extras": self.extras,
			"processor": self.processor,
		}
    
    def to_json(self) -> str:
        dict = self.to_dict()
        return json.dumps(dict, indent=4)

    @classmethod
    def from_json(self, json_str: str):
        dict = json.loads(json_str)
        return self.from_dict(dict)

    # TODO: create template model. these should go there.
    @classmethod
    def extras_from_template(self, template):
        # TODO: remove comments before processing...
        # only uses the last pattern. leaving these here for testing.
        # extras_pattern = re.compile(r'extras\s*=\s*{([\s\S]*?)}\s*', re.DOTALL)
        # extras_pattern = re.compile(r'extras\s*=\s*{([\s\S]*?)}\s*}', re.DOTALL)
        # extras_pattern = re.compile(r'extras\s*=\s*{.*?}', re.DOTALL)
        # extras_pattern = re.compile(r'extras\s*=\s*\{(?:\s*".*?"\s*:\s*".*?"\s*,?)*}', re.DOTALL)
        extras_pattern = re.compile(r'extras\s*=\s*{((?:[^{}]|{{[^{}]*}})*)}', re.DOTALL)
        
        extras_matches = extras_pattern.findall(template)

        try:
            extras_content = ast.literal_eval("{" + extras_matches[0] + "}")
            if not isinstance(extras_content, dict):
                raise InvalidTemplateExtras(f"extras not evaluated to dict: got {type(extras_content)}")
            return extras_content
        except Exception as ex:
            raise InvalidTemplateExtras(str(ex))

    @classmethod
    def fields_from_template(self, template):
        input_fields = []
        output_fields = []

        input_content, output_content = self.fields_text_from_template(template)

        try:
            input_fields = ast.literal_eval(input_content) if input_content else None
        except Exception as e:
            raise InvalidTemplateInputFields(str(e))
        
        try:
            output_fields = ast.literal_eval(output_content) if output_content else None
        except Exception as e:
            raise InvalidTemplateOutputFields(str(e))

        return input_fields, output_fields

    @classmethod
    def fields_text_from_template(self, template):
        # Regular expressions to find input and output fields in the template
        input_pattern = re.compile(r'input_fields\s*=\s*(\[.*?\])', re.DOTALL)
        output_pattern = re.compile(r'output_fields\s*=\s*(\[.*?\])', re.DOTALL)

        input_match = input_pattern.search(template)
        output_match = output_pattern.search(template)

        input_content = input_match.group(1) if input_match else None
        output_content = output_match.group(1) if output_match else None

        return input_content, output_content

    @classmethod
    def remove_fields_and_extras(self, template):
        # Remove extras definition
        extras_pattern = re.compile(r'extras\s*=\s*{([\s\S]*?)}\s*', re.DOTALL)
        template = extras_pattern.sub('', template)

        # Remove input_fields and output_fields definitions
        input_pattern = re.compile(r'input_fields\s*=\s*(\[.*?\])', re.DOTALL)
        output_pattern = re.compile(r'output_fields\s*=\s*(\[.*?\])', re.DOTALL)

        template = input_pattern.sub('', template)
        template = output_pattern.sub('', template)

        return template


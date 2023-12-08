import os
import sys
import unittest

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(project_root)

from SlothAI.lib.tasks import process_data_dict_for_insert
from SlothAI.lib.schemar import FBTypes

class TestTasks(unittest.TestCase):

    def test_process_data_dict_for_insert(self):
        cases = [
            {
                "name": "test prompt input",
                "table": "table00",
                "data_dict": {
                    "attributes": [[
                        "frontdoor",
                        "sound",
                        "person",
                    ]],
                    "text": ["There was a knock at the door, then silence."],
                    "embedding": [[
                        0.0001,
                        0.0002,
                        0.0003,
                        0.0004,
                    ]],
                },
                "column_type_map": {
                    "_id": FBTypes.ID,
                    "text": FBTypes.STRING,
                    "attributes": FBTypes.STRINGSET,
                    "embedding": FBTypes.VECTOR,
                },
                "columns": ["_id", "attributes", "text", "embedding"],
                "records": ["(identifier('table00'),['frontdoor','sound','person'],'There was a knock at the door, then silence.',[0.0001, 0.0002, 0.0003, 0.0004])"]
            },
            {
                "name": "test prompt input with single quote in strings",
                "table": "table00",
                "data_dict": {
                    "attributes": [[
                        "front'door",
                        "sound",
                        "person",
                    ]],
                    "text": ["There's a knock at the door, then silence."],
                    "embedding": [[
                        0.0001,
                        0.0002,
                        0.0003,
                        0.0004,
                    ]],
                },
                "column_type_map": {
                    "_id": FBTypes.ID,
                    "text": FBTypes.STRING,
                    "attributes": FBTypes.STRINGSET,
                    "embedding": FBTypes.VECTOR,
                },
                "columns": ["_id", "attributes", "text", "embedding"],
                "records": ["(identifier('table00'),['front''door','sound','person'],'There''s a knock at the door, then silence.',[0.0001, 0.0002, 0.0003, 0.0004])"]
            },
            {
                "name": "test multiple records one with single quote",
                "table": "table00",
                "data_dict": {
                    "attributes": [
                        ["front'door", "sound", "person"],
                        ["backdoor", "silent", "story'time"],                        
                    ],
                    "text": [
                        "There was a knock at the door, then silence.",
                        "There was a knock at the back'door, then silence. Storytime.",                        
                    ],
                    "embedding": [
                        [0.0001, 0.0002, 0.0003, 0.0004],
                        [0.0005, 0.0006, 0.0007, 0.0008],
                    ],
                },
                "column_type_map": {
                    "_id": FBTypes.ID,
                    "text": FBTypes.STRING,
                    "attributes": FBTypes.STRINGSET,
                    "embedding": FBTypes.VECTOR,
                },
                "columns": ["_id", "attributes", "text", "embedding"],
                "records": [
                    "(identifier('table00'),['front''door','sound','person'],'There was a knock at the door, then silence.',[0.0001, 0.0002, 0.0003, 0.0004])",
                    "(identifier('table00'),['backdoor','silent','story''time'],'There was a knock at the back''door, then silence. Storytime.',[0.0005, 0.0006, 0.0007, 0.0008])",                    
                ]
            },
            {
                "name": "test timestamp",
                "table": "table00",
                "data_dict": {
                    "text": ["There was a knock at the door, then silence."],
                    "time": ["2022-01-01"],
                },
                "column_type_map": {
                    "_id": FBTypes.ID,
                    "text": FBTypes.STRING,
                    "time": FBTypes.TIMESTAMP,
                },
                "columns": ["_id", "text", "time"],
                "records": ["(identifier('table00'),'There was a knock at the door, then silence.','2022-01-01T00:00:00.000000+00:00')"]
            },
            {
                "name": "test multiple records with double quote",
                "table": "table00",
                "data_dict": {
                    "attributes": [
                        ['front"door', "sound", "person"],
                        ["backdoor", "silent", 'story"time'],                        
                    ],
                    "text": [
                        "There was a knock at the door, then silence.",
                        'There"s was a knock at the backdoor, then silence. Storytime.',                        
                    ],
                    "embedding": [
                        [0.0001, 0.0002, 0.0003, 0.0004],
                        [0.0005, 0.0006, 0.0007, 0.0008],
                    ],
                },
                "column_type_map": {
                    "_id": FBTypes.ID,
                    "text": FBTypes.STRING,
                    "attributes": FBTypes.STRINGSET,
                    "embedding": FBTypes.VECTOR,
                },
                "columns": ["_id", "attributes", "text", "embedding"],
                "records": [
                    '(identifier(\'table00\'),[\'front"door\',\'sound\',\'person\'],\'There was a knock at the door, then silence.\',[0.0001, 0.0002, 0.0003, 0.0004])',
                    '(identifier(\'table00\'),[\'backdoor\',\'silent\',\'story"time\'],\'There"s was a knock at the backdoor, then silence. Storytime.\',[0.0005, 0.0006, 0.0007, 0.0008])',                    
                ]
            },
        ]

        for case in cases:
            columns, records = process_data_dict_for_insert(case['data_dict'], case['column_type_map'], case['table'])
            self.assertEqual(case['columns'], columns, f"\n\nFAILURE: test named {case['name']} failed.")
            self.assertListEqual(case['records'], records, f"\n\nFAILURE: test named {case['name']} failed.")


if __name__ == '__main__':
    unittest.main()
import os
import sys
import unittest
from datetime import datetime, timezone

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.append(project_root)

from SlothAI.lib.schemar import FBTypes, Schemar, InvalidData, UnhandledDataType, string_to_datetime, datetime_to_string

class TestSchemar(unittest.TestCase):

    def test_set_data(self):
        """
        data must be set to a dict and will raise an exception otherwise.
        testing that here.
        """
        cases = [
            {
                "target": {"some": "good data"},
            },
            {
                "target": None,
                "exception_type": TypeError,
                "exception_str": "data must be set to dict"
            },
            {
                "target": 10,
                "exception_type": TypeError,
                "exception_str": "data must be set to dict"
            },
            {
                "target": "string",
                "exception_type": TypeError,
                "exception_str": "data must be set to dict"
            }
        ]

        for case in cases:
            schemar = Schemar()
            if not case.get('exception_type', None):
                schemar.data = case['target']
            else:
                with self.assertRaises(case['exception_type']) as cm:
                    schemar.data = case['target']
                self.assertEqual(str(cm.exception), str(case['exception_str']))

    def test_infer_schema(self):
        cases = [
            {
                "input": {
                    "str_attr": ["this is some test", "this is some text"],
                    "ts_attr": ["2022-02-02T02:02:02Z", "2022-02-02T02:02:02Z"],
                    "str_list_attr": [["list of test", "list of text"], ["list of text", "list of text"]],
                    "int_attr": [1, 2],
                    "int_list_attr": [[1, 2], [1, 2]],
                    "float_attr": [1.253, 1.256],
                    "bool_attr": [True, False],
                    "vect_attr": [[0.1565, 0.45654], [0.5465, 0.05654]],
                    "str_list_attr_empty": [[], ["some", "data"]],
                    "int_list_attr_empty": [[], [0, 1]],
                    "vec_list_attr_empty": [[], [0.5456, 1.5456, 5.456465, 0.04564]]
                },
                "output": {
                    "str_attr": FBTypes.STRING,
                    "ts_attr": FBTypes.TIMESTAMP + " timeunit 'ms'",
                    "str_list_attr": FBTypes.STRINGSET,
                    "int_attr": FBTypes.INT,
                    "int_list_attr": FBTypes.IDSET,
                    "float_attr": FBTypes.DECIMAL,
                    "bool_attr": FBTypes.BOOL,
                    "vect_attr": FBTypes.VECTOR + "(2)",
                    "str_list_attr_empty": FBTypes.STRINGSET,
                    "int_list_attr_empty": FBTypes.IDSET,
                    "vec_list_attr_empty": FBTypes.VECTOR + "(4)"
                }
            },
            {
                "input": {
                    "str": "str"
                },
                "exception_type": InvalidData,
                "exception_str": "value for all data keys must be a non-empty list"
            },
            {
                "input": {
                    "str": None
                },
                "exception_type": InvalidData,
                "exception_str": "value for all data keys must be a non-empty list"
            },
            {
                "input": {
                    "str": []
                },
                "exception_type": InvalidData,
                "exception_str": "value for all data keys must be a non-empty list"
            },
            {
                "input": {
                    "str": [[]]
                },
                "exception_type": InvalidData,
                "exception_str": "must have at least one non-empty list in value of lists"
            },
            {
                "input": {
                    "str": [{}]
                },
                "exception_type": UnhandledDataType,
                "exception_str": ""
            },
            {
                "input": {
                    "str": [set()]
                },
                "exception_type": UnhandledDataType,
                "exception_str": ""
            },
            {
                "input": {
                    "str": [None]
                },
                "exception_type": UnhandledDataType,
                "exception_str": ""
            },
            {
                "input": {
                    "str": [[{}]]
                },
                "exception_type": UnhandledDataType,
                "exception_str": ""
            }
        ]

        schemar = Schemar()
        for case in cases:
            if not case.get('exception_type', None):
                schemar.data = case['input']
                self.assertDictEqual(schemar.infer_schema(), case['output'])
            else:
                with self.assertRaises(case['exception_type']) as cm:
                    schemar.data = case['input']
                    schemar.infer_schema()
                self.assertEqual(str(cm.exception), str(case['exception_str']))

    def test_string_to_datetime(self):
        """
        data must be set to a dict and will raise an exception otherwise.
        testing that here.
        """
        cases = [
            {
                "string": "2022",
                "datetime": datetime(2022, 1, 1, 0, 0, 0)
            },
            {
                "string": "2022-02",
                "datetime": datetime(2022, 2, 1, 0, 0, 0)
            },
            {
                "string": "2022-02-02",
                "datetime": datetime(2022, 2, 2, 0, 0, 0)
            },
            {
                "string": "2022-02-02 02",
                "datetime": datetime(2022, 2, 2, 2, 0, 0)
            },
            {
                "string": "2022-02-02T02",
                "datetime": datetime(2022, 2, 2, 2, 0, 0)
            },
            {
                "string": "2022-02-02 02:02",
                "datetime": datetime(2022, 2, 2, 2, 2, 0)
            },
            {
                "string": "2022-02-02T02:02",
                "datetime": datetime(2022, 2, 2, 2, 2, 0)
            },
            {
                "string": "2022-02-02 02:02:02",
                "datetime": datetime(2022, 2, 2, 2, 2, 2)
            },
            {
                "string": "2022-02-02T02:02:02",
                "datetime": datetime(2022, 2, 2, 2, 2, 2)
            },
            {
                "string": "2022-02-02 02:02:02.123456",
                "datetime": datetime(2022, 2, 2, 2, 2, 2, 123456)
            },
            {
                "string": "2022-02-02T02:02:02.123456",
                "datetime": datetime(2022, 2, 2, 2, 2, 2, 123456)
            },
            {
                "string": "2022-02-02T02Z",
                "datetime": datetime(2022, 2, 2, 2, 0, 0, tzinfo=timezone.utc)
            },
            {
                "string": "2022-02-02 02:02Z",
                "datetime": datetime(2022, 2, 2, 2, 2, 0, tzinfo=timezone.utc)
            },
            {
                "string": "2022-02-02T02:02Z",
                "datetime": datetime(2022, 2, 2, 2, 2, 0, tzinfo=timezone.utc)
            },
            {
                "string": "2022-02-02 02:02:02Z",
                "datetime": datetime(2022, 2, 2, 2, 2, 2, tzinfo=timezone.utc)
            },
            {
                "string": "2022-02-02T02:02:02Z",
                "datetime": datetime(2022, 2, 2, 2, 2, 2, tzinfo=timezone.utc)
            },
            {
                "string": "2022-02-02 02:02:02.123456Z",
                "datetime": datetime(2022, 2, 2, 2, 2, 2, 123456, tzinfo=timezone.utc)
            },
            {
                "string": "2022-02-02T02:02:02.123456Z",
                "datetime": datetime(2022, 2, 2, 2, 2, 2, 123456, tzinfo=timezone.utc)
            },
            {
                "string": "03/15/2023",
                "datetime": datetime(2023, 3, 15, 0, 0, 0)
            },
            {
                "string": "03/15/2023 03:30:45 AM",
                "datetime": datetime(2023, 3, 15, 3, 30, 45)
            },
            {
                "string": "03/15/2023 03:30:45 PM UTC",
                "datetime": datetime(2023, 3, 15, 15, 30, 45)
            },
            {
                "string": "September 22 2023",
                "datetime": datetime(2023, 9, 22, 0, 0, 0)
            },
            {
                "string": "September 22, 2023",
                "datetime": datetime(2023, 9, 22, 0, 0, 0)
            }
        ]

        for case in cases:
            dt = string_to_datetime(case['string'])
            self.assertEqual(case['datetime'], dt)

    def test_datetime_to_string(self):
        """
        data must be set to a dict and will raise an exception otherwise.
        testing that here.
        """
        cases = [
            {
                "datetime": datetime(2022, 2, 2),
                "string": "2022-02-02T00:00:00.000000+00:00"
            },
            {
                "datetime": datetime(2022, 2, 2, 2, 2, 2, 123456, tzinfo=timezone.utc),
                "string": "2022-02-02T02:02:02.123456+00:00"

            }
        ]

        for case in cases:
            string = datetime_to_string(case['datetime'])
            self.assertEqual(case['string'], string)


if __name__ == '__main__':
    unittest.main()
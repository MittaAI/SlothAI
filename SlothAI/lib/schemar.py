import re
from datetime import datetime
from typing import Dict

class FBTypes():
    ID = "id"
    IDSET = "idset"
    IDSETQ = "idsetq"
    STRING = "string"
    STRINGSET = "stringset"
    STRINGSETQ = "stringsetq"
    INT = "int"
    DECIMAL = "decimal(4)"
    TIMESTAMP = "timestamp"
    BOOL = "bool"
    VARCHAR = "varchar"
    VECTOR = "vector"


class SchemarError(Exception):
    """
    Base class for schema errors
    """

class InvalidData(SchemarError):
    """
    Raised when data in the data attribute is invalid
    """

class UnhandledDataType(SchemarError):
    """
    Raised when data in the data attribute type is not handled
    """


class Schemar:
    
    def __init__(self, data=dict()):
        self.data = data

    def _get_data(self):
        return self.__data

    def _set_data(self, value):
        if not isinstance(value, dict):
            raise TypeError("data must be set to dict")
        self.__data = value

    data = property(_get_data, _set_data)

    def infer_schema(self):
        if not self.data:
            return None
        
        schema = {}
        for key, values in self.data.items():
            if not isinstance(values, list) or (isinstance(values, list) and len(values) == 0):
                raise InvalidData(f"value for all data keys must be a non-empty list")

            # list of bools
            if isinstance(values[0], bool):
                schema[key] = FBTypes.BOOL

            # list of ints
            elif isinstance(values[0], int):
                if any(value < 0 for value in values):
                    schema[key] = FBTypes.INT
                else:
                    schema[key] = FBTypes.INT

            # list of floats
            elif isinstance(values[0], float):
                schema[key] = FBTypes.DECIMAL

            # list of strs
            elif isinstance(values[0], str):
                ts = string_to_datetime(values[0])
                if ts:
                    schema[key] = FBTypes.TIMESTAMP +  " timeunit 'ms'"
                else:
                    schema[key] = FBTypes.STRING
                
            # list of lists
            elif isinstance(values[0], list):
                for value in values:
                    if len(value) > 0:
                        if isinstance(value[0], int): 
                            schema[key] = FBTypes.IDSET
                            break
                        elif isinstance(value[0], str):
                            schema[key] = FBTypes.STRINGSET
                            break
                        elif isinstance(value[0], float):
                            schema[key] = FBTypes.VECTOR + f"({len(value)})"
                            break
                        else:
                            raise UnhandledDataType()
                if not schema.get(key, None):
                    raise InvalidData("must have at least one non-empty list in value of lists")

            else:
                raise UnhandledDataType("The data you are sending to FeatureBase isn't able to be auto-detected. Ensure you are only sending in arrays or arrays of arrays that match length.")
                

        return schema

    def infer_create_table_schema(self):
        schema = self.infer_schema()
        if "_id" not in schema.keys():
            schema['_id'] = "id"
        return "(" + ", ".join([f"{fld} {typ}" for fld, typ in schema.items()]) + ")"



def string_to_datetime(string):
    
    # input must be a string
    if not isinstance(string, str):
        return None

    formats = [
        "%Y",
        "%Y-%m",
        "%Y-%m-%d",
        "%Y-%m-%d %H",
        "%Y-%m-%dT%H",
        "%Y-%m-%d %H%z",
        "%Y-%m-%dT%H%z",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M%z",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%m/%d/%Y",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M:%S %p %Z",
        "%B %d %Y",
        "%B %d, %Y"
    ]

    for format in formats:
        try:
            date_object = datetime.strptime(string, format)
            return date_object
        except Exception:
            continue

    return None

def datetime_to_string(dt):

    # input must be datetime
    if not isinstance(dt, datetime):
        return None
    
    try:
        string = dt.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        if not re.search(r"[-+]?\d{2}:\d{2}$", string): # doesn't end in +00:00 or similar
            if re.search(r"[-+][0-9]{4}$", string): # end in +0000 or similar
                string = string[:-2] + ":" + string[-2:]
            else:
                string += "+00:00"

        return string
    except Exception as e:
        print(e)
        return None

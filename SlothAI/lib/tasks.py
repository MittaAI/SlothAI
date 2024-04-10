import os
import json
import random
from SlothAI.lib.schemar import Schemar
from datetime import datetime, timedelta

from ping3 import ping
from SlothAI.lib.util import check_webserver_connection

from typing import List, Tuple, Dict

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

from SlothAI.lib.gcloud import box_start
from SlothAI.web.models import Box
from SlothAI.lib.util import random_string, handle_quotes
from SlothAI.lib.schemar import string_to_datetime, datetime_to_string, FBTypes

from flask import current_app as app

from enum import Enum

class TaskState(Enum):
	RUNNING = 'running'
	COMPLETED = 'completed'
	FAILED = 'failed'
	CANCELED = 'canceled'

	@classmethod
	def state_from_string(self, state_as_string):
		if state_as_string == "running":
			return self.RUNNING
		elif state_as_string == "complete":
			return self.COMPLETED
		elif state_as_string == "failed":
			return self.FAILED
		else:
			raise Exception("invalid state_as_string")

class Task:
	
	def __init__(self, id: str, user_id: str, pipe_id: str, nodes: List[str], document: dict, created_at: datetime, retries: int, error: str, state: TaskState, split_status: int, jump_status: int):
		self.id = id
		self.user_id = user_id
		self.pipe_id = pipe_id
		self.nodes = nodes
		self.document = document
		self._created_at = created_at
		self.retries = retries
		self.error = error
		self.state = state
		self.split_status = split_status
		self.jump_status = jump_status
	@property
	def created_at(self):
		return self._created_at

	def to_dict(self) -> dict:
		"""
		Convert a Task object to a dictionary.
		"""
		return {
			"id": self.id,
			"user_id": self.user_id,
			"pipe_id": self.pipe_id,
			"nodes": self.nodes,
			"document": self.document,
			"created_at": self.created_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
			"retries": self.retries,
			"error": self.error,
			"state": self.state.value,
			"split_status": self.split_status,
			"jump_status": self.jump_status
		}
		
	@classmethod
	def from_dict(cls, task_dict: dict) -> 'Task':
		"""
		Create a Task object from a dictionary.
		"""
		return cls(
			id=task_dict["id"],
			user_id=task_dict["user_id"],
			pipe_id=task_dict["pipe_id"],
			nodes=task_dict["nodes"],
			document=task_dict["document"],
			created_at= datetime.strptime(task_dict["created_at"], '%Y-%m-%dT%H:%M:%SZ'),
			retries=task_dict['retries'],
			error=task_dict['error'],
			state=TaskState.state_from_string(task_dict['state']),
			split_status=task_dict['split_status'],
			jump_status=task_dict['jump_status']
		)

	def to_json(self) -> str:
		"""
		Convert a Task object to a JSON string.
		"""
		task_dict = self.to_dict()
		return json.dumps(task_dict, indent=4)

	@classmethod
	def from_json(cls, json_str: str) -> 'Task':
		"""
		Create a Task object from a JSON string.
		"""
		task_dict = json.loads(json_str)
		return cls.from_dict(task_dict)

	def next_node(self):
		if len(self.nodes) == 0:
			return None
		return self.nodes[0]

	def jump_node(self, jump_id=None):
		"""
		Modify the task's node sequence to jump to the specified node.
		This leaves the current node intact but removes all nodes between
		the current node and the target node.

		:param jump_id: The ID of the node to jump to.
		"""
		if jump_id not in self.nodes:
			raise ValueError(f"Node '{jump_id}'' not found in task nodes.")

		current_index = 0  # Assuming the first node is always the current node
		jump_index = self.nodes.index(jump_id)

		if jump_index <= current_index:
			raise ValueError("Cannot jump backwards or to the current node.")

		# Remove nodes between the current node and the jump node
		# This keeps the current node and the jump node in the list
		self.nodes = [self.nodes[current_index]] + self.nodes[jump_index:]
		return True

	def halt_node(self):
		"""
		Modify the task's node sequence to halt after the current node.
		This removes all nodes subsequent to the current node, effectively stopping the task's progress after the current node is processed.
		"""
		if len(self.nodes) == 0:
			return None

		current_index = 0  # Assuming the first node is always the current node

		# Keep only the current node in the list, removing all subsequent nodes
		self.nodes = self.nodes[:current_index + 1]

		return True

	def remove_node(self):
		if len(self.nodes) > 1:
			node = self.nodes[0]
			self.nodes = self.nodes[1:]
			return node
		else:
			node = self.nodes[0]
			self.nodes = []
			return node

	def delete_task(self):
		self.delete()
		return True


def delete_task(name):
	# don't forget to add a delete task button in the UI!
	pass


def get_task_schema(data: Dict[str, any]) -> Tuple[Dict[str, str], str]:
	'''
	Populate with schema dict
	'''

	if not data:
		return dict(), None

	try:
		schema = Schemar(data=data).infer_schema()
	except Exception as ex:
		return dict(), f"in get_task_schema: {ex}"

	return schema, None


def get_values_by_json_paths(json_paths, document):
	results = {}
	
	for json_path in json_paths:
		path_components = json_path.split('.')
		current_location = document
		
		for key in path_components:
			if key in current_location:
				current_location = current_location[key]
			else:
				# If a key is not found, skip this path
				break
		else:
			# This block executes if the loop completed without a 'break'
			results[path_components[-1]] = current_location
	
	return results


def auto_field_data(document):
	# This will store the maximum length found
	max_length = 0

	# This will store the key-value pairs with the max length
	results = {}

	# Iterate over the dictionary to find the max length and collect the key-value pairs
	for key, value in document.items():
		if isinstance(value, list):  # Ensure the value is a list
			length = len(value)
			if length > max_length:
				max_length = length
				results = {key: value}  # Start a new dict with this key-value pair
			elif length == max_length:
				results[key] = value  # Add the key-value pair to the existing dict

	# Now results contains all key-value pairs with the longest list lengths
	return results


def process_data_dict_for_insert(data, column_type_map, table):
	"""
	Process data from a dictionary for insertion into a database table.

	This function takes data in the form of a dictionary, a mapping of column types,
	and the target table name. It generates records suitable for insertion into
	the specified table and returns the list of columns and records.

	Parameters:
	- data (dict): A dictionary containing data to be inserted into the table.
	- column_type_map (dict): A dictionary mapping column names to their data types.
	- table (str): The name of the target database table.

	Returns:
	- columns (list): A list of column names including '_id'.
	- records (list): A list of records, each formatted as a tuple for insertion.

	Example:
	data = {
		'text': ['Record 1', 'Record 2'],
		'value': [42, 57]
	}
	column_type_map = {
		'_id': 'string',
		'text': 'string',
		'value': 'int'
	}
	table = 'my_table'
	columns, records = process_data_dict_for_insert(data, column_type_map, table)
	# columns = ['_id', 'text', 'value']
	# records = ["('abc123','Record 1',42)", "('def456','Record 2',57)"]
	"""
	
	records = []
	columns = list(data.keys())

	if "_id" not in columns:
		columns = ["_id"] + columns

	data_lengths = []
	for column in data.keys():
		data_lengths.append(len(data[column]))

	if not all_equal(data_lengths):
		raise NonRetriableError("data dict for insert: length of values must be equal for all keys in data.")

	# build insert tuple for each record
	for i, _ in enumerate(data[list(data.keys())[0]]):
		record = ""
		for column in columns:
			col_type = column_type_map[column]
			if column == '_id':
				if column not in list(data.keys()):
					record += f"'{random_string(6)}'," if col_type == "string" else f"identifier('{table}'),"
					continue
			value = data[column][i]
			if FBTypes.TIMESTAMP in col_type:
				value = f"'{datetime_to_string(string_to_datetime(value))}'"
			if col_type == FBTypes.STRING:
				value = f"'{handle_quotes(value)}'"
			if col_type == FBTypes.STRINGSET:
				value = "['" + "','".join(handle_quotes(value)) + "']"	
			record += f"{value},"
		records.append(f"({record[:-1]})")

	return columns, records


from itertools import groupby
def all_equal(iterable):
	g = groupby(iterable)
	return next(g, True) and not next(g, False)


def validate_dict_structure(keys_list, input_dict):
	for key in keys_list:
		keys = key.get('name').split('.')
		current_dict = input_dict

		for k in keys:
			if k not in current_dict:
				return key
			current_dict = current_dict[k]

	return None


def transform_data(output_keys, data):
	out = {}

	if len(output_keys) == 1 and output_keys[0] == 'data':
		# Special case: If the output key is 'data', wrap the data in a single key
		out['data'] = data
	else:
		for key_name in output_keys:
			if key_name in data:
				out[key_name] = data[key_name]
			else:
				raise KeyError(f"Key not found: {key_name}")

	return out

"""
# check boxes and start if needed
def box_required(box_type=None):
	boxes = Box.get_boxes()  # Retrieve all boxes

	if not boxes:
		return False, None  # Indicates no box is available

	active_t4s = []
	halted_t4s = []

	for box in boxes:
		status = box.get('status')
		box_ip = box.get('ip_address')
		box_id = box.get('box_id')

		# Check if the called type matches the box_type
		if box_type and box_id.split("-")[0] != box_type:
			continue

		# Check for active boxes
		if status == "RUNNING":
			if box_ip and ping(box_ip, timeout=2.0) and check_webserver_connection(box_ip, 9898):
				active_t4s.append(box)
			else:
				halted_t4s.append(box)

		# Add boxes in START, PROVISIONING, STAGING to halted_t4s
		elif status in ["START", "PROVISIONING", "STAGING", "TERMINATED"]:
			halted_t4s.append(box)

	# Return a random active box if available
	if active_t4s:
		return False, random.choice(active_t4s)

	# No active boxes, attempt to start a halted box
	if halted_t4s:
		alternate_box = random.choice(halted_t4s)
		if alternate_box.get('status') != "START":
			print("Starting box", alternate_box.get('box_id'))
			box_start(alternate_box.get('box_id'), alternate_box.get('zone'))
			Box.start_box(alternate_box.get('box_id'), "START")
		return True, alternate_box

	# No boxes available to start
	return False, None
"""

# AI improved check boxes
def box_required(box_type=None):
    boxes = Box.get_boxes()  # Retrieve all boxes
    if not boxes:
        return False, None  # Indicates no box is available

    active_gpus = []
    halted_gpus = []
    starting_gpus = []

    for box in boxes:
        status = box.get('status')
        box_ip = box.get('ip_address')
        box_id = box.get('box_id')

        # Check if the called type matches the box_type
        if box_type and box_id.split("-")[0] != box_type:
            continue

        # Check for active boxes
        if status == "RUNNING":
            if box_ip and ping(box_ip, timeout=2.0) and check_webserver_connection(box_ip, 9898):
                active_gpus.append(box)
            else:
                starting_gpus.append(box)  # Consider boxes that fail ping as starting

        # Add boxes in START, PROVISIONING, STAGING to starting_gpus
        elif status in ["START", "PROVISIONING", "STAGING"]:
            starting_gpus.append(box)

        # Add boxes in TERMINATED to halted_gpus
        elif status == "TERMINATED":
            halted_gpus.append(box)

    # Return a random active box if available
    if active_gpus:
        return False, random.choice(active_gpus)

    # Check if a box is already being started or a running box is potentially starting
    if starting_gpus:
        return True, random.choice(starting_gpus)

    # No active or starting boxes, attempt to start a halted box
    if halted_gpus:
        alternate_box = random.choice(halted_gpus)
        app.logger.info(f"Starting box: {alternate_box.get('box_id')}")
        box_start(alternate_box.get('box_id'), alternate_box.get('zone'))
        Box.start_box(alternate_box.get('box_id'), "START")
        return True, alternate_box

    # No boxes available to start
    return False, None
    

class RetriableError(Exception):
	def __init__(self, message):
		super().__init__(message)

class NonRetriableError(Exception):
	def __init__(self, message):
		super().__init__(message)

class ResourceNotFoundError(NonRetriableError):
	def __init__(self, message):
		super().__init__(message)

class PipelineNotFoundError(ResourceNotFoundError):
	def __init__(self, pipeline_id):
		super().__init__(f"pipeline with id {pipeline_id} not found.")

class UserNotFoundError(ResourceNotFoundError):
	def __init__(self, user_id):
		super().__init__(f"user with id {user_id} not found.")

class TaskNotFoundError(ResourceNotFoundError):
	def __init__(self, task_id):
		super().__init__(f"task with id {task_id} not found.")

class NodeNotFoundError(ResourceNotFoundError):
	def __init__(self, node_id):
		super().__init__(f"node with id {node_id} not found")

class TemplateNotFoundError(ResourceNotFoundError):
	def __init__(self, template_id):
		super().__init__(f"node with id {template_id} not found")

class MissingFieldError(NonRetriableError):
	def __init__(self, message):
		super().__init__(message)

class MissingInputFieldError(MissingFieldError):
	def __init__(self, field, node):
		super.__init__(f"task document is missing required input field {field} for node {node}")

class MissingOutputFieldError(MissingFieldError):
	def __init__(self, field, node):
		super.__init__(f"task document is missing required output field {field} for node {node}")

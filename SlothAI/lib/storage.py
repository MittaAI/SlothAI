from abc import ABC, abstractmethod
from typing import Dict
import datetime

from SlothAI.lib.util import random_string, compress_text, decompress_text

from google.cloud import ndb

class AbstractTaskStore(ABC):
	@abstractmethod
	def create(cls, task_id, user_id, current_node_id, pipe_id, created_at, state, error, retries, split_status):
		pass

	@abstractmethod
	def update(cls, task_id: str, **kwargs: Dict[str, any]):
		pass

	@abstractmethod
	def fetch(cls, **kwargs: Dict[str, any]):
		pass

	@abstractmethod
	def delete_older_than(cls, hours=0, minutes=0, seconds=0):
		pass

	@abstractmethod
	def delete(cls, task_id=None, user_id=None, states=None):
		pass

# Create a context manager decorator for NDBTaskStore
def ndb_context_manager(func):
    def wrapper(*args, **kwargs):
        with ndb.Client().context():
            result = func(*args, **kwargs)
        return result  # Return the result outside the context
    return wrapper

class NDBTaskStore(ndb.Model):
    task_id = ndb.StringProperty()
    user_id = ndb.StringProperty()
    current_node_id = ndb.StringProperty()
    pipe_id = ndb.StringProperty()
    created_at = ndb.DateTimeProperty()
    state = ndb.StringProperty()
    error = ndb.StringProperty()
    retries = ndb.IntegerProperty()
    split_status = ndb.IntegerProperty()

    @classmethod
    def _get_kind(cls):
         return 'Task'

    @classmethod
    @ndb_context_manager
    def create(cls, task_id, user_id, current_node_id, pipe_id, created_at, state, error, retries, split_status):
        task = cls(
            task_id=task_id,
            user_id=user_id,
            current_node_id=current_node_id,
            pipe_id=pipe_id,
            created_at=created_at,
            state=state.value,
            error=error,
            retries=retries,
            split_status = split_status,
        )
        task.put()
        return task.to_dict()

    @classmethod
    @ndb_context_manager
    def delete_older_than(cls, hours=0, minutes=0, seconds=0):
        threshold = datetime.datetime.utcnow() - \
            datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)
        entities = cls.query(cls.created_at < threshold).fetch()
        if entities:
            for entity in entities:
                entity.key.delete()

    @classmethod
    @ndb_context_manager
    def fetch(cls, **kwargs):
        query_conditions = []

        if 'task_id' in kwargs:
            query_conditions.append(cls.task_id == kwargs['task_id'])
        if 'user_id' in kwargs:
            query_conditions.append(cls.user_id == kwargs['user_id'])
        if 'pipe_id' in kwargs:
            query_conditions.append(cls.pipe_id == kwargs['pipe_id'])
        if 'current_node_id' in kwargs:
            query_conditions.append(cls.current_node_id == kwargs['current_node_id'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).fetch()
        else:
            entities = []

        return [e.to_dict() for e in entities]

    @classmethod
    @ndb_context_manager
    def update(cls, task_id, **kwargs):
        task = cls.query(cls.task_id == task_id).get()
        if not task:
            raise Exception("task_id not found")

        if 'state' in kwargs:
            task.state = kwargs['state'].value
        if 'error' in kwargs:
            task.error = kwargs['error']
        if 'current_node_id' in kwargs:
            task.current_node_id = kwargs['current_node_id']
        if 'retries' in kwargs:
            task.retries = kwargs['retries']
        if 'split_status' in kwargs:
            task.split_status = kwargs['split_status']

        task.put()

        return task.to_dict()

    @classmethod
    @ndb_context_manager
    def delete(cls, task_id=None, user_id=None, states=None):
        query_conditions = []

        if user_id:
            query_conditions.append(cls.user_id == user_id)

        if task_id:
            # If task_id is provided, we use it in the query conditions.
            query_conditions.append(cls.task_id == task_id)
        elif states:
            # If states are provided but no task_id, then we prepare a compound 'OR' condition for all the states.
            # This is assuming that the combination of user_id and each of the states is desired.
            state_conditions = [cls.state == state for state in states]
            if user_id:
                # If user_id is also provided, it should be 'AND'ed with the 'OR' condition of states.
                query_conditions.append(ndb.AND(*state_conditions))
            else:
                # If user_id is not provided, just use the 'OR' condition of states.
                query_conditions.extend(state_conditions)
        else:
            # If neither task_id nor states are provided, return False.
            return False

        if query_conditions:
            # Use 'AND' to combine all conditions
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).fetch()
        else:
            entities = []

        # TODO: use unit of work pattern to make this "atomic"
        try:
            for entity in entities:
                entity.key.delete()
        except Exception:
             return False

        return True
    
class AbstractTemplateStore(ABC):
	@abstractmethod
	def create(cls, name, user_id, text, input_fields=[], output_fields=[], extras=[], processor="jinja2"):
		pass

	@abstractmethod
	def update(cls, template_id, user_id, name, text, input_fields=[], output_fields=[], extras=[], processor="jinja2"):
		pass

	@abstractmethod
	def fetch(cls, **kwargs: Dict[str, any]):
		pass

	@abstractmethod
	def get(cls, **kwargs: Dict[str, any]):
		pass

	@abstractmethod
	def delete(cls, **kwargs: Dict[str, any]):
		pass


_sentinel = object()

class NDBTemplateStore(ndb.Model):
    template_id = ndb.StringProperty()
    name = ndb.StringProperty()
    uid = ndb.StringProperty()
    text = ndb.StringProperty()
    input_fields = ndb.JsonProperty()
    output_fields = ndb.JsonProperty()
    extras = ndb.JsonProperty()
    processor = ndb.StringProperty()
    created = ndb.DateTimeProperty()

    @classmethod
    def _get_kind(cls):
         return 'Template'

    @classmethod
    @ndb_context_manager
    def create(cls, name, user_id, text, input_fields=[], output_fields=[], extras=[], processor="jinja2"):
        current_utc_time = datetime.datetime.utcnow()
        existing_template = cls.query(cls.name == name, cls.uid == user_id).get()

        if not existing_template:
            template_id = random_string(13)
            template = cls(
                template_id=template_id,
                name=name,
                uid=user_id,
                text=compress_text(text),
                input_fields=input_fields,
                output_fields=output_fields,
                extras=extras,
                processor=processor,
                created=current_utc_time,
            )
            template.put()
            return template.to_dict()
        else:
            return existing_template.to_dict()

    @classmethod
    @ndb_context_manager
    def update(cls, template_id, user_id=_sentinel, name=_sentinel, text=_sentinel, input_fields=_sentinel, output_fields=_sentinel, extras=_sentinel, processor=_sentinel):
        template = cls.query(cls.template_id == template_id, cls.uid == user_id).get()
        if not template:
            print("didn't find template")
            return None

        # Update fields only if the new values are not None
        if name is not _sentinel:
            template.name = name
        if user_id is not _sentinel:
             template.uid = user_id
        if text is not _sentinel:
            template.text = compress_text(text)  # Assuming you want to always compress
        if input_fields is not _sentinel:
            template.input_fields = input_fields
        if output_fields is not _sentinel:
            template.output_fields = output_fields
        if extras is not _sentinel:
            template.extras = extras
        if processor is not _sentinel:
            template.processor = processor

        template.put()

        return template.to_dict()

    @classmethod
    @ndb_context_manager
    def fetch(cls, **kwargs: Dict[str, any]):
        query_conditions = []

        if 'processor' in kwargs and 'user_id' in kwargs:
            query_conditions.append(cls.processor == kwargs['processor'], cls.uid == kwargs['user_id'])
        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'user_id' in kwargs:
            query_conditions.append(cls.uid == kwargs['user_id'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).fetch()
        else:
            entities = None

        templates = []
        for entity in entities:
            template = entity.to_dict()
            template['text'] = decompress_text(entity.text)  # Decompress the stored text
            templates.append(template)

        return templates

    @classmethod
    @ndb_context_manager
    def get(cls, **kwargs: Dict[str, any]):
        query_conditions = []

        if 'processor' in kwargs and 'user_id' in kwargs:
            query_conditions.append(cls.processor == kwargs['processor'], cls.uid == kwargs['user_id'])
        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'user_id' in kwargs:
            query_conditions.append(cls.uid == kwargs['user_id'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            template = cls.query(query).get()

        if template:
            template_dict = template.to_dict()
            template_dict['text'] = decompress_text(template.text)  # Decompress the stored text
            return template_dict
        else:
            return None

    @classmethod
    @ndb_context_manager
    def delete(cls, **kwargs: Dict[str, any]):
        query_conditions = []

        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'user_id' in kwargs:
            query_conditions.append(cls.uid == kwargs['user_id'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entity = cls.query(query).get()

        if entity:
            entity.key.delete()
            return True
        else:
            return False
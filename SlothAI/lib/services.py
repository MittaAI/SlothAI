
from SlothAI.lib.tasks import Task, TaskState, TaskNotFoundError, NonRetriableError
from SlothAI.lib.storage import AbstractTaskStore, AbstractTemplateStore
from SlothAI.lib.queue import AbstractTaskQueue
from SlothAI.lib.template import Template
from typing import Dict, List

class InvalidStateForDelete(NonRetriableError):
    def __init__(self, state):
        super().__init__(f"Task state must be complete, canceled, or failed to delete. Got state {state}.")

class InvalidStateForCancel(NonRetriableError):
    def __init__(self, state):
        super().__init__(f"Task state must be running to cancel delete. Got state {state}.")

class InvalidStateForProcess(NonRetriableError):
    def __init__(self, state):
        super().__init__(f"Task state must be running to be processed. Got state {state}.")

class TaskService:

    def __init__(self, task_store: AbstractTaskStore, task_queue: AbstractTaskQueue):
        self.task_store = task_store
        self.task_queue = task_queue

    def create_task(self, task: Task):
        self.task_store.create(
            task_id=task.id,
            user_id=task.user_id,
            current_node_id=task.next_node(),
            pipe_id = task.pipe_id,
            created_at=task.created_at,
            state=task.state,
            error=task.error,
            retries=task.retries,
            split_status=task.split_status
        )
        self.queue_task(task)

    def update_task(self, task_id, **kwargs):
        self.task_store.update(task_id, **kwargs)

    def fetch_tasks(self, **kwargs) -> Dict[str, any]:
        # TODO: fetch task should probably return a Task object /  model, not a
        # dict
        return self.task_store.fetch(**kwargs)

    def delete_older_than(self, hours=0, minutes=0, seconds=0):
        self.task_store.delete_older_than(hours=hours, minutes=minutes, seconds=seconds)

    def drop_task(self, task: Task):
        self.task_store.update(
                    task_id=task.id,
                    error=task.error,
                    retries=task.retries,
                    current_node_id=task.next_node(),
                    state=TaskState.FAILED
                )

    def queue_task(self, task: Task):
        self.task_queue.queue(task)
        self.update_task(
			task_id=task.id,
			state=task.state,
			retries=task.retries,
			error=task.error,
			current_node_id=task.next_node(),
			split_status=task.split_status,
		)

    def retry_task(self, task: Task):
        if self._is_retriable(task):
            task.retries += 1
            self.queue_task(task)
        else:
            self.drop_task(task)

    def _is_retriable(self, task: Task):
        if task.retries >= 5:
            return False
        return True
    
    def is_valid_state_for_delete(self, state: str):
        '''
        at this point, we will say you cannot delete a task until it's in a
        non-running state
        '''
        if state == TaskState.CANCELED.value:
            return True
        if state == TaskState.FAILED.value:
            return True
        if state == TaskState.COMPLETED.value:
            return True
        return False
    
    def delete_tasks_by_states(self, user_id: str = "", states: List[str]= []):
        for state in states:
            if not self.is_valid_state_for_delete(state):
                return False
        if user_id != "":
            return self.task_store.delete(states=states, user_id=user_id)
        
        return self.task_store.delete(states=states)

    def delete_task_by_id(self, task_id):
        return self.task_store.delete(task_id=task_id)
    
    def is_valid_state_for_cancel(self, state: str):
        if state == TaskState.RUNNING.value:
            return True
        return False

    def cancel_task(self, user_id, task_id):
        tasks = self.fetch_tasks(user_id=user_id, task_id=task_id)
        if len(tasks) == 0:
            raise TaskNotFoundError(task_id)
        
        if len(tasks) > 1:
            raise NonRetriableError("Logic error: multiple tasks in the task store with the same id")

        if self.is_valid_state_for_cancel(tasks[0]['state']):
            self.task_store.update(
                task_id=task_id,
                state=TaskState.CANCELED
            )
        else:
            raise InvalidStateForCancel(tasks[0]['state'])
        

    def is_valid_state_for_process(self, state: str):
        if state == TaskState.RUNNING.value:
            return True
        return False


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

class TemplateService:
    
    def __init__(self, template_store: AbstractTemplateStore):
        self.template_store = template_store

    def create_template(self, name, user_id, text, input_fields=[], output_fields=[], extras=[], processor="jinja2"):
        return self.template_store.create(
            name=name,
            user_id=user_id,
            text=text,
            input_fields=input_fields,
            output_fields=output_fields,
            extras=extras,
            processor=processor,
        )

    def update_template(self, template_id, name=None, user_id=None, text=None, input_fields=None, output_fields=None, extras=None, processor=None):
        return self.template_store.update(
            template_id=template_id,
            name=name,
            user_id=user_id,
            text=text,
            input_fields=input_fields,
            output_fields=output_fields,
            extras=extras,
            processor=processor,
        )
    
    def fetch_template(self, **kwargs: Dict[str, any]) -> Dict[str, any]:
        # TODO: fetch task should probably return a Task object /  model, not a
        # dict
        return self.template_store.fetch(**kwargs)
    
    def get_template(self, **kwargs: Dict[str, any]) -> Dict[str, any]:
        return self.template_store.get(**kwargs)
    
    def delete_template(self, **kwargs: Dict[str, any]) -> Dict[str, any]:
        return self.template_store.delete(**kwargs)
    
    def create_template_from_dict(self, template_dict: Dict[str, any]):

        if 'name' not in template_dict:
            raise MissingTemplateKey('name')
        if 'user_id' not in template_dict:
            raise MissingTemplateKey('user_id')
        if 'text' not in template_dict:
            raise MissingTemplateKey('text')

        template = Template.from_dict(template_dict)

        return self.create_template(
            name=template.name,
            user_id=template.user_id,
            text=template.text,
            input_fields=template.input_fields,
            output_fields=template.output_fields,
            extras=template.extras,
            processor=template.processor,
        )
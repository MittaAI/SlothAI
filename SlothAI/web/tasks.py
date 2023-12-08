import json
import traceback

from flask import Blueprint, request
from flask import current_app as app
import flask_login
from flask_login import current_user

from SlothAI.lib.processor import process
from SlothAI.lib.tasks import Task, RetriableError, NonRetriableError, TaskState, TaskNotFoundError
import SlothAI.lib.services as services
# from SlothAI.web.models import Task as TaskModel

tasks = Blueprint('tasks', __name__)

@tasks.route('/tasks/process/<cron_key>', methods=['POST'])
def process_tasks(cron_key):

	try:
		# validate call with a key
		if cron_key != app.config['CRON_KEY']:
			raise NonRetriableError("invalid cron key")

		task_service = app.config['task_service']

		# Parse the task payload sent in the request.
		task = Task.from_json(request.get_data(as_text=True))

		task_stored = task_service.fetch_tasks(task_id=task.id)
		if len(task_stored) == 0:
			raise TaskNotFoundError(task.id)
		
		if len(task_stored) != 1:
			raise Exception("Logic error: multiple tasks with same id")
				
		if task_stored[0]['state'] != TaskState.RUNNING.value:
			raise services.InvalidStateForProcess(task_stored.state.value)

		task = process(task)

		node = task.remove_node()
		if len(task.nodes) > 0:
			task_service.queue_task(task)			
		else:
			task_service.update_task(task_id=task.id, state=TaskState.COMPLETED)

		app.logger.info(f"successfully processed task with id {task.id} on node with id {node} in pipeline with id {task.pipe_id}")

	except RetriableError as e:
		task.error = str(e)
		app.logger.error(f"processing task with id {task.id} on node with id {task.next_node()} in pipeline with id {task.pipe_id}: {str(e)}: retrying task.")
		task_service.retry_task(task)
	except services.InvalidStateForProcess as e:
		# state likely changed during processing a task, don't requeue
		# TODO: this could be drop task but drop_task should accept a final state.
		return "invalid state for processing", 200
	except Exception as e:
		traceback.print_exc()
		task.error = str(e)
		app.logger.error(f"processing task with id {task.id} on node with id {task.next_node()} in pipeline with id {task.pipe_id}: {str(e)}: dropping task.")
		task_service.drop_task(task)
		
	return f"successfully completed node", 200


@tasks.route('/tasks', methods=['DELETE'])
@flask_login.login_required
def delete_tasks():
	'''
	DELETE /tasks?state=running&state=complete
	'''
	task_service = app.config['task_service']
	states = request.args.getlist('state')
	if not states:
		states = [
			TaskState.COMPLETED.value,
			TaskState.CANCELED.value,
			TaskState.FAILED.value
		]
	else:
		for state in states:
			if not task_service.is_valid_state_for_delete(state):
				return f"Invalid state: {state}", 400
	
	ok = task_service.delete_tasks_by_states(user_id=current_user.uid, states=states)
	if not ok:
		return "Issue deleting tasks", 500
		
	return "OK", 200


@tasks.route('/tasks/<task_id>', methods=['DELETE'])
@flask_login.login_required
def delete_task(task_id):
	task_service = app.config['task_service']
	tasks = task_service.fetch_tasks(task_id=task_id)
	if len(tasks) == 0:
		return "Task not found", 404
	
	# user can only delete task they own
	if tasks[0].user_id != current_user.uid:
		return "Task not found", 404
	
	if tasks[0].state == TaskState.RUNNING.value:
		return "Cannot delete a task in running state. Cancel the task first, then try again", 403

	ok = task_service.delete_task_by_id(task_id=task_id)
	if not ok:
		return "Issue deleting task", 500
	
	return f"OK", 200

@tasks.route('/tasks/<task_id>/cancel', methods=['POST'])
@flask_login.login_required
def cancel_task(task_id):
	task_service = app.config['task_service']
	try:
		task_service.cancel_task(task_id=task_id, user_id=current_user.uid)
	except TaskNotFoundError as e:
		return "Task not found", 404
	except services.InvalidStateForCancel as e:
		return str(e), 403
	except Exception as e:
		return str(e), 500
	
	return f"OK", 200

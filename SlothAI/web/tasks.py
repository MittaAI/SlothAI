import json
import traceback

from flask import Blueprint, request, jsonify
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

        # clear any errors
        task.error = None
        task_stored = task_service.fetch_tasks(task_id=task.id)
        app.logger.debug(task_stored)

        if len(task_stored) == 0:
            app.logger.debug(f"Task {task.id} not found. Removing from queue.")
            return "Task not found", 200

        if len(task_stored) != 1:
            raise Exception("Logic error: multiple tasks with same id")

        if task_stored[0]['state'] != TaskState.RUNNING.value:
            raise services.InvalidStateForProcess(task_stored.state.value)

        # run processors
        task = process(task)

        # remove the current node so we'll move on
        node = task.remove_node()

        # queue the next ndoe
        if len(task.nodes) > 0:
            task_service.queue_task(task)
        else:
            task_service.update_task(task_id=task.id, state=TaskState.COMPLETED)

        app.logger.info(f"Successfully processed task with id {task.id} on node with id {node} in pipeline with id {task.pipe_id}")

    except RetriableError as e:
        task.error = str(e)
        app.logger.error(f"Processing task with id {task.id} on node with id {task.next_node()} in pipeline with id {task.pipe_id}: {str(e)}: retrying task.")
        task_service.retry_task(task)

    except NonRetriableError as e:
        task.error = str(e)
        app.logger.error(f"Processing task with id {task.id} on node with id {task.next_node()} in pipeline with id {task.pipe_id}: {str(e)}: dropping task.")
        task_service.drop_task(task)
        return f"Error in task: {task.error}", 200

    except services.InvalidStateForProcess as e:
        # state likely changed during processing a task, don't requeue
        # TODO: this could be drop task but drop_task should accept a final state.
        return "Invalid state for processing", 200

    except Exception as e:
        traceback.print_exc()
        task.error = str(e)
        app.logger.error(f"Processing task with id {task.id} on node with id {task.next_node()} in pipeline with id {task.pipe_id}: {str(e)}: dropping task.")
        task_service.drop_task(task)

    return "Successfully completed node", 200


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
                return jsonify({"error": f"Invalid state: {state}"}), 400

    ok = task_service.delete_tasks_by_states(user_id=current_user.uid, states=states)
    if not ok:
        return jsonify({"error": "Issue deleting tasks"}), 500

    return jsonify({"message": "OK"}), 200


@tasks.route('/tasks/<task_id>', methods=['DELETE'])
@flask_login.login_required
def delete_task(task_id):
    task_service = app.config['task_service']
    tasks = task_service.fetch_tasks(task_id=task_id)
    if len(tasks) == 0:
        return jsonify({"error": "Task not found"}), 404

    # user can only delete task they own
    if tasks[0].user_id != current_user.uid:
        return jsonify({"error": "Task not found"}), 404

    if tasks[0].state == TaskState.RUNNING.value:
        return jsonify({"error": "Cannot delete a task in running state. Cancel the task first, then try again"}), 403

    ok = task_service.delete_task_by_id(task_id=task_id)
    if not ok:
        return jsonify({"error": "Issue deleting task"}), 500

    return jsonify({"message": "OK"}), 200


@tasks.route('/tasks/<task_id>/cancel', methods=['POST'])
@flask_login.login_required
def cancel_task(task_id):
    task_service = app.config['task_service']
    try:
        task_service.cancel_task(task_id=task_id, user_id=current_user.uid)
    except TaskNotFoundError as e:
        return jsonify({"error": "Task not found"}), 404
    except services.InvalidStateForCancel as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"message": "OK"}), 200


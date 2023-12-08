from abc import ABC, abstractmethod
from typing import Dict
from flask import current_app as app 

from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from SlothAI.lib.tasks import Task
from datetime import datetime, timedelta

import random
import os

class AbstractTaskQueue(ABC):
	@abstractmethod
	def queue(self, task: Task):
		pass

class AppEngineTaskQueue(ABC):

	def queue(self, task: Task):
		project_id = app.config['PROJECT_ID']
		client = tasks_v2.CloudTasksClient()
		queue = client.queue_path(project_id, app.config['SLOTH_QUEUE_REGION'], app.config['SLOTH_QUEUE'])
		encoding = task.to_json().encode()

		if app.config['DEV'] == "True":
			app_engine_task = {
				"http_request": {
					"url": f"{app.config['NGROK_URL']}/tasks/process/{app.config['CRON_KEY']}",
					"headers": {"Content-type": "application/json"},
					"http_method": tasks_v2.HttpMethod.POST
				}
			}
			app_engine_task["http_request"]["body"] = encoding
		else:
			app_engine_task = {
				"app_engine_http_request": {
					"http_method": tasks_v2.HttpMethod.POST,
					"app_engine_routing": {"version": os.environ['GAE_VERSION']},
					"relative_uri": f"/tasks/process/{app.config['CRON_KEY']}",
					"headers": {"Content-type": "application/json"}
				}
			}
			app_engine_task["app_engine_http_request"]["body"] = encoding


		# Create a timestamp
		timestamp = timestamp_pb2.Timestamp()

		# Calculate the time 15 seconds from now
		if task.document.get('run_in', None):
			future_time = datetime.utcnow() + timedelta(seconds=int(task.document.get('run_in')))
		else:
			delay = random.randint(100, 300)
			future_time = datetime.utcnow() + timedelta(milliseconds=delay)

		# Set the timestamp using the calculated future time
		timestamp.FromDatetime(future_time)

		app_engine_task["schedule_time"] = timestamp

		# Send the task to the Cloud Tasks queue
		response = client.create_task(parent=queue, task=app_engine_task)

		# self.id = response.name.split('/')[-1]
import re
import random
import string
import requests

from flask import current_app as app

# random strings
def random_string(size=6, chars=string.ascii_letters + string.digits):
	return ''.join(random.choice(chars) for _ in range(size))

# get box status
def box_status(box_id="", zone=""):
	if box_id == "":
		# get all status
		
		# reach out to the controller box
		url = f"http://{app.config['SLOTH_CONTROLLER_USERNAME']}:{app.config['SLOTH_TOKEN']}@{app.config['SLOTH_CONTROLLER_IP']}:8787/api/instance/list?token={app.config['SLOTH_TOKEN']}"

		headers = {"Content-Type": "application/json"}
		response = requests.get(url, headers=headers)

		try:
			boxes = []

			for box in response.json():
				zone_url = box.get('zone')
				pattern = r"/zones/([^/]+)$"
				match = re.search(pattern, zone_url)
				zone = match.group(1) if match else None

				boxes.append({
					"box_id": box.get('name'),
					"ip_address": box.get('networkInterfaces')[0].get('accessConfigs')[0].get('natIP', None),
					"status": box.get('status'),
					"zone": zone
				})
				print(boxes)

			return boxes
		except Exception as ex:
			return {"error": ex}
	else:
		if zone == "":
			return {"error": "no zone specified"}

		# reach out to the controller box
		# /api/instance/<zone>/<instance_id>/status
		url = f"http://{app.config['SLOTH_CONTROLLER_USERNAME']}:{app.config['SLOTH_TOKEN']}@{app.config['SLOTH_CONTROLLER_IP']}:8787/api/instance/{zone}/{box_id}/status?token={app.config['SLOTH_TOKEN']}"

		headers = {"Content-Type": "application/json"}
		response = requests.get(url, headers=headers)

		box = response.json()
		zone_url = box.get('zone')
		pattern = r"/zones/([^/]+)$"
		match = re.search(pattern, zone_url)
		zone = match.group(1) if match else None

		boxes = [{
					"box_id": box.get('name'),
					"ip_address": box.get('networkInterfaces')[0].get('accessConfigs')[0].get('natIP', None),
					"status": box.get('status'),
					"zone": zone
				}]
		print(boxes)
				
		return boxes

def box_start(box_id="", zone="us-central1-a"):
		# reach out to the controller box
		# /api/instance/<zone>/<instance_id>/start
		url = f"http://{app.config['SLOTH_CONTROLLER_USERNAME']}:{app.config['SLOTH_TOKEN']}@{app.config['SLOTH_CONTROLLER_IP']}:8787/api/instance/{zone}/{box_id}/start?token={app.config['SLOTH_TOKEN']}"

		headers = {"Content-Type": "application/json"}
		response = requests.get(url, headers=headers)


def box_stop(box_id="", zone="us-central1-a"):
		# reach out to the controller box
		# /api/instance/<zone>/<instance_id>/start
		url = f"http://{app.config['SLOTH_CONTROLLER_USERNAME']}:{app.config['SLOTH_TOKEN']}@{app.config['SLOTH_CONTROLLER_IP']}:8787/api/instance/{zone}/{box_id}/stop?token={app.config['SLOTH_TOKEN']}"

		headers = {"Content-Type": "application/json"}
		response = requests.get(url, headers=headers)
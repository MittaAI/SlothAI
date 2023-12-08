import re

from flask import Blueprint, jsonify
from flask import current_app as app

from SlothAI.lib.gcloud import box_status

from SlothAI.web.models import Box

cron = Blueprint('cron', __name__)

# get box status
@cron.route('/cron/boxes/<box_id>/<cron_key>', methods=['GET'])
def status_handler(box_id="all", cron_key=""):
	if cron_key != app.config['CRON_KEY']:
		return jsonify([])

	if box_id == "all":
		boxes = box_status()
	else:
		boxes = box_status()
		for box in boxes:
			if box.get('box_id') == box_id:
				boxes = [box]
				break
		else:
			boxes = []

	box_list = []
	for box in boxes:
		box_list.append(box.get('box_id'))

		# check sloth- (with dash) is in name
		if "sloth-" in box.get('box_id'):
			# run create (which updates Box object in datastore - the cache of current boxes)
			Box.create(box.get('box_id'), box.get('ip_address'), box.get('zone'), box.get('status'))

	_boxes = Box.get_boxes()

	# purge old boxes
	for _box in _boxes:
		if _box.get('box_id') not in box_list:
			Box.delete(_box.get('box_id'))

	return _boxes

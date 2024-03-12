import re
from flask import Blueprint, jsonify
from flask import current_app as app
from SlothAI.lib.gcloud import box_status
from SlothAI.web.models import Box

cron = Blueprint('cron', __name__)

@cron.route('/cron/boxes/<box_id>/<cron_key>', methods=['GET'])
def status_handler(box_id="all", cron_key=""):
   """
   Cron handler to get the status of boxes and update the Box objects in the datastore.

   Args:
       box_id (str): The ID of the box to get the status for. If set to "all", it retrieves the status of all boxes.
       cron_key (str): The cron key for authentication.

   Returns:
       list: A JSON array of Box objects representing the current state of the boxes.

   Raises:
       None

   """
   if cron_key != app.config['CRON_KEY']:
       app.logger.warning("Invalid cron key")
       return jsonify([])

   if box_id == "all":
       response = box_status()
   else:
       response = box_status(box_id=box_id)

   if isinstance(response, dict) and response.get('status') == 'failed':
       app.logger.error(f"Failed to get box status: {response.get('error')}")
       return jsonify([])

   boxes = response if box_id == "all" else [box for box in response if box.get('box_id') == box_id]

   app.logger.info(f"Received boxes: {boxes}")

   box_list = [box.get('box_id') for box in boxes]

   for box in boxes:
       if "instructor-" in box.get('box_id') or "pdf-" in box.get('box_id'):
           # run create (which updates Box object in datastore - the cache of current boxes)
           Box.create(box.get('box_id'), box.get('ip_address'), box.get('zone'), box.get('status'))

   _boxes = Box.get_boxes()

   # purge old boxes
   for _box in _boxes:
       if _box.get('box_id') not in box_list:
           app.logger.info(f"Deleting old box: {_box.get('box_id')}")
           Box.delete(_box.get('box_id'))

   return jsonify(_boxes)
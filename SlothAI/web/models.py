import datetime
import zlib
import base64

from google.cloud import ndb

import flask_login

from SlothAI.lib.util import random_name, random_string, generate_token

import config as config

# client connection
client = ndb.Client()

# Create a context manager decorator
def ndb_context_manager(func):
    def wrapper(*args, **kwargs):
        with ndb.Client().context():
            result = func(*args, **kwargs)
        return result  # Return the result outside the context
    return wrapper

class Transaction(ndb.Model):
    uid = ndb.StringProperty()
    tid = ndb.StringProperty()
    created = ndb.DateTimeProperty()

    @classmethod
    @ndb_context_manager
    def get_old(cls, timestamp):
        entities = cls.query(cls.created < timestamp).fetch()
        return [entity.to_dict() for entity in entities]

    @classmethod
    @ndb_context_manager
    def get_by_tid(cls, tid):
        entity = cls.query(cls.tid == tid).get()
        return entity.to_dict() if entity else None

    @classmethod
    @ndb_context_manager
    def create(cls, tid=None, uid=None):
        table = cls(
            tid=tid,
            uid=uid,
            created=datetime.datetime.utcnow()
        )
        table.put()
        return table.to_dict()


class Template(ndb.Model):
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
    @ndb_context_manager
    def delete_by_uid(cls, uid):
        templates = cls.query(cls.uid == uid).fetch()
        if templates:
            for template in templates:
                template.key.delete()
            return True
        return False

    @staticmethod
    def compress_text(text):
        compressed_bytes = zlib.compress(text.encode('utf-8'))
        return base64.b64encode(compressed_bytes).decode('utf-8')

    @staticmethod
    def decompress_text(compressed_text):
        compressed_bytes = base64.b64decode(compressed_text.encode('utf-8'))
        decompressed_bytes = zlib.decompress(compressed_bytes)
        return decompressed_bytes.decode('utf-8')

    @classmethod
    @ndb_context_manager
    def create(cls, name, uid, text, input_fields=[], output_fields=[], extras=[], processor="jinja2"):
        current_utc_time = datetime.datetime.utcnow()
        existing_template = cls.query(cls.name == name, cls.uid == uid).get()

        if not existing_template:
            template_id = random_string(13)
            template = cls(
                template_id=template_id,
                name=name,
                uid=uid,
                text=cls.compress_text(text),
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
    def update(cls, template_id, uid, name, text, input_fields=[], output_fields=[], extras=[], processor="jinja2"):
        template = cls.query(cls.template_id == template_id, cls.uid == uid).get()
        if not template:
            return None

        template.name = name
        template.text = cls.compress_text(text)
        template.input_fields = input_fields
        template.output_fields = output_fields
        template.extras = extras
        template.processor = processor

        template.put()

        return template.to_dict()

    @classmethod
    @ndb_context_manager
    def fetch(cls, **kwargs):
        query_conditions = []

        if 'processor' in kwargs and 'uid' in kwargs:
            query_conditions.append(cls.processor == kwargs['processor'], cls.uid == kwargs['uid'])
        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).fetch()
        else:
            entities = None

        templates = []
        for entity in entities:
            template = entity.to_dict()
            template['text'] = cls.decompress_text(entity.text)  # Decompress the stored text
            templates.append(template)

        return templates


    @classmethod
    @ndb_context_manager
    def get(cls, **kwargs):
        query_conditions = []

        if 'processor' in kwargs and 'uid' in kwargs:
            query_conditions.append(cls.processor == kwargs['processor'], cls.uid == kwargs['uid'])
        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            template = cls.query(query).get()

        if template:
            template_dict = template.to_dict()
            template_dict['text'] = cls.decompress_text(template.text)  # Decompress the stored text
            return template_dict
        else:
            return None


    @classmethod
    @ndb_context_manager
    def delete(cls, **kwargs):
        query_conditions = []

        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entity = cls.query(query).get()

        if entity:
            entity.key.delete()
            return True
        else:
            return False


class Node(ndb.Model):
    node_id = ndb.StringProperty()
    name = ndb.StringProperty()
    uid = ndb.StringProperty()
    created = ndb.DateTimeProperty()
    processor = ndb.StringProperty()
    template_id = ndb.StringProperty()
    extras = ndb.JsonProperty() # holds model flavor, tokens, etc.

    @classmethod
    @ndb_context_manager
    def delete_by_uid(cls, uid):
        nodes = cls.query(cls.uid == uid).fetch()
        if nodes:
            for node in nodes:
                node.key.delete()
            return True
        return False

    @classmethod
    @ndb_context_manager
    def rename(cls, uid, node_id, new_name):
        node = cls.query(cls.uid == uid, cls.node_id == node_id).get()
        node.name = new_name
        node.put()
        return node.to_dict()

    @classmethod
    @ndb_context_manager
    def update_extras(cls, uid, node_id, new_extras):
        node = cls.query(cls.uid == uid, cls.node_id == node_id).get()
        
        # Clear the existing extras dictionary
        node.extras = {}
        
        # Check if the "processor" key is present in new_extras
        if "processor" in new_extras:
            node.processor = new_extras["processor"]
        
        # Update the extras with the new data
        for key, value in new_extras.items():
            node.extras[key] = value
        
        # Save the updated node
        node.put()
        
        return node.to_dict()

    @classmethod
    @ndb_context_manager
    def create(cls, name, uid, extras, processor, template_id):
        current_utc_time = datetime.datetime.utcnow()
        node = cls.query(cls.name == name, cls.uid == uid).get()

        if not node:
            if template_id:
                # ensure we have the template
                template = Template.query(Template.template_id == template_id).get()
                if not template:
                    template_id = None
            else:
                template_id = None

            node_id = random_string(13)
            node = cls(
                node_id=node_id,
                name=name,
                uid=uid,
                extras=extras,
                created=current_utc_time,
                processor=processor,
                template_id=template_id
            )
            node.put()

        return node.to_dict()

    @classmethod
    @ndb_context_manager
    def update(cls, node_id, name, extras, processor, template_id):
        node = cls.query(cls.node_id == node_id).get()
        if not node:
            return None

        if template_id:
            template = Template.query(Template.template_id == template_id).get()
            if not template:
                template_id = None
        else:
            template_id = None

        node.name = name
        node.extras = extras
        node.processor = processor
        node.template_id = template_id

        node.put()

        return node.to_dict()

    @classmethod
    @ndb_context_manager
    def get(cls, **kwargs):
        query_conditions = []

        if 'node_id' in kwargs:
            query_conditions.append(cls.node_id == kwargs['node_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            node = cls.query(query).get()
        
        if query_conditions and node:
            return node.to_dict()
        else:
            return None

    @classmethod
    @ndb_context_manager
    def fetch(cls, **kwargs):
        query_conditions = []

        if 'node_id' in kwargs:
            query_conditions.append(cls.node_id == kwargs['node_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])
        if 'template_id' in kwargs:
            query_conditions.append(cls.template_id == kwargs['template_id'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).fetch()
        else:
            entities = []

        nodes = []
        for entity in entities:
            _entity = entity.to_dict()
            nodes.append(_entity)
        return nodes

    @classmethod
    @ndb_context_manager
    def delete(cls, **kwargs):
        query_conditions = []

        if 'node_id' in kwargs:
            query_conditions.append(cls.node_id == kwargs['node_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).get()
        else:
            entities = None

        if entities:
            entities.key.delete()
            return True
        else:
            return False

    @classmethod
    @ndb_context_manager
    def delete_by_pipe_id(cls, pipe_id):
        pipe = cls.query(cls.pipe_id == pipe_id).get()
        if pipe:
            pipe.key.delete()
            return True
        return False


class Pipeline(ndb.Model):
    pipe_id = ndb.StringProperty()
    uid = ndb.StringProperty()
    name = ndb.StringProperty()
    node_ids = ndb.JsonProperty()
    created = ndb.DateTimeProperty()

    @classmethod
    @ndb_context_manager
    def delete_by_uid(cls, uid):
        pipes = cls.query(cls.uid == uid).fetch()
        if pipes:
            for pipe in pipes:
                pipe.key.delete()
            return True
        return False

    @classmethod
    @ndb_context_manager
    def create(cls, uid, name, node_ids):
        current_utc_time = datetime.datetime.utcnow()
        pipeline = cls.query(cls.uid == uid, cls.name == name).get()

        if not pipeline:
            pipe_id = random_string(13)
            pipeline = cls(
                pipe_id=pipe_id,
                uid=uid,
                name=name,
                node_ids=node_ids,
                created=current_utc_time
            )
            pipeline.put()

        else:
            pipeline.node_ids = node_ids
            pipeline.put()

        return pipeline.to_dict()

    @classmethod
    @ndb_context_manager
    def add_node(cls, uid, pipe_id, node_id):
        # Fetch the pipeline by pipe_id
        pipeline = cls.query(cls.pipe_id == pipe_id).get()

        if pipeline:
            # Update the node_ids
            pipeline.node_ids.append(node_id)

            # Save the changes
            pipeline.put()

            return pipeline.to_dict()  # Return the updated pipeline as a dictionary
        else:
            # Handle the case where the pipeline doesn't exist
            return None 

    @classmethod
    @ndb_context_manager
    def get_by_uid_node_id(cls, uid, node_id):
        pipelines = cls.query(cls.uid == uid).fetch()
        
        node_pipelines = []
        for pipeline in pipelines:
            if node_id in pipeline.to_dict().get('node_ids'):
                node_pipelines.append({"name": pipeline.name, "pipe_id": pipeline.pipe_id})

        return node_pipelines if node_pipelines else None

    @classmethod
    @ndb_context_manager
    def get(cls, **kwargs):
        query_conditions = []

        if 'pipe_id' in kwargs:
            query_conditions.append(cls.pipe_id == kwargs['pipe_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            pipeline = cls.query(query).get()

        if query_conditions and pipeline:
            return pipeline.to_dict()
        else:
            return None

    @classmethod
    @ndb_context_manager
    def fetch(cls, **kwargs):
        query_conditions = []

        if 'pipe_id' in kwargs:
            query_conditions.append(cls.node_id == kwargs['pipe_id'])
        if 'name' in kwargs:
            query_conditions.append(cls.name == kwargs['name'])
        if 'uid' in kwargs:
            query_conditions.append(cls.uid == kwargs['uid'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).fetch()
        else:
            entities = None

        pipelines = []
        for entity in entities:
            _entity = entity.to_dict()
            pipelines.append(_entity)

        return pipelines

    @classmethod
    @ndb_context_manager
    def delete_by_pipe_id(cls, pipe_id):
        pipe = cls.query(cls.pipe_id == pipe_id).get()
        if pipe:
            pipe.key.delete()
            return True
        return False


# this needs to go to Laminoid
class Box(ndb.Model):
    box_id = ndb.StringProperty()
    ip_address = ndb.StringProperty()
    zone = ndb.StringProperty()
    status = ndb.StringProperty(default='NEW')  # PROVISIONING, STAGING, RUNNING, STOPPING, SUSPENDING, SUSPENDED, REPAIRING, and TERMINATED
    created = ndb.DateTimeProperty()
    runs = ndb.JsonProperty()  # models it runs

    @classmethod
    @ndb_context_manager
    def create(cls, box_id, ip_address, zone, status):
        current_utc_time = datetime.datetime.utcnow()
        expiration_time = current_utc_time + datetime.timedelta(days=7)  # Expiry in 7 days

        box = cls.query(cls.box_id == box_id).get()
        if not box:
            box = cls(box_id=box_id, ip_address=ip_address, zone=zone, status=status, created=current_utc_time)
        else:
            box.ip_address = ip_address
            box.status = status
            box.zone = zone

        box.put()
        return box.to_dict()

    @classmethod
    @ndb_context_manager
    def delete(cls, box_id):
        box = cls.query(cls.box_id == box_id).get()
        if box:
            box.key.delete()
            return True
        return False

    @classmethod
    @ndb_context_manager
    def get_boxes(cls):
        boxes = cls.query().fetch()
        return [box.to_dict() for box in boxes]

    @classmethod
    @ndb_context_manager
    def start_box(cls, box_id, status="START"):
        box = cls.query(cls.box_id == box_id).get()
        if box:
            box.status = status
            box.put()
            return box.to_dict()
        return None

    @classmethod
    @ndb_context_manager
    def stop_box(cls, box_id, status="STOP"):
        box = cls.query(cls.box_id == box_id).get()
        if box:
            box.status = status
            box.put()
            return box.to_dict()
        return None


class User(flask_login.UserMixin, ndb.Model):
    uid = ndb.StringProperty()  # user_id
    name = ndb.StringProperty()  # assigned name
    created = ndb.DateTimeProperty()
    updated = ndb.DateTimeProperty()
    expires = ndb.DateTimeProperty()

    # phone settings
    phone = ndb.StringProperty()
    phone_code = ndb.StringProperty(default=False)
    failed_2fa_attempts = ndb.IntegerProperty(default=0)

    # email actions
    email = ndb.StringProperty()
    mail_token = ndb.StringProperty()
    mail_confirm = ndb.BooleanProperty(default=False)
    mail_tries = ndb.IntegerProperty(default=0)

    # database settings
    dbid = ndb.StringProperty()
    db_token = ndb.StringProperty()

    # status
    authenticated = ndb.BooleanProperty(default=False)
    active = ndb.BooleanProperty(default=True)
    anonymous = ndb.BooleanProperty(default=False)
    admin = ndb.BooleanProperty()
    account_type = ndb.StringProperty(default="free")

    # API use
    api_token = ndb.StringProperty()

    # flask-login
    def is_active(self):  # all accounts are active
        return self.active

    def get_id(self):
        return self.uid

    def is_authenticated(self):
        return self.authenticated

    def is_anonymous(self):
        return self.anonymous

    def has_phone(self):
        if self.phone != "+1":
            return True
        return False

    @classmethod
    @ndb_context_manager
    def token_reset(cls, uid):
        user = cls.query(cls.uid == uid).get()
        user.api_token = generate_token()
        user.put()
        return user.to_dict()

    @classmethod
    @ndb_context_manager
    def create(cls, email="noreply@mitta.ai", phone="+1"):
        name = random_name(3)
        uid = random_string(size=17)
        user = cls(
            uid = uid,
            name = name,
            email = email,
            account_type = "free",
            phone = phone,
            phone_code = generate_token(),
            created = datetime.datetime.utcnow(),
            updated = datetime.datetime.utcnow(),
            expires = datetime.datetime.utcnow() + datetime.timedelta(days=15),
            admin = False,
            mail_token = generate_token(),
            api_token = generate_token()
        )
        user.put()
        return cls.query(cls.email == email).get()

    @classmethod
    @ndb_context_manager
    def bump_mail(cls, uid, tries):
        user = cls.query(cls.uid == uid).get()
        user.mail_tries = tries
        user.put()
        return user.to_dict()

    @classmethod
    @ndb_context_manager
    def update_db(cls, uid=None, dbid="", db_token=""):
        user = cls.query(cls.uid == uid).get()
        user.dbid = dbid
        user.db_token = db_token
        user.put()
        return user.to_dict()

    @classmethod
    @ndb_context_manager
    def remove_by_uid(cls, uid):
        user = cls.query(cls.uid == uid).get()
        if user:
            user.key.delete()
            return True
        return False

    @classmethod
    @ndb_context_manager
    def authenticate(cls, uid):
        user = cls.query(cls.uid == uid).get()
        user.authenticated = True
        user.put()
        return user

    @classmethod
    @ndb_context_manager
    def get_by_name(cls, name):
        result = cls.query(cls.name == name).get()
        return result.to_dict() if result else None

    @classmethod
    def get_by_email(cls, email):
        with client.context():
            return cls.query(cls.email == email).get()

    @classmethod
    @ndb_context_manager
    def get_by_dbid(cls, dbid):
        result = cls.query(cls.dbid == dbid).get()
        return result.to_dict() if result else None

    @classmethod
    @ndb_context_manager
    def get_by_uid(cls, uid):
        result = cls.query(cls.uid == uid).get()
        return result.to_dict() if result else None

    @classmethod
    @ndb_context_manager
    def get_by_token(cls, api_token):
        result = cls.query(cls.api_token == api_token).get()
        return result.to_dict() if result else None

    @classmethod
    @ndb_context_manager
    def reset_token(cls, uid):
        user = cls.query(cls.uid == uid).get()
        user.api_token = generate_token()
        user.put()
        
        return user.to_dict() if user else None

    @classmethod
    def get_by_mail_token(cls, mail_token):
        with client.context():
            return cls.query(cls.mail_token == mail_token).get()


class Token(ndb.Model):
    token_id = ndb.StringProperty()
    user_id = ndb.StringProperty()
    name = ndb.StringProperty()
    value = ndb.JsonProperty()
    created = ndb.DateTimeProperty()

    @classmethod
    @ndb_context_manager
    def create(cls, user_id, name, value):
        id = random_string(size=13)
        token = cls.query(cls.user_id == user_id, cls.name == name).get()
        if token:
            return token.to_dict()

        # otherwise, create
        token = cls(
            token_id=id,
            user_id=user_id,
            name=name,
            value=value,
            created=datetime.datetime.utcnow(),
        )
        token.put()
        return token.to_dict()

    @classmethod
    @ndb_context_manager
    def get_by_uid_name(cls, user_id, name):
        token = cls.query(cls.user_id == user_id, cls.name == name).get()
        if token:
            return token.to_dict()
        return None

    @classmethod
    @ndb_context_manager
    def get_all_by_uid(cls, user_id):
        tokens = cls.query(cls.user_id == user_id).fetch()
        _tokens = []
        for token in tokens:
            _tokens.append(token.to_dict())
        return _tokens

    @classmethod
    @ndb_context_manager
    def delete_all(cls, user_id):
        entities = cls.query(cls.user_id == user_id).fetch()
        if entities:
            for entity in entities:
                entity.key.delete()
        return True

    @classmethod
    @ndb_context_manager
    def delete(cls, user_id, token_id):
        entity = cls.query(cls.user_id == user_id, cls.token_id == token_id).get()
        if entity:
            entity.key.delete()
            return True
        else:
            return False

class Log(flask_login.UserMixin, ndb.Model):
    log_id = ndb.StringProperty()
    user_id = ndb.StringProperty()
    node_id = ndb.StringProperty()
    pipe_id = ndb.StringProperty()
    line = ndb.BlobProperty()
    created = ndb.DateTimeProperty()

    @classmethod
    @ndb_context_manager
    def create(cls, user_id, node_id, pipe_id, line):
        id = random_string(size=17)
        log = cls(
            log_id=id,
            user_id=user_id,
            node_id=node_id,
            pipe_id=pipe_id,
            created=datetime.datetime.utcnow(),
            line=str(line).encode('utf-8')
        )
        log.put()
        return log.to_dict()

    @classmethod
    @ndb_context_manager
    def delete_all(cls, user_id):
        entities = cls.query(cls.user_id == user_id).fetch()
        if entities:
            for entity in entities:
                entity.key.delete()

    @classmethod
    @ndb_context_manager
    def delete_older_than(cls, hours=0, minutes=0, seconds=0):
        threshold = datetime.datetime.utcnow() - \
            datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)
        entities = cls.query(cls.created < threshold).fetch()
        if entities:
            for entity in entities:
                entity.key.delete()

    @classmethod
    @ndb_context_manager
    def fetch(cls, **kwargs):
        query_conditions = []

        if 'log_id' in kwargs:
            query_conditions.append(cls.log_id == kwargs['log_id'])
        if 'uid' in kwargs:
            query_conditions.append(cls.user_id == kwargs['uid'])
        if 'node_id' in kwargs:
            query_conditions.append(cls.user_id == kwargs['node_id'])
        if 'pipe_id' in kwargs:
            query_conditions.append(cls.user_id == kwargs['pipe_id'])

        if query_conditions:
            query = ndb.AND(*query_conditions)
            entities = cls.query(query).order(-cls.created).fetch()
        else:
            entities = None

        logs = []
        for entity in entities:
            _entity = entity.to_dict()
            _entity['line'] = entity.line.decode('utf-8')
            logs.append(_entity)

        return logs

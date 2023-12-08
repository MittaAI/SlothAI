import flask_login

from flask import Flask, render_template, make_response, request, redirect
from flask_compress import Compress

from apscheduler.schedulers.background import BackgroundScheduler

from google.cloud import ndb

from SlothAI.web.site import site
from SlothAI.web.auth import auth
from SlothAI.web.cron import cron
from SlothAI.web.tasks import tasks

from SlothAI.web.pipelines import pipeline
from SlothAI.web.nodes import node_handler
from SlothAI.web.settings import settings_handler
from SlothAI.web.templates import template_handler
from SlothAI.web.custom_commands import custom_commands
from SlothAI.web.callback import callback

from SlothAI.web.models import User, Log

import config as config 

from SlothAI.lib.services import TaskService, TemplateService
from SlothAI.lib.storage import NDBTaskStore, NDBTemplateStore
from SlothAI.lib.queue import AppEngineTaskQueue

def create_app(conf='dev'):

    app = Flask(__name__)
    compress = Compress()
    compress.init_app(app)
    
    # Enable pretty-printing for JSON responses
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

    if conf == 'testing':
        app.config.from_object(config.TestingConfig)
    elif conf == 'dev':
        app.config.from_object(config.DevConfig)
    elif conf == 'prod':
        app.config.from_object(config.ProdConfig)
    else:
        raise Exception("invalid conf argument: must be 'testing', 'dev', or 'prod'.") 

    # logins
    login_manager = flask_login.LoginManager()
    login_manager.init_app(app)
    login_manager.session_protection = "strong"
    login_manager.login_message = u""

    # client connection
    client = ndb.Client()

    ndb_task_store = NDBTaskStore()
    ndb_template_store = NDBTemplateStore()
    app_engine_queue = AppEngineTaskQueue()

    task_service = TaskService(task_store=ndb_task_store, task_queue=app_engine_queue)
    template_service = TemplateService(template_store=ndb_template_store)

    app.config['task_service'] = task_service
    app.config['template_service'] = template_service

    def clean_logs():
        Log.delete_older_than(hours=1)
        # app.logger.info('ran background process to delete old callback logs')

    def clean_tasks():
        task_service.delete_older_than(hours=1)
        # app.logger.info('ran background process to delete old tasks')
    
    scheduler = BackgroundScheduler()
    _ = scheduler.add_job(clean_logs, 'interval', minutes=5)
    _ = scheduler.add_job(clean_tasks, 'interval', minutes=5)

    scheduler.start()


    @login_manager.request_loader
    def load_request(request):
        # get a token, if there is one
        token = request.args.get('token')
        if not token:
            token = request.form.get('token')

        if token:
            with client.context():
                user = User.query().filter(User.api_token==token).get()
            return user
        else:
            return None

    @login_manager.user_loader 
    def load_user(uid):
        try:
            # get the user
            with client.context():
                if uid != "anonymous":
                    user = User.query().filter(User.uid==uid).get()

            if user.authenticated == False and uid !="anonymous":
                return None

        except Exception as ex:
            print("In load user error was %s" % ex)
            return None

        return user

    # blueprints
    with app.app_context():
        app.register_blueprint(site)
        app.register_blueprint(auth)
        app.register_blueprint(settings_handler)
        app.register_blueprint(cron)
        app.register_blueprint(tasks)
        app.register_blueprint(pipeline)
        app.register_blueprint(node_handler)
        app.register_blueprint(template_handler)
        app.register_blueprint(custom_commands)
        app.register_blueprint(callback)

    login_manager.blueprint_login_views = {
        'site': "/login",
    }

    @app.before_request
    def before_request():
        forwarded_proto = request.headers.get('X-Forwarded-Proto')

        if app.config['DEV'] == "True":
            return

        # Check if the request is already secure (HTTPS)
        if forwarded_proto == 'https':
            return

        # Disable redirects for URLs that contain "tasks" to avoid a loop
        if "tasks" in request.url:
            return

        if forwarded_proto == 'http':
            url = request.url.replace("http", "https", 1)
            return redirect(url, code=302)

        return

    @app.errorhandler(404)
    def f404_notfound(e):
        # Check if the request URL contains "/static/templates/"
        if "/static/templates/" in request.path:
            return "Not found.", 404
        else:
            # Render the 404 HTML page for other URLs
            response = make_response(render_template('pages/404_notfound.html'))
            return response, 404

    return app
    # flask --app SlothAI run --port 8080 --debug
import json
from typing import Dict
from jinja2 import Environment, Undefined
from SlothAI.lib.tasks import Task
from SlothAI.web.custom_commands import random_word, random_sentence, random_chars, chunk_with_page_filename, filter_shuffle, random_entry
from SlothAI.lib import processor

def safe_tojson(value):
    def handle_undefined(value):
        if isinstance(value, Undefined):
            return "Undefined"
        elif isinstance(value, dict):
            return {k: handle_undefined(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [handle_undefined(item) for item in value]
        else:
            return value

    processed_data = handle_undefined(value)
    return json.dumps(processed_data)

env = Environment(trim_blocks=True, lstrip_blocks=True)
env.globals['random_chars'] = random_chars
env.globals['random_word'] = random_word
env.globals['random_sentence'] = random_sentence
env.globals['random_entry'] = random_entry
env.globals['chunk_with_page_filename'] = chunk_with_page_filename
env.filters['shuffle'] = filter_shuffle
env.filters['safe_tojson'] = safe_tojson


@processor
def jinja2(node: Dict[str, any], task: Task, is_post_processor=False) -> Task:
    try:
        app.logger.debug(f"Entering post-processor 'jinja2' for task with id {task.id}")

        # set the time for the template
        current_epoch_time = int(time.time())
        task.document['current_epoch'] = current_epoch_time

        # load templates
        template_service = app.config['template_service']
        template = template_service.get_template(template_id=node.get('template_id'))

        if not template:
            raise TemplateNotFoundError(template_id=node.get('template_id'))

        template_text = Template.remove_fields_and_extras(template.get('text'))
        template_text = template_text.strip()

        # If we have text we try to get the JSON out of it
        if template_text:
            # Test if this is a post_processor run
            if is_post_processor:
                # Define a fake template to project json into
                templates = {
                    "base": """
                    {% block json %}
                    {% endblock %}
                    """
                }

                # child template gets the template_text from the node, extends base and is updated to templates
                child = "{% extends 'base' %}\n" + template_text
                templates.update({"child": child})

                # set the environment and load custom functions
                json_env = Environment(loader=DictLoader(templates))
                json_env.globals['random_chars'] = random_chars
                json_env.globals['random_word'] = random_word
                json_env.globals['random_sentence'] = random_sentence
                json_env.globals['random_entry'] = random_entry
                json_env.globals['chunk_with_page_filename'] = chunk_with_page_filename
                json_env.filters['shuffle'] = filter_shuffle

                # Set new environment with the dictloader, grab the child template
                try:
                    child_template = json_env.get_template('child')
                except:
                    # template had issues TODO fix this
                    app.logger.debug("Passing on doing anything with Jinja2 due to not finding the child template from above?")
                    return task

                try:
                    # render the template with the document
                    jinja_json = child_template.render(task.document)
                except Exception as e:
                    raise NonRetriableError(f"jinja2 processor: {e}")
            else:
                try:
                    # Render the entire template, as we are running the jinja2 processor
                    jinja_template = env.from_string(template_text)
                    jinja_json = jinja_template.render(task.document)
                except Exception as e:
                    raise NonRetriableError(f"jinja processor: {e}")

            # update the task.document with the rendered dict
            try:
                task.document.update(json.loads(jinja_json.strip()))
            except Exception:
                app.logger.debug("Passing on doing anything with Jinja2, got an error trying to evaluate the dictionary.")
                # From now on, we'll just ignore that we don't have a dict in the template loaded by this processor
                pass

    except NonRetriableError as e:
        app.logger.error(f"NonRetriableError in post-processor 'jinja2' for task with id {task.id}: {str(e)}")
        raise
    except Exception as e:
        app.logger.error(f"Error in post-processor 'jinja2' for task with id {task.id}: {str(e)}")
        raise NonRetriableError(str(e))

    app.logger.debug(f"Exiting post-processor 'jinja2' for task with id {task.id}")
    return task
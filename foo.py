from jinja2 import Environment, DictLoader

# Define both the base template and the child template in a dictionary
templates = {
    "base_template.html": """
{% block json %}
<!-- Default JSON content if not overridden -->
{% endblock %}
""",
    "child_template.html": """
{% extends 'base_template.html' %}

{% block json %}
{"foo": "{{ value }}"}  # Custom JSON content
{% endblock %}
"""
}

# Create an environment with DictLoader
env = Environment(loader=DictLoader(templates))

# Get the child template from the environment
child_template = env.get_template('child_template.html')

# Render the child template with context
rendered_content = child_template.render(value="bar")
print(rendered_content)


"""
jinja2 template loader for Amiga script generation

provides a simple interface for rendering templates from this package.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


# templates directory is the same directory as this file
_TEMPLATES_DIR = Path(__file__).parent

# create Jinja2 environment with file system loader
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(default=False),  # no HTML escaping for scripts
    trim_blocks=True,  # remove newline after block tags
    lstrip_blocks=True,  # strip leading whitespace from block tags
    keep_trailing_newline=True,  # preserve trailing newlines in templates
)


def render_template(name: str, **context) -> str:
    """
    render a Jinja2 template by name"""
    template = _env.get_template(name)
    return template.render(**context)


def get_template(name: str):
    """
    get a Jinja2 template object for more complex rendering"""
    return _env.get_template(name)

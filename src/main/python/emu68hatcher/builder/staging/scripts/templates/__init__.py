"""Jinja2 template loader for Amiga script generation (config.txt, shell-startup)"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(default=False),  # scripts, not HTML
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render_template(name: str, **context) -> str:
    return _env.get_template(name).render(**context)

"""Thin UI shells (Gradio WebUI / Typer CLI).

Modules here are the ONLY place that may import a UI library. They must call
:mod:`omnidoc.controller` — never an engine or processor directly.
"""

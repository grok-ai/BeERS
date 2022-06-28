# BeERS 🍻

[![badge](https://shields.io/badge/nn--template-0.0.2-emerald?style=flat&labelColor=gray)](https://github.com/lucmos/nn-template)
[![badge](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/downloads/)
[![badge](https://img.shields.io/badge/code%20style-black-000000.svg)](https://black.readthedocs.io/en/stable/)

Better Enabled Resource Sharing

## Installation

```bash
pip install git+ssh://git@github.com/grok-ai/beers.git
```


## Quickstart

[comment]: <> (> Fill me!)


## Development installation

Setup the development environment:

```bash
git clone git+ssh://git@github.com/grok-ai/beers.git
conda env create -f env.yaml
conda activate beers
pre-commit install
```

Run the tests:

```bash
pre-commit run --all-files
pytest -v
```


### Update the dependencies

Re-install the project in edit mode:

```bash
pip install -e .[dev]
```

# How to run the test files

## Running  example_bluesky_plan.py

two options:

### Using pip install of the built dispatcher (until published on synchrotrons pypi)

1. navigate to the bluesky-library folder where the pyproject.toml file resides
1. run `poetry build`
1. navigate back to this directory and create a virtual environment for the
example bluesky plan and activate it
1. pip install the .whl file found in the dist subdirectory of the bluesky-library folder
1. `python example_bluesky_plan.py`

### Just doing a local import

1. in this examples directory, create/activate a virtual environment
1. `pip install -r requirements.txt`
1. create a link to the dispatcher in this directory: `ln -s ../bluesky-library/bluesky_dispatcher.py bluesky_dispatcher.py`
1. `python example_bluesky_plan.py`

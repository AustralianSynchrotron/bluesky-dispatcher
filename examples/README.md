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

## run example scripts

Now that the dispatcher is running and you've activated a virtual environment
get the fastapi server up and running

### run a fastapi server to connect to the dispatcher

1. In a separate terminal, but also with the virtual environment activated run

   `BLUESKY_SERVICE_WEBSOCKET_URI=ws://localhost:8765 uvicorn example_fastapi_server:app --log-level="debug" --reload`
   
### run a standalone python script to connect to the dispatcher and issue a command to start a scan

This script is going to be the one to use if you want to test bluesky plans
you're writing work with the dispatcher.

1. In a separate terminal, but also with the virtual environment activated, run

    `python websocket-client-test.py`

    to test sending a websocket message directly to the running dispatcher
    (running by virtue of the example_bluesky_plan.py script)
    
### run a standalone python script to connect to the dispatcher as a subscriber listening for updates

1. In a separate terminal, but also with the virtual environment activated, run

    `python websocket-subscribe-test.py`

    this is basically the same script as the websocket-client-test.py
    but just sending a different type of websocket message that results in the
    connection staying open in order to 'listen' for future live updates.

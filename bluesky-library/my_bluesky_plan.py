"""
An example, making use of the helical scan demo from brightsac,
of how to utilise the bluesky_dispatcher
"""

from bluesky.plans import count
from ophyd.sim import det1, det2  # two simulated detectors
import time
import os
import functools  # necessary for https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
# see https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio-pass-keywords
from queue import Queue

from bluesky_dispatcher import *

WEBSOCKET_CONTROL_PORT = os.environ.get('WEBSOCKET_CONTROL_PORT', 8765)

# define your plan as a function that can be called (parameters must be defined as keyword args)

def do_fake_helical_scan(run_engine, hook_function, example_param_1=None, example_param_2=None):
    # the required function signature will have provision for the runEngine.
    # here I also add provision for the hook_function. but this is only
    # because I wish to 'simulate' the run engine being busy for testing
    # purposes. I don't think their is much of a need to give provisions
    # for the hook function. however on the other hand I could NOT make
    # any assumptions about how future dev's will make use of this dispatcher
    # class, and provide a provision for 'self' as in the dispatcher instance
    # itself. this now requires the dev to have a knowledge of the internal
    # functioning of the dispatcher. but at least allows one to make use of
    # such functionality if it turned out to be desirable... good idea or not?

    if example_param_1 is None and example_param_2 is None:
        print("simulation (fake) scan: No supplied parameters, running with my defaults")

    # print a message to aid diagnostics:
    timestamp_str = time.strftime("%d.%b %Y %H:%M:%S")
    print(f'{timestamp_str}:  running FAKE helical scan with '
          f'the following params: '
          f'example_param_1:{example_param_1}, '
          f'example_param_2:{example_param_2}')

    run_engine(count([det1, det2]))

    hook_function("running", "idle")  # because the above finished
    # so quickly, it doesn't look like much happens on the end users web
    # GUI, this is just to simulate the RunEngine entering another
    # "running" state so that when we're sleeping for 10 seconds the
    # button in the GUI is also showing that it's
    # currently *air quotes* Scanning...

    time.sleep(10)  # because hard to test accompanying threads when this
    # ends in a couple ms due to simulated detectors not simulating much

    hook_function("idle", "running")  # undo our artificial state
    # update, now we're back in line with the actual RunEngine state.

    print("scan finished ( in do_fake_helical_scan )")



# create an instance of the BlueskyDispatcher:
bd = BlueskyDispatcher(port=WEBSOCKET_CONTROL_PORT)

# add the function we defined to the dispatcher, providing a label which is how we will refer to the plan later
bd.add_scan(do_fake_helical_scan, 'simulated') # first arg is function, second is label to use when we're telling it which function to run

# start the dispatcher, which means it start listening for websocket connections. From now on we use a different service to interact with it (start plans, pause and stop them, get state).
bd.start()

# IGNORE THE BELOW VESTIGIAL CODE IN THIS CASE, THE ABOVE IS ALL THAT IS ENVISIONED THAT YOU WOULD NEED.

# THE RULES:
# you must interact with the dispatcher through the port number you have defined. (it may have a default)
# You must follow a defined and documented protocol to your websocket messages when you want it to run a plan you have previously added to it
# you must define your scan function, with any parameters you wish it to take, and you must declare those as kwargs.

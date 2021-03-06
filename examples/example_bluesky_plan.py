"""
Example of how to utilise the bluesky_dispatcher.
"""

# import libs required for our plan function:
from bluesky.plans import count
from ophyd.sim import det1, det2  # two simulated detectors
import time  # for print message timestamps
import os


# import everything from the bluesky_dispatcher:
from bluesky_dispatcher import *

import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s:%(levelname)s:%(module)s:%(message)s')
logger = logging.getLogger(__name__)

WEBSOCKET_CONTROL_PORT = os.environ.get('WEBSOCKET_CONTROL_PORT', 8765)


# define your plan as a function that can be called
# (parameters must be defined as keyword args)
def do_fake_scan(
        run_engine,
        hook_function,
        example_param_1=None,
        example_param_2=None):
    # the required function signature will have provision for the runEngine.

    # here I also add provision for the hook_function. but this is only
    # because I wish to 'simulate' the run engine being busy for testing
    # purposes. I don't think there is much of a need to give provisions
    # for the hook function. however on the other hand we could refrain from
    # making any assumptions about how future dev's will make use of this
    # dispatcher class, and provide a provision for 'self' as in the dispatcher
    # instance itself. But this now requires the dev to have a knowledge of the
    # internal functioning of the dispatcher. but at least allows one to make
    # use of such functionality if it turned out to be desirable... good idea
    # or not?
    if example_param_1 is None and example_param_2 is None:
        logger.debug("simulation (fake) scan: No supplied parameters, "
                     "running with my defaults")

    # print a message to aid diagnostics:
    timestamp_str = time.strftime("%d.%b %Y %H:%M:%S")
    logger.debug(f'running FAKE scan with the following params: '
                 f'example_param_1: {example_param_1}, '
                 f'example_param_2: {example_param_2}')

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

    logger.debug("scan finished ( in do_fake_scan )")


# create an instance of the BlueskyDispatcher:
bd = BlueskyDispatcher(port=WEBSOCKET_CONTROL_PORT)


def mycb(name, doc):
    print("#########################")
    print(name)
    print(doc)
    print("#########################")


token1 = bd.subscribe_callback_function(mycb)
token2 = bd.subscribe_callback_function(mycb, "start")
bd.unsubscribe_callback_function(token2)
token2 = bd.subscribe_callback_function(mycb, "start")
bd.unsubscribe_callback_function(token2)
token2 = bd.subscribe_callback_function(mycb, "start")
bd.unsubscribe_callback_function(token2)
token2 = bd.subscribe_callback_function(mycb, "start")
bd.unsubscribe_callback_function(token2)

try:
    print("testing the exception raising when asked"
          " to unsubscribe with a bad token")
    bd.unsubscribe_callback_function(404)
except LookupError as e:
    print("caught exception as expected")
    print(e)


# add the function we defined to the dispatcher,
# providing a label which is how we will refer to the plan later in our sent
# websocket messages:
bd.add_scan(do_fake_scan, 'simulated')
# first arg is function,
# second is label by which we can refer to this plan in future websocket
# messages

# start the dispatcher, which means it starts listening for websocket
# connections. From now on we use a different service to interact* with it
# *( start plans, pause and stop them, get state ).
# eg. we can invoke the scan to start by sending a websocket message of the
# form below, json encoded:
# {
#   type: "start",
#   plan: "simulated",
#   params: {
#     example_param_1: 200,
#     example_param_2: 1000
#   }
# }
bd.start()

# THE RULES:
# - You must interact with the dispatcher through the port number you have
#   defined. (it defaults to 8765)

# - You must follow the protocol, defined and documented in the
#   bluesky_dispatcher README, in your websocket messages_demo when you want it
#   to run a plan you have previously added to it

# - You must define your scan function, with any parameters you wish it to take,
#   and you must declare those as kwargs. (This is to allow the websocket
#   messages to provide the params to your function as json key values.)

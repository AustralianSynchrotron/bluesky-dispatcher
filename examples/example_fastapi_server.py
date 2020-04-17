from fastapi import FastAPI
from pydantic import BaseModel
# from enum import Enum
# from starlette.websockets import WebSocket
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.websockets import WebSocket
import websockets
import asyncio
import signal
import json
import os

BLUESKY_WEBSOCKET = os.environ.get('BLUESKY_SERVICE_WEBSOCKET_URI')
# This is the url to the websocket of the bluesky service, for
# example: ws://bluesky:8765  or  ws://localhost:8765

assert BLUESKY_WEBSOCKET is not None, ("Missing required environment variable "
                                       "(BLUESKY_SERVICE_WEBSOCKET_URI) "
                                       "pointing to the bluesky service's "
                                       "websocket")

OPENAPI_PREFIX = os.environ.get('OPENAPI_PREFIX', '')
# This is necessary because in deployment, there is a traefik reverse
# proxy that is rerouting requests to the path /bluesky/api to this
# service, but is also stripping that prefix out of the path so when
# this service gets a http request it doesn't see that they requested
# /bluesky/api/docs, it just sees that they requested /docs, and it
# responds normally, but because it believes it's accessible at /docs
# it encodes this into the javascript sent back to the client wherein
# there is a part that tries to fetch an openapi_spec.json type file
# that defines all the endpoints and is how the /docs UI is able to
# render the right information. But unfortunately from the clients point
# of view they are actually accessing this service not through SERVER/
# but SERVER/bluesky/api/ and the docs not through SERVER/docs but
# SERVER/bluesky/api/docs, so if the javascript they retrieve then tries
# to subsequently retrieve SERVER/openapi_spec.json instead of
# SERVER/bluesky/api/openapi_spec.json you can see that it's going to have
# trouble

# This prefix is to be used by the swagger documentation when it generates
# client side javascript, so that the client can formulate a request back to
# this service in order to retrieve the openapi spec json file that is needed
# to describe all the available endpoints when the client visits the /docs
# endpoint - This solves the issue of the openapi swagger plugin assuming
# that there is no url path prefixing or reverse proxy type stuff going on.
# (read https://github.com/apigee-127/swagger-tools/issues/342 for background)


HTTP_409_CONFLICT = 409

# create an object to share data between coroutines,
# stackoverflow link explains the python code:
# https://stackoverflow.com/questions/19476816/creating-an-empty-object-in-python#19476841
state = type('', (), {})()

state.update_event_object = None
# a file-wide accessible reference to an asyncio event object that coroutines
# can use to wait() for an event of interest.

state.update_event_type = None
# a file-wide accessible reference to a label to be paired with any set()
# action on the update_event_object to give the coroutines that were waiting
# on that some context to inform their actions.

# initial state (this is the source of truth):
# following information is shared with frontends and clients
state.busy = False
state.result = None


async def yield_control_back_to_event_loop():
    await asyncio.sleep(0)
    # this seems to be the idiomatic way:
    # https://github.com/python/asyncio/issues/284


async def notify_coroutines(event_type):
    """This function is to simplify the process of notifying coroutines of some
    event they may be waiting on and helps this file adhere to the DRY
    principle.
    """
    state.update_event_type = event_type
    state.update_event_object.set()
    state.update_event_object.clear()
    # Any coroutines await'ing this update_event_object will now be back in
    # the event loop. (execution will pass to them at some time after the
    # current coroutine awaits or ends)

    await yield_control_back_to_event_loop()
    # pass control back to the event loop so those waiting coroutines can
    # have a chance to execute before we do anything else.


async def start_scan(scan_name, params=None):
    # uri = "ws://localhost:8765"  # this needs to change to bluesky
    print(f'fastapi: making a websocket connection to bluesky ('
          f'{BLUESKY_WEBSOCKET}) to send job')

    # Todo: think if this needs a try except block to be able to handle if
    #  the websocket server is not available on the dispatcher side?
    async with websockets.connect(BLUESKY_WEBSOCKET) as websocket:
        payload = {"type": "start", "plan": scan_name, "params": params}
        await websocket.send(json.dumps(payload))
        # Todo: put in timeouts because we can't afford to be waiting forever
        #  for these (this function is called by one of the endpoint functions.
        response = await websocket.recv()
        await websocket.close(reason="will create a new connection \
                                      if I need to")
        return json.loads(response)
        # todo: this is at risk if the response ISN"T valid json but since we
        #  also authored the code sending the response back chances are it will
        #  be fine


async def pause_scan():
    # uri = "ws://localhost:8765"  # this needs to change to bluesky
    async with websockets.connect(BLUESKY_WEBSOCKET) as websocket:
        payload = {'type': 'pause'}
        await websocket.send(json.dumps(payload))
        response = await websocket.recv()
        await websocket.close(reason='will create a new connection \
                                      if I need to')
        return json.loads(response)
        # todo: this is at risk if the response ISN"T valid json but since we
        #  also authored the code sending the response back chances are it will
        #  be fine

#  -------------------------------------------------------
#  Start of our FastAPI implementation
#  -------------------------------------------------------
app = FastAPI(openapi_prefix=OPENAPI_PREFIX)

# for cors:
origins = [
    '*',
]
# for cors:
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


# defining the schema of acceptable POST request bodies for the endpoints
# /testfakehelicalscan and /testhelicalscan respectively, these should match
# the parameters taken in by the scan functions declared in the python file that
# also imports, invokes, and passes scan functions to the bluesky_dispatcher.

class FakeScanParams(BaseModel):
    example_param_1: int
    example_param_2: int


class HelicalParams(BaseModel):
    start_y: int = 10
    height: int = 10
    pitch: int = 2
    restful_host: str = 'http://camera-server:8000'
    websocket_url: str = 'ws://camera-server:8000/ws'

#  -----------------
#  FastAPI endpoints
#  -----------------

# The endpoint function names form the descriptions of the endpoints in the
# auto-generated swagger documentation.

@app.get('/')
def root_endpoint_for_diagnostics():
    return {
        'Helical': 'Scan',
        'About': 'This is the backend for the frontend (BFF) for the helical \
                  scan demo - see the /docs endpoint',
        'busy scanning': state.busy
    }


@app.post('/pausescan')
async def pause_any_currently_underway_scan():
    if state.busy:
        result = await pause_scan()
        return result
    else:
        return {'success': False,
                'status': 'no scan is currently running to be paused'}


@app.post('/testfakehelicalscan')
async def run_a_simulated_scan(s_params: FakeScanParams, response: Response):
    # THE FAKE ONE!
    if state.busy:
        response.status_code = HTTP_409_CONFLICT
        return {'success': False,
                'status': 'currently busy with a previous scan'}
    result = await start_scan('simulated', json.loads(s_params.json()))
    return result


@app.post('/testhelicalscan')
async def run_the_real_helical_scan_in_the_lab(s_params: HelicalParams, response: Response):
    # establish a new websocket connection to the bluesky websocket server
    if state.busy:
        response.status_code = HTTP_409_CONFLICT
        return {'success': False,
                'status': 'currently busy with a previous scan'}
    result = await start_scan('helical scan', json.loads(s_params.json()))
    return result


@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    """ The connection with a web browser that wishes to receive live updates on
    the bluesky dispatchers run engine's internal state so as to know whether a
    plan is currently executing or if the RunEngine is idle. """
    await websocket.accept()
    # Send an initial message to indicate what mode of 'busy' the state is in,
    # We refer to the global 'state' object to determine the 'busy'ness of the
    # RunEngine. (The global 'state' object is maintained in sync with the
    # RunEngine in the bluesky dispatcher by way of the bluesky_telemetery_task)
    await websocket.send_json({'busy': state.busy})
    while True:
        # continually notify our client whenever the bluesky_telemetry_task
        # notifies that it has updated the 'busy' property
        # (or it's a shutdown event)
        await state.update_event_object.wait()
        task_id = repr(asyncio.Task.current_task())  # diagnostics
        print(f'websocket coroutine: just woke up! {task_id}')  # diagnostics
        if state.update_event_type == 'busy':
            await websocket.send_json({'busy': state.busy})
        if state.update_event_type == 'shutdown':
            break
        if state.update_event_type == 'exception':
            await websocket.send_json({
                'exception': state.exception_message
            })
    await websocket.close()


#  -------------------------------------------------------
#  background task to run concurrently with fastapi server
#  -------------------------------------------------------

async def wait_for_available_websocket(url, timeout_seconds=None,
                                        retry_delay=1):
    try_forever = True if timeout_seconds is None else False
    retries_remaining = 0 if try_forever else int(timeout_seconds / retry_delay)

    while True:
        try:
            async with websockets.connect(url) as testsocket:
                return True
        except (ConnectionError, websockets.exceptions.InvalidMessage) as e:
            print(e)
            if not try_forever:
                retries_remaining -= 1
                if retries_remaining < 0:
                    return False
            print(f'unable to connect, will retry in {retry_delay} '
                  f'second/s')
            await asyncio.sleep(retry_delay)


async def be_robust(connection_func):
    while True:
        try:
            await connection_func()
        # to handle if connection breaks:
        except websockets.exceptions.ConnectionClosedError:
            print("connection to bluesky dispatcher lost")
        except ConnectionError:
            print("connection to bluesky dispatcher lost")
        except asyncio.streams.IncompleteReadError:
            print("connection to bluesky dispatcher lost")
        except ConnectionResetError:
            print("connection to bluesky dispatcher lost")
        except websockets.exceptions.InvalidMessage:
            print("connection to bluesky dispatcher lost")

async def subscribe_to_dispatcher():

    # wait for good connection before proceeding
    print("attempting to connect.")
    managed_to_connect = await wait_for_available_websocket(BLUESKY_WEBSOCKET)
    if managed_to_connect is False:
        pass
        # pass because we are happy to wait indefinitely for the websocket
        # (we do not pass any argument for timeout_seconds to the call to
        # wait_for_available_websocket) therefore this code is unreachable
        # but I include it as an example of completeness.
    async with websockets.connect(BLUESKY_WEBSOCKET) as websocket:
        await websocket.send(json.dumps({'type': 'subscribe'}))
        initial_response = await websocket.recv()
        print(f'telemetry task: got this initial response: '
              f'{initial_response}')
        # initial_response will be received almost immediately and serves to
        # update us on what the CURRENT state of the RunEngine is.
        re_state = json.loads(initial_response)['state']
        print(f'telemetry task: re_state: {re_state}')
        if re_state == 'running':
            state.busy = True
            print('telemetry task: Just set busy as True, now notifying'
                  ' coroutines')
            await notify_coroutines('busy')
            print('telemetry task: DONE notifying coroutines')
        elif re_state == 'idle':
            state.busy = False
            print('telemetry task: Just set busy as True, now notifying'
                  ' coroutines')
            await notify_coroutines('busy')
            print('telemetry task: DONE notifying coroutines')

        while True:
            an_update = await websocket.recv()
            print(f'telemetry task: received an update: {an_update}')
            if json.loads(an_update)['type'] == 'status':
                re_state = json.loads(an_update)['state']
                print(f'telemetry task: re_state: {re_state}')
                if re_state == 'idle':
                    print('telemetry task: Just set busy as False, now '
                          'notifying coroutines')
                    state.busy = False
                    await notify_coroutines('busy')
                    print('telemetry task: DONE notifying coroutines')
                if re_state == 'running':
                    state.busy = True
                    print('telemetry task: Just set busy as False, now '
                          'notifying coroutines')
                    await notify_coroutines('busy')
                    print('telemetry task: DONE notifying coroutines')
            elif json.loads(an_update)['type'] == 'exception':
            # about and message are the available keys when type is exception
            # and we can pretty much ignore 'about'
                state.exception_message = json.loads(an_update)['message']
                await notify_coroutines('exception')

async def bluesky_telemetry_task():
    """Basically this is the connection between this api and the bluesky
    dispatcher service so that this api can know whether the bluesky
    RunEngine is currently idle and ready to run a plan or busy with
    a current plan, and by proxy, so can our connected web browser clients."""

    await be_robust(subscribe_to_dispatcher)



#  -------------------------------------
#  fastapi startup and shutdown routines
#  -------------------------------------

def exit_gracefully(*args, **kwargs):
    state.update_event_type = 'shutdown'
    state.update_event_object.set()


@app.on_event('startup')
async def service_startup():
    # catch Ctrl+C inform websocket to leave loop in order to trigger fastapi
    # shutdown
    signal.signal(signal.SIGINT, exit_gracefully)
    signal.signal(signal.SIGTERM, exit_gracefully)

    # initialise the event_object used between coroutines to signal events:
    state.update_event_object = asyncio.Event(loop=asyncio.get_event_loop())

    # Start the background task and store the asyncio TASK object in a
    # task variable so as to capture any returned results or exceptions
    # to make use of such result would mean you would have to 'await'
    # the task variable. Admittedly this is a hacky attempt at fixing
    # https://stackoverflow.com/questions/46890646/asyncio-weirdness-of-task-exception-was-never-retrieved
    # todo: if the bluesky_telemetry_task suffers an exception we don't
    #  account for it crashes the program because it's never retrieved,
    #  however if it suffers an exception we haven't accounted for maybe we
    #  are happy for it to crash the program since we'd then be in an unknown
    #  state?
    print(f'starting bluesky_telemetry_task - connecting to'
          f' {BLUESKY_WEBSOCKET}')
    asyncio.ensure_future(bluesky_telemetry_task())
    # Link to the code used as inspiration for this trick (I didn't know you
    # could just do .create_task (or ensure_future in python 3.6), I thought
    # you would need to get a hold of
    # the event loop or something and use something like .gather or something!
    # https://github.com/tiangolo/fastapi/issues/617
    # The `@app.on_event("startup")` decorator was inappropriate for starting
    # our simulate_data_gathering coroutine because the actual fastAPI server
    # will not start until this is complete, but `while True` loop ensures it
    # never completes.

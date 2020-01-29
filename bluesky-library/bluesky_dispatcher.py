"""
This is the bluesky dispatcher service that gives interactivity via websockets
to the python script that runs a bluesky plan.

-----------
Motivation:

The intention is that if you can write a standalone python script that executes
a bluesky plan to run a scan and it works at the command line, and you can
pause the scan with CTRL-C, then if you can do the following:

    - modify your script to put your code in a callable function of the
        following signature:

        def my_scan(run_engine, example_param_1=1, example_param_2=2)

    - import this BlueskyDispatcher, instantiate it, pass the instance your scan
        function, and then call its start() method.

you will get:

    - a websocket server listening on port 8765 (can be overridden) that you
        can send websocket messages to in order to enact actions on the run
        engine such as starting a plan and pausing a plan.

    - a websocket server that can be 'subscribed' to in order to receive live
        message updates whenever the state of the RunEngine changes.

    - The ability to create a system where custom scan scripts can be loaded and
        used by users that pass their parameters and control the RunEngine
        through a web interface.

------------------
Technical details:


This is comprised of two distinct threads

The main thread is the thread that runs (executes) the bluesky plan on the
bluesky runengine, I got an error from the bluesky runengine when it was
run once in a thread that wasn't the main thread, however that was before
I instantiated it with an empty list of context_managers which may very
well have fixed its desire to be in the main thread, but whether it was in
the main thread or the newly spawned one made no difference for our
purposes so the main thread is the one that executes the bluesky plan and,

The other thread is the one that serves to listen for requests/commands
from an external source (such as an API service) and to then take the
appropriate actions against the runengine. In this case the other thread
spins up a websocket server coroutine that handles the connections. You
could also do something else like listen to events on a kafka queue or
whatever.

The use of threads was believed to be necessary because the runengine
provides crucial functionality by way of methods you can call such as
request_pause() that allow you to manipulate its behaviour, but when
its in the process of executing a plan it's blocking the thread it's in.
This is why I'm using another thread, instead of another process, to
listen to external events in some way (websockets in this case) and to
take subsequent actions against the same runengine object that is
currently busy with executing a plan.

Given the complexity of this service with respect to threads, any business
logic or UI provisions are envisioned to be implemented in a separate
service that just makes use of this service via the interface it exposes
(in this case, custom websocket message protocols)
Therefore the only thing in this service that should be changed in future
projects should be the instructions around how to perform the scan/experiment.
"""

from bluesky import RunEngine
import threading
import asyncio
import websockets
import json
import time
import functools  # necessary for https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
# see https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio-pass-keywords
from queue import Queue

def timestamp():
    return "[" + time.strftime("%d.%b %Y %H:%M:%S") + "]: "

class ScanNameError(Exception):
    """Raised when:
    - a scan function with a name that is already allocated to a previously
        supplied scan function is attempted to be added
    - a scan function is attempted to be removed that doesn't exist"""
    pass


class BlueskyDispatcher:

    def __init__(self, port=8765):
        self._RE = RunEngine(context_managers=[])
        # passing empty array as context managers so that the run engine will
        # not try to register signal handlers or complain that it's not the
        # main thread
        self._websocket_port = port

        self._selected_scan = None  # acts as a pointer to whichever scan
                                    # function is to be executed.
        self._supplied_params = None  # when the selected_scan is called, these
                                     # will be supplied as long as they are not
                                     # None
        self._scan_functions = {}  # key = name of the scan
        # value = a python function matching the required signature

        self._busy = threading.Lock()
        # Used by the RunEngine to signal that it's currently busy. Read by the
        # websocket threads to decide to refuse or accept a request to start a
        # scan.

        self._start_scanning = threading.Event()
        # Used by the websocket thread to signal the main thread that it should
        # start a scan. Which scan to be run should be selected before
        # set()'ing this event.

        self._re_state_changes_q = Queue()
        # Used to capture RunEngine state changes so no events are dropped,
        # even if they occur in rapid succession.
        # The addition of a new item in this queue is what 'wakes up' the
        # coroutine_to_bridge_thread_events_to_asyncio

        self._re_state_changes_data = None
        # Used to hold the information provided by the RunEngine whenever its
        # state changes. eg.: {'new_state': 'idle', 'old_state': 'running'}
        # Consumed by websocket connections serving 'subscribers'.

        self._websocket_state_update = asyncio.Event()
        # the event that 'wakes up' sleeping websocket subscriber connections
        # so they can consume above re_state_changes_data to feed to their
        # subscribers

        # register our state_hook function on the RunEngine, it will add updates
        # as items on the _re_state_changes_q Queue where the
        # coroutine_to_bridge_thread_events_to_asyncio function can work through
        # the items to one-by-one notify waiting websocket coroutines through
        # the above asyncio.Event()
        self._RE.state_hook = self.__state_hook
        print(f'{timestamp()}BlueskyDispatcher initialised.')


    def add_scan(self, scan_function, scan_name):
        if scan_name in self._scan_functions:
            raise ScanNameError(f'The supplied scan name "{scan_name}" is '
                                f'already in use, If you wish to overwrite the '
                                f'previously supplied scan function remove the '
                                f'existing one first with '
                                f'remove_scan("{scan_name}")')
        self._scan_functions[scan_name] = scan_function


    def remove_scan(self, scan_name):
        if scan_name not in self._scan_functions:
            raise ScanNameError(f'The supplied scan name "{scan_name}" is not '
                                f'in the list of scan functions')
        del self._scan_functions[scan_name]


    def start(self):
        # This code runs in the main thread.
        print(f'{timestamp()}BlueskyDispatcher starting…')
        ws_thread_ready = threading.Event()
        #   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .
        ws_thread = threading.Thread(target=self.__websocket_thread,
                                     kwargs={'ready_signal': ws_thread_ready},
                                     daemon=True,
                                     name="websocket_thread")
        # Regarding above Thread instantiation as a daemon thread:
        # running the thread as a daemon means that the main thread will
        # effectively forget about it once its started (which is how I've
        # been mentally thinking about it anyway) the implications of this
        # are then:
        # a)    the websocket thread will be automatically killed when the main
        #       thread is, this means you need to keep main thread alive for as
        #       long as you wish the websocket thread to be (which we are)
        # b)    You may run into issues if the websocket thread needed to shut
        #       down gracefully, for example it had opened files for writing,
        #       since the main thread will have lost control over it.
        # c)    Most importantly, I don't have to press ctrl-C twice to kill
        #       this script when I fail to have the main thread perform reaping
        #       of the websocket thread.
        #   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .
        ws_thread.start()
        # wait for the websocket thread to get up and running and ready before
        # continuing
        ws_thread_ready.wait()
        # now go ahead and perform the scan

        # Todo: From here on assumptions are made that the other thread
        #  correctly sets things up for us - check we're not exposing ourselves
        #  to race conditions or deadlocks.

        while True:
            self._start_scanning.wait()

            # we don't acquire the self._busy lock here but instead rely on the
            # websocket thread coroutine that called _start_scanning.set() to
            # acquire it on behalf of this code, because the coroutine that
            # called self._start_scanning.set() is guaranteed to run
            # sequentially to a competing coroutine that might try to do the
            # same thing with a different plan, due to the nature of the
            # asyncio event loop. However if left up to this code to acquire the
            # lock, this code runs in a separate thread to the coroutines and
            # so the risk is that multiple coroutines (running in their own
            # thread) both attempt to set the parameters for the next scan and
            # respond to their respective websocket clients with success
            # messages, yet this thread had not executed anything yet and so you
            # have multiple websocket coroutines attempt to initiate plans
            # before this code (which is in a separate thread to the websockets
            # thread) had a chance to acquire the busy lock.

            self._start_scanning.clear()
            scan_func = self._scan_functions[self._selected_scan]
            if self._supplied_params is not None:
                scan_func(
                    self._RE,
                    self.__state_hook,  # Todo: NO state_hook (just testing!)
                    **self._supplied_params)
                # IMPORTANT!
                # We rely on the supplied_params being set by the code that
                # .set() the start_scanning Event BEFORE it .set() the
                # start_scanning Event, (we appropriately reset it afterwards)
                self._supplied_params = None
                # I'm not sure how to detect that if _supplied_params is not
                # None, that it then pertains to the function we are about to
                # call and not a different previous function that was called.
            else:
                # this avoids executing self._selected_scan(…, **None) which
                # raises "TypeError: arg after ** must be a mapping"

                # rely on defaults if no params:
                scan_func(self._RE, self.__state_hook())
                #Todo: don't inject the state_hook function,
                # this is only for testing!

            # if we reset self._selected_scan here I think we might risk having
            # this thread be paused while a websocket thread takes a client that
            # requests to start a scan, and it tries to respond that we are
            # still busy with a current scan, and try to get which scan based on
            # self._selected_scan, but we had just reset it to None
            self._busy.release()
            # if we reset self._selected_scan here AFTER we release the _busy
            # lock, I fear that we could have a scenario where a websocket takes
            # a client that requests to start a scan, and since we have released
            # busy lock, the websocket client assumes it's ok to get a scan
            # started and so it would start by setting up some things including
            # setting the self._selected_scan ... If that happens between the
            # above self._busy.release() and our call here to
            # self._selected_scan = None then we risk resetting the value of
            # _selected_scan when a new scan request was 'coming through the
            # pipeline'. We now risk this execution looping back around to find
            # that we should go through this while loops body again, but when
            # we go to refer to the _selected_scan it will have been reset by
            # us.
            #
            # We don't HAVE to reset the self._selected_scan value if we rely
            # on the websocket thread to appropriately set it before invoking us
            # again, and resetting it here would not remove the reliance on the
            # websocket thread appropriately setting it anyway
            #
            # also we don't have to worry about competing websocket
            # threads from stepping over each other to modify the values of
            # _selected_scan or _supplied_params because they are not running
            # in parallel thanks to asyncio.


    ####    Start of Private methods:


    def __state_hook(self, new_state, old_state):
        """this function will be called from the main thread, by the
        RunEngine code whenever its state changes.
        """
        # https://docs.python.org/3.6/library/queue.html
        self._re_state_changes_q.put(
            {'new_state': new_state, 'old_state': old_state})


    async def __bridge_queue_events_to_coroutines(self,
                                                  loop,
                                                  queue,
                                                  asyncio_event):
        """This function serves to bridge the events between the main threading
        driven thread and the secondary asyncio driven thread by using an
        executor to get around the blocking aspects of waiting on a threading
        Queue primitive and then subsequently echo that item using an
        asyncio.Event() for any awaiting open websocket connection coroutines.

        Using a queue ensures every single RunEngine state update event is
        accounted for and an appropriate message dispatched to any waiting
        subscriber clients.

        It is expected that the queue will remain relatively empty and
        only during very brief moments where the RunEngine changes state in
        quick succession would there be more than one event item in the queue

        The state_hook function, called by the RunEngine whenever its state
        changes, is what adds items to the queue
        """
        while True:
            state_update = await loop.run_in_executor(
                None,
                functools.partial(queue.get, block=True))
            # (this is the only consumer of the queue)
            print('return value from the queue: ')
            print(state_update)
            self._re_state_changes_data = state_update

            asyncio_event.set()
            # at this point any websocket connection coroutines that were
            # shelved out of the event loop awaiting this asyncio_event will be
            # scheduled back into the event loop. and continue execution after
            # their `await event.wait()` line.

            asyncio_event.clear()
            # it's ok to immediately reset the Event, any coroutines that
            # were waiting on it will still be run once this coroutine yields
            # control back to the event loop via an await or completion, it
            # just means that if they hit another line (or the same line) that
            # makes them await it they will again be shelved out of the event
            # loop until it is once again set().

            await self.__yield_control_back_to_event_loop()
            # deliberately pass control back to the event loop so that the
            # coroutines that are now back in the loop can run before we reset
            # the global variable they will be referring to.

            self._re_state_changes_data = None
            queue.task_done()


    async def __yield_control_back_to_event_loop(self):
        await asyncio.sleep(0)
        # https://github.com/python/asyncio/issues/284


    def __websocket_thread(self, ready_signal=None):
        # runs in the other (asyncio driven) thread (not the main thread)
        print("websocket thread: establishing new event loop")
        loop_for_this_thread = asyncio.new_event_loop()
        asyncio.set_event_loop(loop_for_this_thread)

        if ready_signal is not None:
            print("websocket thread: signalling that I'm ready")
            ready_signal.set()

        print("websocket thread: starting websocket control server")
        loop_for_this_thread.run_until_complete(
            websockets.serve(
                self.__websocket_server,
                "0.0.0.0",
                self._websocket_port))

        print("websocket thread: Setting the "
              "websocket state update Event() object")
        self._websocket_state_update = asyncio.Event(loop=loop_for_this_thread)
        print("websocket thread: starting events bridging function")
        asyncio.ensure_future(
            self.__bridge_queue_events_to_coroutines(
                loop_for_this_thread,
                self._re_state_changes_q,
                self._websocket_state_update), loop=loop_for_this_thread)

        print(f'{timestamp()}websocket thread: ready for connections!')

        loop_for_this_thread.run_forever()
        loop_for_this_thread.close()


    async def __websocket_server(self, websocket, path):
        # runs in the other (asyncio driven) thread (not the main thread)
        print("websocket server: client connected to me!")
        print(f'websocket server: runengine state: {self._RE.state}')
        while True:
            # This loop is only effectively infinite if their message
            # contains a 'keep_open' key (see bottom of loop)
            json_msg = await websocket.recv()
            try:
                obj = json.loads(json_msg)
                """
                    valid example obj:
                    
                    start a new plan running:
                    {
                        'type': 'start',
                        'plan': 'simulated',  # <-- this is the scan_name
                        'keep_open': True     # <-- this is optional
                    }

                    ( the presence of a keep_open key is enough, 
                    the value doesn't matter )

                    pause a running plan:
                    {'type': 'pause'}
                    
                    interrogate the current state of the RunEngine:
                    {'type': 'state'}

                    subscribe to a stream of RunEngine state update events
                    (the onus is on the client to close the connection):
                    {'type': 'subscribe'}
                """
            except json.JSONDecodeError:
                print("websocket server: the following received "
                      "message could not be properly decoded as json:")
                print(json_msg)
                await websocket.send(json.dumps({
                    'success': False,
                    'status': "Your message could not be properly decoded, "
                              "is it valid json?"}))
                await websocket.close()
                return None
            # now at this point we can be relatively
            # confident obj is a proper object
            print("websocket server: obj:")
            print(obj)

            if obj['type'] == 'halt':
                # "stop a running plan,
                # don't wait for it to clean up, mark as aborted"
                try:
                    self._RE.halt()
                    # halt() takes no args but may raise
                    # runtime error/transition error, or returns task.result()
                    await websocket.send(json.dumps({
                        'success': True,
                        'status': "halt requested"}))
                except Exception as err:
                    err_repr = repr(err)
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': "exception was raised",
                        'exception': err_repr}))

            elif obj['type'] == 'abort':
                # "stop a running plan, wait for it to cleanup, mark as aborted"
                try:
                    self._RE.abort(reason='Todo: get reason from websocket '
                                          'client')
                    # Todo: get reason from websocket client
                    await websocket.send(json.dumps({
                        'success': True,
                        'status': "abort requested"}))
                except Exception as err:
                    err_repr = repr(err)
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': "exception was raised",
                        'exception': err_repr}))

            elif obj['type'] == 'stop':
                # "stop a running plan, wait for it to clean up, mark as
                # successful"
                try:
                    self._RE.stop()
                    # .stop() takes no args, returns tuple(self._run_start_uids)
                    await websocket.send(json.dumps({
                        'success': True,
                        'status': "stop requested"}))
                except Exception as err:
                    err_repr = repr(err)
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': "exception was raised",
                        'exception': err_repr}))

            elif obj['type'] == 'pause':
                # "if checkpoints have been programmed into the plan, pause on
                # the next checkpoint
                # if no checkpoints, the effect becomes the same as abort
                # this is analogous to pressing Ctrl-C during execution of a
                # plan manually on the terminal"
                try:
                    self._RE.request_pause()
                    await websocket.send(json.dumps({
                        'success': True,
                        'status': "pause requested"}))
                except Exception as err:
                    err_repr = repr(err)
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': "exception was raised",
                        'exception': err_repr}))

            elif obj['type'] == 'resume':
                # resume a paused plan from the last checkpoint
                try:
                    if self._RE.state == 'paused':
                        self._RE.resume()  # takes no args
                        await websocket.send(json.dumps({
                            'success': True,
                            'status': "resume requested"}))
                    else:
                        await websocket.send(json.dumps({
                            'success': False,
                            'status': "cannot resume a runEngine that "
                                      "isn't paused"}))
                except Exception as err:
                    err_repr = repr(err)
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': "exception was raised",
                        'exception': err_repr}))

            elif obj['type'] == 'start':
                if self._busy.locked():
                    # scan is currently underway, don't attempt to start another
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': f'Currently busy with '
                                  f'"{self._selected_scan}" scan'}))
                elif 'plan' not in obj:
                    # if they don't specify which plan then fail:
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': f'You need to provide a "plan" key '
                                  f'specifying which scan you want to start'}))
                elif obj['plan'] not in self._scan_functions:
                    # if we don't have the plan they specified then fail:
                    requested_scan = obj['plan']
                    await websocket.send(json.dumps({
                        'success': False,
                        'status': f'I don\'t recognise any scan function '
                                  f'by the name "{requested_scan}"'}))
                else:
                    response = {  # Get a default response prepared
                        'success': True,
                        'status': "Signalling main thread to start a new scan"}
                    # pull out any supplied parameters:
                    if 'params' in obj:
                        self._supplied_params = obj['params']
                        response['params'] = obj['params']  # update response

                    self._selected_scan = obj['plan']

                    # Pre-emptively set a lock here on behalf of the 'main'
                    # thread to ensure that once we .set() the
                    # self._start_scanning event object the busy flag is
                    # already appropriately set, doing it here ensures that
                    # once we respond to our respective websocket client and
                    # relinquish control back to the event loop, that there
                    # is no chance that a competing websocket coroutine can
                    # come in and attempt to do the same thing before the
                    # 'main' thread had even had a chance to get started yet
                    # (because remember it's a separate thread so the order
                    # of execution between this thread and that is
                    # non-deterministic), the competing websocket coroutine will
                    # already see that the busy flag is set and so not
                    # attempt to modify the class instance variables (such as
                    # self._selected_scan and self._supplied_params,
                    # etc.) while the 'main' thread is starting to get
                    # started on executing the plan.
                    self._busy.acquire()

                    # initiate a scan by setting an event object that the main
                    # thread is waiting on before it proceeds to run whichever
                    # function is referenced now by self._selected_scan and
                    # the corresponding value in self.scan_functions
                    self._start_scanning.set()
                    await websocket.send(json.dumps(response))

            elif obj['type'] == 'state':
                await websocket.send(json.dumps({
                    'type': "status",
                    'about': "current state of the Bluesky RunEngine",
                    'state': self._RE.state
                }))

            elif obj['type'] == "subscribe":
                # if client wants to subscribe to runengine state updates,
                # send them an initial message containing the current state
                await websocket.send(json.dumps({
                    'type': "status",
                    'about': "run engine state updates",
                    'state': self._RE.state
                }))
                while True:
                    # then wait until the state is updated:
                    await self._websocket_state_update.wait()
                    assert self._re_state_changes_data is not None, (
                        "Alex's mental model of asyncio event loop behaviour "
                        "is wrong - prerequisites not met in websocket "
                        "connection that just received asyncio.Event signal "
                        "regarding update to RunEngine state")
                    # then send our client an update:
                    await websocket.send(json.dumps({
                        'type': "status",
                        'about': "run engine state updates",
                        'state': self._re_state_changes_data['new_state'],
                        'old_state': self._re_state_changes_data['old_state']
                    }))

            else:
                await websocket.send(json.dumps({
                    'success': False,
                    'status': "Unsupported message type"}))

            if 'keep_open' not in obj:
                await websocket.close()
                break
            # Todo: handle gracefully when ctrl-C is pressed on this server
            #  if there are any open websocket connections (currently have to
            #  press ctrl-C twice)

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
import logging
import asyncio
import websockets
import json
import time
import functools  # necessary for https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
# see https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio-pass-keywords
import inspect
from queue import Queue

logger = logging.getLogger(__name__)


def timestamp():
    return "[" + time.strftime("%d.%b %Y %H:%M:%S") + "]: "


class ScanNameError(Exception):
    """Raised when:
    - a scan function with a name that is already allocated to a previously
        supplied scan function is attempted to be added
    - a scan function is attempted to be removed that doesn't exist"""
    pass


class BlueskyDispatcher:

    def __init__(self, port=8765, handle_exceptions=False):
        self._RE = RunEngine(context_managers=[])
        # passing empty array as context managers so that the run engine will
        # not try to register signal handlers or complain that it's not the
        # main thread
        self._websocket_port = port

        self._handle_exceptions = handle_exceptions
        # determines whether or not this dispatcher should handle exceptions
        # raised by user supplied scan functions by simply logging the
        # exception and also updating any currently connected websocket
        # subscriber clients. Or if it should re raise the exceptions to the
        # user's calling code.

        self._selected_scan = None
        # acts as a pointer to whichever scan function is to be executed.

        self._supplied_params = None
        # when the selected_scan is called, these will be supplied as long as
        # they are not None

        self._scan_functions = {}
        # The dict of bluesky plan scan functions registered against this
        # dispatcher.
        # key = name of the scan
        # value = a python function matching the required signature

        self._callback_count = 0

        self._callbacks_to_subscribe = []
        # The list of callback functions to be subscribed to the run engine
        # instance (no matter the scan/plan being run),
        # Example value:
        # [
        #   {func: callback_function_1, name: "all"},
        #   {func: callback_function_2, name: "stop"}
        # ]
        # Why?: (the need to maintain a list is to ensure that if in future
        # the run engine instance is discarded and recreated anew after every
        # 'run' that the subsequent instance can be set up with the same
        # subscriptions.)

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
        # state changes OR by this dispatcher if an exception was raised when
        # running a plan.
        #   eg.:
        #   {'exception': False,
        #    'new_state': 'idle',
        #    'old_state': 'running'}
        #   OR
        #   {'exception': True,
        #    'message': 'cannot divide by zero'}
        # Consumed by websocket connections serving 'subscribers'.

        self._websocket_state_update = asyncio.Event()
        # the event that 'wakes up' sleeping websocket subscriber connections
        # so they can consume above re_state_changes_data OR
        # exception data to feed to their respective subscribers

        # register our state_hook function on the RunEngine, it will add updates
        # as items on the _re_state_changes_q Queue where the
        # coroutine_to_bridge_thread_events_to_asyncio function can work through
        # the items to one-by-one notify waiting websocket coroutines through
        # the above asyncio.Event()
        self._RE.state_hook = self.__state_hook
        logger.debug('BlueskyDispatcher initialised.')

    def add_scan(self, scan_function, scan_name):
        if scan_name in self._scan_functions:
            raise ScanNameError(f'The supplied scan name "{scan_name}" is '
                                f'already in use, If you wish to overwrite the '
                                f'previously supplied scan function remove the '
                                f'existing one first with '
                                f'remove_scan("{scan_name}")')
        if self.__good_function_signature(scan_function):
            self._scan_functions[scan_name] = scan_function

    def _get_next_callback_token(self):
        """ function to get the next usable token int value for returning to
        users that call the subscribe_callback_function method to ensure
        always a unique token value, but without using the value returned by
        the runEngine so as to abstract the implementation of the assignment
        of tokens within the run engine, thereby allowing this dispatcher to
        have the freedom to destroy and recreate the runEngine instance. """
        tokenint_to_return = self._callback_count
        # the token is basically just a value that increments whenever a
        # new function is subscribed.
        self._callback_count += 1
        return tokenint_to_return

    def _reapply_callback_functions(self):
        """to be used in the event that the self._RE instance gets recreated,
        so as to ensure the new instance is subscribed to all the same
        callback functions as the previous instance was"""
        for cb in self._callbacks_to_subscribe:
            new_actual_token = self._RE.subscribe(cb["func"], cb["name"])
            # and update the stored actual token (leaving the user held token
            # unchanged):
            cb["actual_token"] = new_actual_token

    def subscribe_callback_function(self, func, name="all"):
        """ subscribe function to mirror the run engine's subscribe function
        which uses the same signature, The purpose of this function is to
        abstract away the access to the run engine, so that the
        dispatcher may have the freedom to recreate the run engine instance
        at any time. The reason for storing the provided callback function in
        the list called _callbacks_to_subscribe is so that in the event that the
        runengine IS recreated, the same callbacks can be applied to it.

        The reason we don't return to the user the actual_token value,
        (but instead one we control) is so that we don't have to depend on the
        returned value from the actual runengine instance being deterministic
        every time this dispatcher may decide to recreate the instance and
        re-subscribe all the callbacks.

        "actual_token" key is to store the value as returned by the LAST and
        most RECENT time THAT callback function was subscribed to THIS
        self._RE instance (so we don't depend on the run engine's
        implementation being deterministic about the assignment of return
        tokenint values)

        "token_int" key is the value we returned to the user and so need to
        remember for when they wish to unsubscribe
        """
        actual_token = self._RE.subscribe(func, name)
        token_to_return = self._get_next_callback_token()
        self._callbacks_to_subscribe.append(
            {
                "func": func,
                "name": name,
                "actual_token": actual_token,
                "user_held_token": token_to_return
            })
        return token_to_return

    def unsubscribe_callback_function(self, user_held_token):
        """ unsubscribes the callback function from the run engine denoted by
        the user_held_token value"""
        # figure out the actual token from the user held token:
        actual_token = None
        for cb in self._callbacks_to_subscribe:
            if cb["user_held_token"] == user_held_token:
                actual_token = cb["actual_token"]
                break
        # unsubscribe the function from the current RE instance:
        if actual_token is None:
            raise LookupError(f"No callback function previously registered "
                              f"with token: {user_held_token}")
        else:
            self._RE.unsubscribe(actual_token)
            # and prevent it being reapplied in the event of RE recreation,
            # amend our _callbacks_to_subscribe list:
            self._callbacks_to_subscribe = [
                entry for entry in self._callbacks_to_subscribe if
                entry["user_held_token"] != user_held_token]

    def remove_scan(self, scan_name):
        if scan_name not in self._scan_functions:
            raise ScanNameError(f'The supplied scan name "{scan_name}" is not '
                                f'in the list of scan functions')
        del self._scan_functions[scan_name]

    def start(self):
        # This code runs in the main thread.
        logger.info('BlueskyDispatcher starting…')
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
            try:
                if self._supplied_params is not None:
                    scan_func(
                        self._RE,
                        self.__state_hook,  # Todo: NO state_hook (just testing!)
                        **self._supplied_params)
                else:
                    # this avoids executing self._selected_scan(…, **None) which
                    # raises "TypeError: arg after ** must be a mapping"
                    scan_func(self._RE, self.__state_hook)

            except Exception as e:
                name_and_shame = (f'supplied plan with name '
                                  f'"{self._selected_scan}" raised '
                                  f'exception')
                logger.exception(name_and_shame)
                # send message to any connected websocket client there was
                # an issue:
                self._re_state_changes_q.put({
                    'exception': True,
                    'message': name_and_shame + '\n' + repr(e)})
            # IMPORTANT!
            # We rely on the supplied_params being set by the code that
            # .set() the start_scanning Event BEFORE it .set() the
            # start_scanning Event, (we appropriately reset it afterwards)
            self._supplied_params = None
            # I'm not sure how to detect that if _supplied_params is not
            # None, that it then pertains to the function we are about to
            # call and not a different previous function that was called.
            # rely on defaults if no params:

            # if we reset self._selected_scan here I think we might risk having
            # this thread be paused while a websocket thread takes a client that
            # requests to start a scan, and it tries to respond that we are
            # still busy with a current scan, and try to get which scan based on
            # self._selected_scan, but we had just reset it to None
            logger.debug("releasing busy lock")
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

    def __good_function_signature(self, function):
        """checks that the supplied function has a signature that matches our
        requirements (first two args are positional, remaining args are named
        and optional"""
        params = inspect.signature(function).parameters
        # params is now an ordered dict
        count = 0
        for i, (key, val) in enumerate(params.items()):
            count += 1
            if i < 2:
                assert val.default is val.empty, "Don't provide default " \
                                                 "values for the first two " \
                                                 "args, the dispatcher will " \
                                                 "supply those."
            else:
                assert val.default is not val.empty, "You need to provide " \
                                                     "sane defaults for your " \
                                                     "plan's parameters"
        assert count > 1, "You need to supply at least 2 positional args for " \
                          "RunEngine and StateHook"
        return True

    def __state_hook(self, new_state, old_state):
        """this function will be called from the main thread, by the
        RunEngine code whenever its state changes.
        """
        # https://docs.python.org/3.6/library/queue.html
        self._re_state_changes_q.put(
            {'new_state': new_state,
             'old_state': old_state,
             'exception': False})

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
            logger.debug(f'return value from the queue: {repr(state_update)}')
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
        logger.debug("websocket thread: establishing new event loop")
        loop_for_this_thread = asyncio.new_event_loop()
        asyncio.set_event_loop(loop_for_this_thread)

        if ready_signal is not None:
            logger.debug("websocket thread: signalling that I'm ready")
            ready_signal.set()

        logger.debug("websocket thread: starting websocket control server")
        loop_for_this_thread.run_until_complete(
            websockets.serve(
                self.__websocket_server,
                "0.0.0.0",
                self._websocket_port))

        logger.debug("websocket thread: Setting the websocket state update "
                     "Event() object")
        self._websocket_state_update = asyncio.Event(loop=loop_for_this_thread)
        logger.debug("websocket thread: starting events bridging function")
        asyncio.ensure_future(
            self.__bridge_queue_events_to_coroutines(
                loop_for_this_thread,
                self._re_state_changes_q,
                self._websocket_state_update), loop=loop_for_this_thread)

        logger.debug("websocket thread: ready for connections!")

        loop_for_this_thread.run_forever()
        loop_for_this_thread.close()

    async def __websocket_server(self, websocket, path):
        # runs in the other (asyncio driven) thread (not the main thread)
        logger.info("websocket server: client connected to me!")
        logger.debug(f'websocket server: runengine state: {self._RE.state}')
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
                logger.warning(f'websocket server: the following received '
                               f'message could not be properly decoded as '
                               f'json: {json_msg}')
                await websocket.send(json.dumps({
                    'success': False,
                    'status': "Your message could not be properly decoded, "
                              "is it valid json?"}))
                await websocket.close()
                return None
            # now at this point we can be relatively
            # confident obj is a proper object
            logger.debug(f'received websocket json message: {repr(obj)}')
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
                    logger.debug("locking busy lock")
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
                    if self._re_state_changes_data['exception']:
                        await websocket.send(json.dumps({
                            'type': "exception",
                            'about': "exception raised during execution of "
                                     "supplied bluesky plan",
                            'message': self._re_state_changes_data['message']
                        }))
                    else:
                        await websocket.send(json.dumps({
                            'type': "status",
                            'about': "run engine state updates",
                            'state': self._re_state_changes_data['new_state'],
                            'old_state': self._re_state_changes_data['old_state']
                        }))
            # client's message doesn't match any of the above, therefore we
            # don't know what they want from us:
            else:
                await websocket.send(json.dumps({
                    'success': False,
                    'status': "Unsupported message type"}))
                # At this point we don't want to keep looping here if their
                # original request is not serviceable.
                await websocket.close()
                break

            if 'keep_open' not in obj:
                await websocket.close()
                break
            # Todo: handle gracefully when ctrl-C is pressed on this server
            #  if there are any open websocket connections (currently have to
            #  press ctrl-C twice)

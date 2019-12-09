"""
This is the bluesky service that gives interactivity via websockets to the
python script that runs a bluesky plan.

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

from devices import RedisSlewScan, CameraDetector

from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from ophyd.sim import det1, det2  # two simulated detectors
from producers import BlueskyKafkaProducer
from bluesky import RunEngine
import threading
import asyncio
import websockets
import json
import time
import os
import functools  # necessary for https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio.loop.run_in_executor
# see https://docs.python.org/3.6/library/asyncio-eventloop.html#asyncio-pass-keywords
from queue import Queue

WEBSOCKET_CONTROL_PORT = os.environ.get('WEBSOCKET_CONTROL_PORT', 8765)
# WEBSOCKET_STATUS_PORT = os.environ.get('WEBSOCKET_STATUS_PORT', 8764)

# global variables:
bp = None  # the global reference to our blueskyplan class object that holds reference to the RunEngine
busy = threading.Lock()  # used by the runengine to signal that its currently busy to the websocket thread
start_scanning = threading.Event()  # used by the websocket thread to signal to the main thread that it should start a scan
re_state_changes_q = Queue()  # used to capture RunEngine state changes so no events, even if in rapid succession, are missed
re_state_changes_data = None  # eg.: {'new_state': 'idle', 'old_state': 'running'}
state_update = threading.Event()  # used by the runengine to signal that its state has changed, for benefit of websocket threads
websocket_state_update = asyncio.Event()  # the asyncio version of the threading version above, see coroutine_to_bridge_thread_events_to_asyncio()

class BlueskyPlan:

    def __init__(self):
        self.RE = RunEngine(context_managers=[])  # Todo: Test if this param means threads are unnecessary?
        # passing empty array as context managers so that the run engine will
        # not try to register signal handlers or complain that its not the
        # main thread
        self.selected_scan = self.do_fake_helical_scan

    def do_fake_helical_scan(self):
        self.RE(count([det1, det2]))
        time.sleep(10)  # because hard to test accompanying threads when this
        # ends in a couple ms due to simulated detectors not simulating much
        print("scan finished ( in do_fake_helical_scan )")

    def do_helical_scan(self,
                        start_y=10,
                        height=10,
                        pitch=2,
                        restful_host='http://camera-server:8000',
                        websocket_url='ws://camera-server:8000/ws'):
        # create signals (aka devices)
        camera = CameraDetector(name='camera',
                                restful_host=restful_host,
                                websocket_url=websocket_url)
        rss = RedisSlewScan(name='slew_scan',
                            start_y=start_y,
                            height=height,
                            pitch=pitch)

        # set up monitors that allow sending real-time data from the
        # slew scan to Kafka
        sd = SupplementalData()
        sd.monitors.append(rss)
        sd.monitors.append(camera)
        self.RE.preprocessors.append(sd)

        # attach Kafka producer. This will make sure Bluesky documents
        # are sent to Kafka
        producer = BlueskyKafkaProducer('kafka:9092')
        self.RE.subscribe(producer.send)

        # run plan
        self.RE(count([rss, camera]))
        print("scan finished ( in do_helical_scan )")


def state_hook_function(new_state, old_state):
    """this function will be called from the main thread, in the
    RunEngine code.
    The waiting coroutine to bridge events will clear() it"""
    # https://docs.python.org/3.6/library/queue.html
    re_state_changes_q.put({'new_state': new_state, 'old_state': old_state})
    # state_update.set()  # this is the threading type of event


async def bridge_queue_events_to_coroutines(loop, queue, asyncio_event):
    """This function serves to bridge the events between the main threading
    driven thread and the secondary asyncio driven thread by using an
    executor to get around the blocking aspects of waiting on a threading
    Queue primitive and then subsequently echo that item using
    an asyncio.Event() for any awaiting open websocket connection coroutines.

    Using a queue ensures every single RunEngine state update event is
    accounted for and an appropriate message dispatched to any waiting
    subscriber clients.

    It is expected that the queue will remain relatively empty and
    only during very brief moments where the RunEngine changes state in quick
    succession would there ever be more than one event item in the queue

    The state_hook function, called by the RunEngine whenever its state
    changes, is what adds items to the queue
    """
    while True:
        ret = await loop.run_in_executor(None, functools.partial(queue.get, block=True))
        # (this is the only consumer of the queue)
        global re_state_changes_data
        print('return value from the queue: ')
        print(ret)
        re_state_changes_data = ret
        asyncio_event.set()
        # at this point the asyncio event loop will pass control to any
        # waiting websocket server coroutines that have subscribers so
        # they can update their subscribers on the latest RunEngine state
        # before passing control back to this, this is why we can do set()
        # immediately followed by clear()
        asyncio_event.clear()
        re_state_changes_data = None
        queue.task_done()


def websocket_thread(ready_signal=None):
    # this is the other thread which uses asyncio synchronization primitives
    print("websocket thread: establishing new event loop")
    loop_for_this_thread = asyncio.new_event_loop()
    asyncio.set_event_loop(loop_for_this_thread)

    bp.RE.state_hook = state_hook_function

    print("websocket thread: signalling that I'm ready")
    if ready_signal is not None:
        ready_signal.set()

    print("websocket thread: starting websocket control server")
    loop_for_this_thread.run_until_complete(
        websockets.serve(
            websocket_server,
            "0.0.0.0",
            WEBSOCKET_CONTROL_PORT))

    print("websocket thread: Setting the websocket state update Event() object")
    global websocket_state_update  # using the global keyword here allows us to
    # update the global instance of this variable, rather than treating the
    # subsequent line as a local function scoped variable
    websocket_state_update = asyncio.Event(loop=loop_for_this_thread)
    print("websocket thread: starting events bridging function")
    asyncio.ensure_future(
        bridge_queue_events_to_coroutines(
            loop_for_this_thread,
            re_state_changes_q,
            websocket_state_update), loop=loop_for_this_thread)

    loop_for_this_thread.run_forever()
    loop_for_this_thread.close()


async def websocket_server(websocket, path):
    # this is in the second thread which uses asyncio synchronization primitives
    print("websocket server: client connected to me!")
    print(f'websocket server: runengine state: {bp.RE.state}')
    print("websocket server: starting 'while true' listen loop")
    while True:  # more like, while their message contains a 'keep_open' key (see bottom of loop)
        json_msg = await websocket.recv()
        try:
            obj = json.loads(json_msg)
            """
                obj should look something like:
    
                {
                    'type': 'start',
                    'plan': 'simulated'
                }
    
                or
    
                {
                    'type': 'start',
                    'plan': 'simulated',
                    'keep_open': True
                }
    
                ( the presence of keep_open is enough, the value doesn't matter )
                ( I'm not yet making use of this keep_open option and 
                        not sure if I need to given the subscribe option )
                or
    
                {
                    'type': 'pause'
                }
    
                or
    
                {
                    'type': 'state'
                }
                
                or for when the client just wishes to subscribe to update events:
    
                {
                    'type': 'subscribe'
                }
            """
        except json.JSONDecodeError:
            obj = None

        if obj is None:
            print("websocket server: the following received "
                  "message could not be properly decoded as json:")
            print(json_msg)
            await websocket.send(json.dumps({
                'success': False,
                'status': "Your message could not be properly decoded, is it valid json?"}))
            await websocket.close()
            return None
        # now at this point we can be relatively
        # confident obj is a proper object
        print("websocket server: obj:")
        print(obj)
        if obj['type'] == 'start':
            if busy.locked():
                # don't attempt to initiate another scan as one is already in
                # progress as evidenced by the busy Lock
                await websocket.send(json.dumps({
                    'success': False,
                    'status': 'Busy with a current scan'}))
            else:
                # if plan was provided then switch the selected plan:
                if obj['plan'] == 'simulated':
                    bp.selected_scan = bp.do_fake_helical_scan
                if obj['plan'] == 'helical scan':
                    bp.selected_scan = bp.do_helical_scan
                # initiate a scan by setting an event object that the main
                # thread is waiting on before proceeding with scan
                start_scanning.set()
                await websocket.send(json.dumps({
                    'success': True,
                    'status': 'Signalling main thread to start a new scan'}))
        elif obj['type'] == 'subscribe':
            # if client wants to subscribe to runengine state updates,
            # send them an initial message containing the current state
            await websocket.send(json.dumps({
                'type': 'status',
                'about': 'run engine state updates',
                'state': bp.RE.state
            }))
            while True:
                # then wait until the state is updated:
                await websocket_state_update.wait()
                assert re_state_changes_data is not None, "Alex's mental model of asyncio event loop behaviour is wrong - prerequisites not met in websocket connection that just received asyncio.Event signal regarding update to RunEngine state"
                # then send our client an update:
                await websocket.send(json.dumps({
                    'type': 'status',
                    'about': 'run engine state updates',
                    'state': re_state_changes_data['new_state'],
                    'old_state': re_state_changes_data['old_state']
                }))
        # Todo: add the condition if they pass type pause or abort to
        #  enact that against the runEngine, then test that that actually
        #  Works.
        else:
            print("websocket server: ignoring that obj, just responding with RE"
                  " state for now")
            await websocket.send(json.dumps({'runenginestate': bp.RE.state}))
        if 'keep_open' not in obj:
            break
            # Todo: handle gracefully when ctrl-C is pressed on this server
            #  if there are any open websocket connections (currently have to
            #  press ctrl-C twice)

if __name__ == "__main__":
    print("main thread: about to do the scan")
    # RE = RunEngine()
    # RE.state_hook = state_hook_function
    # RE.log.setLevel('DEBUG')
    bp = BlueskyPlan()
    ws_thread_ready = threading.Event()
    #   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .
    ws_thread = threading.Thread(target=websocket_thread,
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
    #   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .   .
    ws_thread.start()
    # wait for the websocket thread to get up and running and ready before
    # continuing
    ws_thread_ready.wait()
    # now go ahead and perform the scan
    while True:
        # this is the main thread that uses threading synchronization primitives
        start_scanning.wait()
        busy.acquire()
        start_scanning.clear()
        bp.selected_scan()
        busy.release()

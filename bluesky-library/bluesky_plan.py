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

bp = None
busy = threading.Lock()
start_scanning = threading.Event()

class BlueskyPlan:

    def __init__(self):
        self.RE = RunEngine(context_managers=[])
        # passing empty array as context managers so that the run engine will
        # not try to register signal handlers or complain that its not the
        # main thread
        self.selected_scan = self.do_fake_helical_scan

    def do_fake_helical_scan(self):
        busy.acquire()
        self.RE(count([det1, det2]))
        time.sleep(10)  # because hard to test accompanying threads when this
        # ends in a couple ms due to simulated detectors not simulating much
        print("scan finished ( in do_fake_helical_scan )")
        busy.release()

    def do_helical_scan(self,
                        start_y=10,
                        height=10,
                        pitch=2,
                        restful_host='http://camera-server:8000',
                        websocket_url='ws://camera-server:8000/ws'):
        # create signals (aka devices)
        busy.acquire()
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
        busy.release()


# def state_hook_function(new_state, old_state):
#     print("new_state")
#     print(type(new_state))
#     print(new_state)
#     print(dir(new_state))
#
#     print("old_state")
#     print(type(old_state))
#     print(old_state)
#     print(dir(old_state))


def websocket_thread(ready_signal=None):

    print("websocket thread: establishing new event loop")
    loop_for_this_thread = asyncio.new_event_loop()
    asyncio.set_event_loop(loop_for_this_thread)

    print("websocket thread: signalling that I'm ready")
    if ready_signal is not None:
        ready_signal.set()

    print("websocket thread: starting websocket server")
    loop_for_this_thread.run_until_complete(websockets.serve(websocket_server, "0.0.0.0", 8765))
    loop_for_this_thread.run_forever()
    loop_for_this_thread.close()


async def websocket_server(websocket, path):
    print("websocket server: client connected to me!")
    print(f'websocket server: runengine state: {bp.RE.state}')
    print("websocket server: starting 'while true' listen loop")

    json_msg = await websocket.recv()
    try:
        obj = json.loads(json_msg)
        """
            obj should look something like:

            {
                'type': 'start',
                'plan': 1
            }

            or

            {
                'type': 'pause'
            }

            or

            {
                'type': 'state'
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
            start_scanning.clear()
            await websocket.send(json.dumps({
                'success': True,
                'status': 'Signalling main thread to start a new scan'}))
    else:
        print("websocket server: ignoring that obj, just responding with RE"
              " state for now")
        await websocket.send(json.dumps({'runenginestate': bp.RE.state}))


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
        start_scanning.wait()
        bp.selected_scan()

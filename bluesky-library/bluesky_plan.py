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

bp = None

class BlueskyPlan:

    def __init__(self):
        self.RE = RunEngine(context_managers=[])
        # passing empty array as context managers so that the run engine will
        # not try to register signal handlers or complain that its not the
        # main thread

    def do_helical_scan_in_thread(self):
        threading.Thread(target=self.do_helical_scan(), daemon=False).start()

    def do_helical_scan(self,
                        start_y=10,
                        height=10,
                        pitch=2,
                        restful_host='http://camera-server:8000',
                        websocket_url='ws://camera-server:8000/ws'):
        # create signals (aka devices)
        # camera = CameraDetector(name='camera',
        #                         restful_host=restful_host,
        #                         websocket_url=websocket_url)
        # rss = RedisSlewScan(name='slew_scan',
        #                     start_y=start_y,
        #                     height=height,
        #                     pitch=pitch)
        #
        #
        # # set up monitors that allow sending real-time data from the
        # # slew scan to Kafka
        # sd = SupplementalData()
        # sd.monitors.append(rss)
        # sd.monitors.append(camera)
        # self.RE.preprocessors.append(sd)
        #
        # # attach Kafka producer. This will make sure Bluesky documents
        # # are sent to Kafka
        # producer = BlueskyKafkaProducer('kafka:9092')
        # self.RE.subscribe(producer.send)

        # run plan
        self.RE(count([det1, det2]))
        print("scan finished ( in do_helical_scan )")


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
    print("websocket thread: starting websocket")
    loop_for_this_thread = asyncio.new_event_loop()
    asyncio.set_event_loop(loop_for_this_thread)
    asyncio.ensure_future(websockets.serve(websocket_server, "0.0.0.0", 8765))
    if ready_signal is not None:
        ready_signal.set()


async def websocket_server(websocket, path):
    print(f'websocket server: runengine state: {bp.RE.state}')
    print("websocket server: starting while true listen loop")
    while True:
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
            continue  # do no more and start loop from beginning again
        # now at this point we can be relatively
        # confident obj is a proper object
        print("websocket server: obj:")
        print(obj)
        print(f'websocket server: runengine state: {bp.RE.state}')


if __name__ == "__main__":
    print("main thread: about to do the scan")
    # RE = RunEngine()
    # RE.state_hook = state_hook_function
    # RE.log.setLevel('DEBUG')
    bp = BlueskyPlan()
    ws_thread_ready = threading.Event()
    ws_thread = threading.Thread(target=websocket_thread,
                                 kwargs={'ready_signal': ws_thread_ready},
                                 daemon=False,
                                 name="websocket_thread")
    ws_thread.start()
    # wait for the websocket thread to get up and running and ready before
    # continuing
    ws_thread_ready.wait()
    # now go ahead and perform the scan
    bp.do_helical_scan()

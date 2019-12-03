from devices import RedisSlewScan, CameraDetector

from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from ophyd.sim import det1, det2  # two simulated detectors
from producers import BlueskyKafkaProducer
from bluesky import RunEngine
import threading


class BlueskyPlan:

    def __init__(self):
        self.RE = RunEngine()

    def do_helical_scan_in_thread(self):
        threading.Thread(target=self.do_helical_scan(), daemon=False).start()

    def do_helical_scan(self, start_y=10, height=10, pitch=2, restful_host='http://camera-server:8000', websocket_url='ws://camera-server:8000/ws'):
        # create signals (aka devices)
        camera = CameraDetector(name='camera', restful_host=restful_host, websocket_url=websocket_url)
        rss = RedisSlewScan(name='slew_scan', start_y=start_y, height=height, pitch=pitch)


        # set up monitors that allow sending real-time data from the slew scan to Kafka
        sd = SupplementalData()
        sd.monitors.append(rss)
        sd.monitors.append(camera)
        self.RE.preprocessors.append(sd)

        # attach Kafka producer. This will make sure Bluesky documents are sent to Kafka
        producer = BlueskyKafkaProducer('kafka:9092')
        self.RE.subscribe(producer.send)
        # run plan
        self.RE(count([det1, det2]))
        print("scan finished (in do_scan)")


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


if __name__ == "__main__":
    print("about to do the scan")
    # RE = RunEngine()
    # RE.state_hook = state_hook_function
    # RE.log.setLevel('DEBUG')
    bp = BlueskyPlan()
    bp.do_helical_scan_in_thread()
    print("scan finished (in __main__)")
    print("################ attempt to see if any threads in bluesky runengine??")
    for thread in threading.enumerate():
        print((thread._target))
    print("################")
    print("print(threading.enumerate())")
    print(threading.enumerate())

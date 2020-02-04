# Bluesky Dispatcher

## About

This bluesky dispatcher wraps your bluesky plan in websocket functionality to
allow you to invoke actions and interrogate state on the bluesky run engine
programmatically via websockets (previously this was usually accomplished by
manually interacting with the run engine at the python REPL terminal)

## How to use

1. Write your bluesky plan that executes your scan.
1. Refactor your plan into a callable function.
1. Amend the function's arguments so that the first argument is the RunEngine
instance and the second argument is the StateHook function
1. Refactor your references to the Run Engine to use the instance provided as
the first parameter
1. Import this bluesky dispatcher.
1. Instantiate it.
1. Pass it your function along with a name.
1. Call its start method.

### Example

#### Write your bluesky plan to execute your scan

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData

# set up redis slew scan device
ss = RedisSlewScan(name = 'slew_scan', start_y = 50, height=100, pitch = 20)

# set up monitors
sd = SupplementalData()
sd.monitors.append(ss)      # set callback onto slew scan object

# set up run engine
RE = RunEngine()
RE.subscribe(print)
# can subscribe to best effort callback or kafka producer
RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
RE(count([ss]))
```

#### Refactor your plan into a callable function

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData

def run_scan(name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    RE = RunEngine()
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    run_scan()
```

#### Amend the function's arguments so that the first argument is the RunEngine instance and the second argument is the StateHook function

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData

def run_scan(RE, hook_func, name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    RE = RunEngine()
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    run_scan()
```

#### Refactor your references to the Run Engine to use the instance provided as the first parameter

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData

def run_scan(RE, hook_func, name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    # RE = RunEngine()  ## <- delete this line, get from param 1 instead
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    run_scan()
```

#### Import this bluesky dispatcher.

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from bluesky-library import bluesky_dispatcher

def run_scan(RE, hook_func, name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    # RE = RunEngine()  ## <- delete this line, get from param 1 instead
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    run_scan()
```

#### Instantiate it.

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from bluesky-library import bluesky_dispatcher

def run_scan(RE, hook_func, name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    # RE = RunEngine()  ## <- delete this line, get from param 1 instead
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
    # the port (8765) is the websocket port the dispatcher will be accessible by
    run_scan()
```

#### Pass it your function along with a name.


```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from bluesky-library import bluesky_dispatcher

def run_scan(RE, hook_func, name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    # RE = RunEngine()  ## <- delete this line, get from param 1 instead
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
    # the port (8765) is the websocket port the dispatcher will be accessible by
    bd.add_scan(run_scan, 'slew_scan')
    run_scan()
```

#### Call its start method.

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from bluesky-library import bluesky_dispatcher

def run_scan(RE, hook_func, name='slew_scan', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    # RE = RunEngine()  ## <- delete this line, get from param 1 instead
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
    # the port (8765) is the websocket port the dispatcher will be accessible by
    bd.add_scan(run_scan, 'slew_scan')
    bd.start()
    # run_scan()
```

Now from a websocket client of your choice connect to the dispatchers websocket
server and send a start message to have your scan start.
Below is a very basic example.

```python
# simple standalone python script example invoking a scan via bluesky dispatcher websocket
import websockets
import json
uri = "ws://localhost:8765"
try:
    with websockets.connect(uri) as websocket:

        plan = "slew_scan"  # this corresponds with expected label on
        payload = {
            "type": "start",
            "plan": plan,
            "params": {
                "name": "slew_scan",
                "start_y": 50,
                "height": 100,
                "pitch": 20
            }
        }
        websocket.send(json.dumps(payload))
        response = websocket.recv()
        print(f'websocket client got this response: {response}')
        websocket.close(reason="that's enough testing for now")
except ConnectionResetError:
    print('The websocket connection was closed by the other end abruptly')
except ConnectionError as e:
    # covers ConnectionRefusedError & ConnectionAbortedError
    print(f'I was unable to connect to the websocket {uri}')
    print(str(e))
```


## History

This repository was started by cherry picking commits from the Australian
Synchrotron's bright-sac-2019 repository.

The bright-sac-2019 repository was for the helical scan demonstration to
showcase the technology stack that would be used on the Synchrotron's
new upcoming beamlines.

BRIGHT: the name of the huge infrastructure project to deliver the
additional beamlines.

SAC: Science Advisory Committee, the group of subject matter experts
recruited to advise the Synchrotron on its BRIGHT developments.

As the work on the helical scan demo progressed, it became evident that
the work being done should be worked on to be easily reused by future
projects. This repository is therefore the extraction of the bluesky
dispatcher component used by and developed by the helical scan project.


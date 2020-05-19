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
ss = RedisSlewScan(name = 'slew_scan_demo', start_y = 50, height=100, pitch = 20)

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

Be sure to include sane defaults for your parameters as the dispatcher does not
perform checking that supplied parameters in a websocket message to request the
start of a scan have all been supplied appropriately.

*todo: the dispatcher should not die due to a badly supplied scan function*
*refactor it to be more robust with its assumptions*

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData

def run_scan(name='slew_scan_demo', start_y=50, height=100, pitch=20):
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

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
#------------^^--^^^^^^^^^------------------------------------------------------
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

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    # RE = RunEngine()  ## <- delete this line, get from param 1 instead
#---^^^^^^^^^^^^^^^^^^----------------------------------------------------------
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
#^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^----------------------------------

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
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

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
#---^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^------------------------------------------
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

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
    bd.add_scan(run_scan, 'slew_scan')
#---^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^------------------------------------------
    run_scan()
```

#### Pass it a callback function you want subscribed to the run engine.

If you wish to provide a callback function that should be subscribed to the run
engine instance and **affect all scans** you have added (the above snippet only
added the one, but we could add multiple) then you can optionally provide the
dispatcher instance with a callback function that you wish the run engine
instance be subscribed to before it's even passed to any of your scan functions
as the first parameter.

The dispatcher will now use the provided callbacks for **all** plans that it
runs.

If we don't want that behaviour because we want to use a different callback
function for a different scan, then we should subscribe the callback
function *within* the scan/plan function and backwork with the run engine
instance we get passed (as the first parameter to our scan function).


```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from bluesky-library import bluesky_dispatcher

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
    bd.add_scan(run_scan, 'slew_scan')
#-------------------------------------------------------------------------------
    from bluesky.callbacks.best_effort import BestEffortCallback
    bec = BestEffortCallback()
    bec_token_to_unsubscribe = bd.subscribe_callback_function(bec)
    # bec_token_to_unsubscribe is necessary if you want to later unsubscribe.
#---^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    run_scan()
```

#### Call its start method.

```python
from devices import RedisSlewScan
from bluesky import RunEngine
from bluesky.plans import count
from bluesky.preprocessors import SupplementalData
from bluesky-library import bluesky_dispatcher

def run_scan(RE, hook_func, name='slew_scan_demo', start_y=50, height=100, pitch=20):
    # set up redis slew scan device
    ss = RedisSlewScan(name, start_y, height, pitch)
    
    # set up monitors
    sd = SupplementalData()
    sd.monitors.append(ss)      # set callback onto slew scan object
    
    # set up run engine
    RE.subscribe(print)
    # can subscribe to best effort callback or kafka producer
    RE.preprocessors.append(sd) # adding sd monitor to sd run engine callbacks
    RE(count([ss]))

if __name__ is '__main__':
    bd = bluesky_dispatcher(port=8765)
    bd.add_scan(run_scan, 'slew_scan')
    bd.start()
#---^^^^^^^^^^------------------------------------------------------------------
    # run_scan()  <--- this line is no longer needed, the dispatcher will
    # effectively make this call, when an appropriate websocket message is sent
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

        plan = "slew_scan"  # corresponds to bd.add_scan(run_scan, 'slew_scan')
        payload = {
            "type": "start",
            "plan": plan,
            "params": {
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

### Websocket interface

As you have seen in the above example, part of the websocket message is the
'type'. The different *types* of websocket message that you can send are listed
below.

type **'start'**:

| keys | required? | description |
|---------|-----------|-------------|
|plan | yes | the name provided with the function when it was added to the dispatcher|
|params| no | parameters to pass to the scan function when its called to overwrite its defaults|

example sent message:

```
json.dumps({
    "type": "start",
    "plan": "slew-scan",
    "params": {
        "start_y": 50,
        "height": 100
    }
})
```

example received success response:

```
{
    "success": True,
    "status": "Signalling main thread to start a new scan",
    "params": {
        "start_y": 50,
        "height": 100
    }
}
```

example received failure responses:

when the dispatcher is already running a scan:

```
{
    "success": False,
    "status": "Currently busy with \"slew_scan\" scan"
}
```

when a required param wasn't supplied:

```
{
    "success": False,
    "status": "You need to provide a \"plan\" key specifying which scan you want to start"
}
```

when the requested scan is not known:

```
{
    "success": False,
    "status": "I don\'t recognise any scan function by the name \"slew_scan\""
}
```

type **'halt'**:

For when you want to stop a running plan, don't wait for it to run cleanup, and
have the run be marked as aborted.
 
*no other keys*

example sent message:

```
json.dumps({
    "type": "halt"
})
```

example received success response:

```
{
    "success": True,
    "status": "halt requested"
}
```

example received failure response:

```
{
    "success": False,
    "status": "exception was raised",
    "exception": "…"
}
```

type **'abort'**:

For when you want to stop a running plan, wait for it to run cleanup, and have
the run be marked as aborted.

| keys | required? | description |
|---------|-----------|-------------|
|reason | no | the reason to be logged against the results of the scan indicating why it was aborted|

example sent message:

```
json.dumps({
    "type": "abort",
    "reason": "sample mount failed midway through scanning"
})
```

example received success response:

```
{
    "success": True,
    "status": "abort requested"
}
```

example received failure response:

```
{
    "success": False,
    "status": "exception was raised",
    "exception": "…"
}
```

type **'stop'**:

For when you want to stop a running plan, wait for it to run clean up, and have
the run be marked as successful.

*no other keys*

example sent message:

```
json.dumps({
    "type": "stop"
})
```

example received success response:

```
{
    "success": True,
    "status": "stop requested"
}
```

example received failure response:

```
{
    "success": False,
    "status": "exception was raised",
    "exception": "…"
}
```

type **'pause'**:

For when you want to pause a running scan.

*no other keys*

example sent message:

```
json.dumps({
    "type": "pause"
})
```

example received success response:

```
{
    "success": True,
    "status": "pause requested"
}
```

example received failure response:

```
{
    "success": False,
    "status": "exception was raised",
    "exception": "…"
}
```

type **'resume'**:

For when you want to resume a paused scan.

*no other keys*

example sent message:

```
json.dumps({
    "type": "resume"
})
```

example received success response:

```
{
    "success": True,
    "status": "resume requested"
}
```

example received failure responses:

when the run engine isn't in a paused state:
```
{
    "success": False,
    "status": "cannot resume a runEngine that isn\'t paused"
}
```

```
{
    "success": False,
    "status": "exception was raised",
    "exception": "…"
}
```

type **'state'**:

For when you want to probe the current state of the Bluesky run engine.

*no other keys*

example sent message:

```
json.dumps({
    "type": "state"
})
```

example received success response:

```
{
    "type": "status",
    "about": "current state of the Bluesky RunEngine",
    "state": "idle"
}
```

type **'subscribe'**:

For when you want to subscribe to a constant stream of updates whenever the
run engine's state changes, so as to know the 'busy' status of the dispatcher.

*note that this subscribe is not the same as the bluesky run engine's method
also called subscribe*

*no other keys*

example sent message:

```
json.dumps({
    "type": "subscribe"
})
```

example received success response:

```
{
    "type": "status",
    "about": "run engine state updates",
    "state": "idle"
}
```

*connection is then maintained and client will continue to receive state
messages whenever an update occurs*


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

## Developer instructions

For instructions on how to get up and running developing this project, have a
look at the [README accompanying the examples](examples/README.md)
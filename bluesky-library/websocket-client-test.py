#!/usr/bin/env python

# WS client example
# https://websockets.readthedocs.io/en/stable/intro.html#synchronization-example

import asyncio
import websockets
import json

use_real_helical_scan_plan_make_hardware_move = False
# false means use simulated detectors in a fake plan instead


async def test_starting_plan():
    uri = "ws://localhost:8765"
    try:
        async with websockets.connect(uri) as websocket:

            plan = "simulated"  # this corresponds with expected label on
            # websocket server in bluesky_plan.py
            if use_real_helical_scan_plan_make_hardware_move:
                plan = "helical scan"  # this corresponds with expected label
                # on websocket server in bluesky_plan.py

            # payload = {"type": "start", "plan": plan}
            payload = {
                "type": "start",
                "plan": plan,
                "params": {"example_param_1": 3, "example_param_2": 4}}
            await websocket.send(json.dumps(payload))
            response = await websocket.recv()
            print(f'I\'m the websocket client and I got this ' +
                  'response: {response}')
            await websocket.close(reason="thats enough testing for now")
    except ConnectionResetError:
        print('The websocket connection was closed by the other end abruptly')
    except ConnectionError as e:
        # covers ConnectionRefusedError & ConnectionAbortedError
        print(f'I was unable to connect to the websocket {uri}')
        print(str(e))


async def test_subscribing_to_updates():
    uri = "ws://localhost:8765"
    try:
        async with websockets.connect(uri) as websocket:
            payload = {"type": "subscribe"}
            await websocket.send(json.dumps(payload))
            while True:
                response = await websocket.recv()
                print('I\'m the websocket subscriber and I got this ' +
                      f'response: {response}')
    except ConnectionResetError:
        print('The websocket connection was closed by the other end abruptly')
    except ConnectionError as e:
        # covers ConnectionRefusedError & ConnectionAbortedError
        print(f'I was unable to connect to the websocket {uri}')
        print(str(e))

asyncio.get_event_loop().run_until_complete(test_starting_plan())

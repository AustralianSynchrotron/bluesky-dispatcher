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
    async with websockets.connect(uri) as websocket:

        plan = "simulated"  # this corresponds with expected label on websocket server in bluesky_plan.py
        if use_real_helical_scan_plan_make_hardware_move:
            plan = "helical scan"  # this corresponds with expected label on websocket server in bluesky_plan.py

        payload = {"type": "start", "plan": plan}
        await websocket.send(json.dumps(payload))
        response = await websocket.recv()
        print(f'I\'m the websocket client and I got this response: {response}')
        await websocket.close(reason="thats enough testing for now")


async def test_subscribing_to_updates():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        payload = {"type": "subscribe"}
        await websocket.send(json.dumps(payload))
        while True:
            response = await websocket.recv()
            print(f'I\'m the websocket subscriber and I got this response: {response}')

asyncio.get_event_loop().run_until_complete(test_subscribing_to_updates())

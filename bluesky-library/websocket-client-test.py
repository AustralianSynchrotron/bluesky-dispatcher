#!/usr/bin/env python

# WS client example
# https://websockets.readthedocs.io/en/stable/intro.html#synchronization-example

import asyncio
import websockets
import json

async def hello():
    uri = "ws://localhost:8765"
    async with websockets.connect(uri) as websocket:
        payload = {"type": "start", "hello": "there"}
        await websocket.send(json.dumps(payload))
        response = await websocket.recv()
        print(f'I\'m the websocket client and I got this response: {response}')
        websocket.close(reason="had enough")
        # current_game_data = json.loads(current_game_data_jsonified)
        # print("#################################")
        # print("current game data so far:")
        # print("#################################")
        # print(current_game_data)
        #
        # print("#################################")
        # print("updates from the server:")
        # print("#################################")
        # while True:
        #     update = await websocket.recv()
        #     print(update)
        # name = input("What's your name? ")
        #
        # await websocket.send(name)
        # print(f"> {name}")
        #
        # print(f"< {greeting}")
        #
        # first_xlist = await websocket.recv()
        # print(f"< {first_xlist}")

asyncio.get_event_loop().run_until_complete(hello())
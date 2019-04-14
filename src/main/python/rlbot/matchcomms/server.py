from contextlib import contextmanager, closing
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue, Empty  # TODO(python 3.7+): use SimpleQueue
from typing import Iterator, Dict, Any, Tuple, Set
import websockets
from websockets.server import WebSocketServerProtocol, WebSocketServer
import json
from threading import Thread
import socket
import asyncio

from rlbot.utils.logging_utils import get_logger
from rlbot.matchcomms.shared import MatchcommsPaths, JSON


@dataclass
class MatchcommsServerThread:
    uri: str  # how to connect to the server
    _server: WebSocketServer
    _event_loop: asyncio.AbstractEventLoop
    _thread: Thread

    def close(self, timeout=1):
        self._event_loop.call_soon_threadsafe(self._event_loop.stop)
        self._thread.join(1)
        assert not self._thread.is_alive()

@dataclass
class MatchcommsServer:
    users: Set[WebSocketServerProtocol] = field(default_factory=set) # TODO

    async def handle_connection(self, websocket: WebSocketServerProtocol, path: str):
        assert path == MatchcommsPaths.BROADCAST  # TODO consider using other channels
        self.users.add(websocket)
        try:
            async for message in websocket:
                asyncio.wait([
                    user.send(message)
                    for user in self.users if user != websocket
                ])
        finally:
            self.users.remove(websocket)


def find_free_port() -> int:
    # https://stackoverflow.com/a/45690594
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

def launch_matchcomms_server() -> MatchcommsServerThread:
    """
    Launches a background process that handles match communications.
    """
    host = 'localhost'
    port = find_free_port()  # deliberately not using a fixed port to prevent hardcoding fragility.

    event_loop = asyncio.new_event_loop()
    server = MatchcommsServer()
    start_server = websockets.serve(server.handle_connection, host, port, loop=event_loop)
    server = event_loop.run_until_complete(start_server)
    thread = Thread(target=event_loop.run_forever, daemon=True)
    thread.start()
    return MatchcommsServerThread(
        uri=f'ws://{host}:{port}',
        _server=server,
        _event_loop=event_loop,
        _thread=thread,
    )


def self_test():
    server = launch_matchcomms_server()
    from rlbot.matchcomms.client import MatchcommsClient
    com1 = MatchcommsClient(server.uri)
    com2 = MatchcommsClient(server.uri)
    com1.outgoing_broadcast.put({'hi': 'there'})
    try:
        print('<', com2.incoming_broadcast.get(timeout=0.5))
    except Empty as e:
        print('Did not get stuff from the queue.')
    com1.close()
    com2.close()
    server.close()

if __name__ == '__main__':
    self_test()
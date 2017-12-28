import unittest
import arbit_ccxt
import requests_mock
# from influxdb import DataFrameClient
import asyncio
import socketio
from unittest import mock
from copy import copy
from functools import partial
import importlib
import interfaces.hitbtc2
from websockets.test_client_server import with_client, with_server, temp_test_client, temp_test_server
import contextlib
from websockets.client import *
from websockets.server import *
import random
import socket

mock_time = mock.Mock()
mock_time.return_value = 7

def AsyncMock(*args, **kwargs):
    """Return a mock asynchronous function."""
    m = mock.MagicMock(*args, **kwargs)

    @asyncio.coroutine
    def mock_coro(*args, **kwargs):
        return m(*args, **kwargs)

    mock_coro.mock = m
    return mock_coro

current_time = 7


class TestStringMethods(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        start = 0
        self.arbitrage_stats = {
            'ETH/BTC': {
                'spread_history': [
                    [0, 1],
                    [1, 1.5],
                    [4, 2],
                    [6, 3],
                ],
                'updated': start,
                'arbitrage': {
                    'lowestAskExchange': 'poloniex',
                    'highestBidExchange': 'hitbtc',
                },
                'time_found': start,
            }
        }

        arbit_ccxt.last_exchange_update = {
            'poloniex': 7,
            'hitbtc': 7
        }

        mgr = mock.MagicMock()
        mgr.emit = AsyncMock()
        mgr.close_room = AsyncMock()
        mgr.trigger_callback = AsyncMock()
        # self.current_time = 7
        arbit_ccxt.time = self.time_mock
        arbit_ccxt.sio = socketio.AsyncServer(client_manager=mgr)

    def reload(self):
        importlib.reload(arbit_ccxt)
        self.setUpClass()

    def time_mock():
        global current_time
        return current_time

    @unittest.mock.patch('socketio.server.engineio.AsyncServer')
    def test_save_to_influx_at_arbitrage_liquidate(self, eio):
        # should add to arbitrage_history if longer than 50 secs
        # should cut history if more than 100 records
        # should delete pair from arbitrage_stats
        # should save to influx with:

        """Test write points from df in TestDataFrameClient object."""
        expected = (
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.0 0\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.5 1000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.5 2000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.5 3000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=2.0 4000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=2.0 5000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=3.0 6000000000\n"
        )

        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            # XXX: it store real records in influx

            arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
            loop = asyncio.get_event_loop()
            arbit_ccxt.loop = loop
            loop.run_until_complete(arbit_ccxt.arbitrage_liquidate(arbit_ccxt.arbitrage_stats['ETH/BTC'], 'ETH/BTC'))

            self.assertEqual(m.last_request.body, expected)

    @unittest.mock.patch('socketio.server.engineio.AsyncServer')
    def test_save_average_spread_to_history(self, eio):
        global current_time
        current_time = 60

        self.reload()

        arbit_ccxt.last_exchange_update = {
            'poloniex': 60,
            'hitbtc': 60
        }

        self.arbitrage_stats = {
            'ETH/BTC': {
                'spread_history': [
                    [0, 2],
                ],
                'updated': 0,
                'arbitrage': {
                    'lowestAskExchange': 'poloniex',
                    'highestBidExchange': 'hitbtc',
                },
                'time_found': 0,
            }
        }

        arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
        loop = asyncio.get_event_loop()
        arbit_ccxt.loop = loop
        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            loop.run_until_complete(arbit_ccxt.arbitrage_liquidate(arbit_ccxt.arbitrage_stats['ETH/BTC'], 'ETH/BTC'))

        # print(arbit_ccxt.arbitrage_history)
        self.assertEqual(arbit_ccxt.arbitrage_history[-1]['average_spread'], 2)

    async def liquidate_without_delay(self):
        await asyncio.sleep(0.1)
        arbit_ccxt.arbitrage_liquidate = self.original_arbitrage_liquidate
        await arbit_ccxt.calculate_arbitrage2('ETH/BTC')

    async def liquidate_with_delay(self):
        self.original_arbitrage_liquidate = arbit_ccxt.arbitrage_liquidate
        arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
        arbit_ccxt.arbitrage_liquidate = partial(self.arbitrage_liquidate_with_delay, 0.2)
        await arbit_ccxt.calculate_arbitrage2('ETH/BTC')

    async def return_true(pair, first, second):
        return False

    async def arbitrage_liquidate_with_delay(self, delay, stats, pair):
        await asyncio.sleep(delay)
        await arbit_ccxt.arbitrage_liquidate(stats, pair)

    @unittest.mock.patch('socketio.server.engineio.AsyncServer')
    def test_pair_should_not_deleted_within_influx(self, eio):
        # can happen when another spread appears and dissapears fast while in process of liquidation
        arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
        # spread 0%
        arbit_ccxt.lowestAskPair = {'ETH/BTC': [0.05, 'poloniex']}
        arbit_ccxt.highestBidPair = {'ETH/BTC': [0.05, 'hitbtc']}
        arbit_ccxt.exchange_pair_updated = {'ETH/BTC': {'poloniex': 0, 'hitbtc': 0}}
        arbit_ccxt.check_wallets = self.return_true

        loop = asyncio.get_event_loop()
        arbit_ccxt.loop = loop
        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)
            m.register_uri(requests_mock.GET,
                           "http://localhost:8086/query?q=select+mean%28spread%29%2C+count%28spread%29+from+spreads+where+time+%3E+now%28%29+-+24h+group+by+pair&db=arbit",
                           status_code=200)

            try:
                loop.run_until_complete(asyncio.gather(
                    self.liquidate_with_delay(),
                    self.liquidate_without_delay()
                ))
            except KeyError:
                self.fail("KeyError exception raised")

    @unittest.mock.patch('socketio.server.engineio.AsyncServer')
    def test_save_spread_within_second_before_liquidate(self, eio):
        global current_time
        start = 0
        current_time = 3
        self.reload()
        self.arbitrage_stats = {
            'ETH/BTC': {
                'spread_history': [
                    [0, 1],
                ],
                'updated': start,
                'arbitrage': {
                    'lowestAskExchange': 'poloniex',
                    'highestBidExchange': 'hitbtc',
                },
                'time_found': start,
            }
        }

        arbit_ccxt.last_exchange_update = {
            'poloniex': 3,
            'hitbtc': 3
        }


        expected = (
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.0 0\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.0 1000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex,pair=ETH/BTC spread=1.0 2000000000\n"
        )

        arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
        loop = asyncio.get_event_loop()
        arbit_ccxt.loop = loop
        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            loop.run_until_complete(arbit_ccxt.arbitrage_liquidate(arbit_ccxt.arbitrage_stats['ETH/BTC'], 'ETH/BTC'))
            self.assertEqual(m.last_request.body, expected)

    async def hitbtc_loop(self):
        ex = interfaces.hitbtc2()
        async for (exchange_id, orderbook, updated_pair) in ex.websocket_run(['ETH/BTC']):
            print(orderbook)

    @unittest.skip("later")
    def test_hitbtc_recovery(self):
        self.reload()
        loop = asyncio.get_event_loop()
        arbit_ccxt.loop = loop

        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            loop.run_until_complete(arbit_ccxt.main_websocket('hitbtc2', ['ETH/BTC']))
            #self.assertEqual(m.last_request.body, expected)

    def test_poloniex_recovery(self):
        pass

    def test_bittrex_recovery(self):
        pass

    @unittest.mock.patch('socketio.server.engineio.AsyncServer')
    def test_do_not_save_history_if_exchange_data_is_old(self, eio):
        global current_time
        current_time = 60
        self.reload()

        arbit_ccxt.last_exchange_update = {'poloniex': 0, 'hitbtc': 0}
        arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)

        loop = asyncio.get_event_loop()
        arbit_ccxt.loop = loop

        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            loop.run_until_complete(arbit_ccxt.arbitrage_liquidate(arbit_ccxt.arbitrage_stats['ETH/BTC'], 'ETH/BTC'))
            self.assertEqual(m.last_request, None)

            self.assertEqual(len(arbit_ccxt.arbitrage_history), 0)
        pass

@asyncio.coroutine
def handler(ws, path):
    raise
    if path == '/attributes':
        yield from ws.send(repr((ws.host, ws.port, ws.secure)))
    elif path == '/path':
        yield from ws.send(str(ws.path))
    elif path == '/headers':
        yield from ws.send(str(ws.request_headers))
        yield from ws.send(str(ws.response_headers))
    elif path == '/raw_headers':
        yield from ws.send(repr(ws.raw_request_headers))
        yield from ws.send(repr(ws.raw_response_headers))
    elif path == '/extensions':
        yield from ws.send(repr(ws.extensions))
    elif path == '/subprotocol':
        yield from ws.send(repr(ws.subprotocol))
    else:
        yield from ws.send((yield from ws.recv()))


def get_server_uri(server, secure=False, resource_name='/'):
    """
    Return a WebSocket URI for connecting to the given server.
    """
    proto = 'wss' if secure else 'ws'

    # Pick a random socket in order to test both IPv4 and IPv6 on systems
    # where both are available. Randomizing tests is usually a bad idea. If
    # needed, either use the first socket, or test separately IPv4 and IPv6.
    server_socket = random.choice(server.sockets)

    # That case
    if server_socket.family == socket.AF_INET6:             # pragma: no cover
        host, port = server_socket.getsockname()[:2]
        host = '[{}]'.format(host)
    elif server_socket.family == socket.AF_INET:
        host, port = server_socket.getsockname()
    elif server_socket.family == socket.AF_UNIX:
        # The host and port are ignored when connecting to a Unix socket.
        host, port = 'localhost', 0
    else:                                                   # pragma: no cover
        raise ValueError("Expected an IPv6, IPv4, or Unix socket")

    return '{}://{}:{}{}'.format(proto, host, port, resource_name)

class InterfacesTests(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.loop = asyncio.get_event_loop()

    def start_server(self, **kwds):
        # Don't enable compression by default in tests.
        kwds.setdefault('compression', None)
        start_server = serve(handler, 'localhost', 0, **kwds)
        self.server = self.loop.run_until_complete(start_server)

    def start_client(self, resource_name='/', **kwds):
        # Don't enable compression by default in tests.
        kwds.setdefault('compression', None)
        secure = kwds.get('ssl') is not None
        server_uri = get_server_uri(self.server, secure, resource_name)
        start_client = connect(server_uri, **kwds)
        self.client = start_client

    def stop_client(self):
        pass
        # try:
        #     self.loop.run_until_complete(
        #         asyncio.wait_for(self.client.close_connection_task, timeout=1))
        # except asyncio.TimeoutError:                # pragma: no cover
        #     self.fail("Client failed to stop")

    def stop_server(self):
        self.server.close()
        try:
            self.loop.run_until_complete(
                asyncio.wait_for(self.server.wait_closed(), timeout=1))
        except asyncio.TimeoutError:                # pragma: no cover
            self.fail("Server failed to stop")

    @contextlib.contextmanager
    def temp_server(self, **kwds):
        with temp_test_server(self, **kwds):
            yield

    @contextlib.contextmanager
    def temp_client(self, *args, **kwds):
        with temp_test_client(self, *args, **kwds):
            yield

    @with_server()
    @with_client()
    def test_websocket(self):
        self.loop = asyncio.get_event_loop()
        # with self.temp_server(loop=self.loop):
        #     with self.temp_client(loop=self.loop):
        #self.loop.run_until_complete(self.client.send("Hello!"))
        print(arbit_ccxt.interfaces.hitbtc2.ws_client)
        arbit_ccxt.interfaces.hitbtc2.ws_client = self.client
        #ex = interfaces.hitbtc2()
        self.loop.run_until_complete(arbit_ccxt.main_websocket('hitbtc2', ['ETH/BTC']))
        #self.assertEqual(reply, "Hello!")


if __name__ == '__main__':
    unittest.main()

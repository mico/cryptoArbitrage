import unittest
import arbit_ccxt
import requests_mock
# from influxdb import DataFrameClient
import asyncio
import socketio
from unittest import mock


def AsyncMock(*args, **kwargs):
    """Return a mock asynchronous function."""
    m = mock.MagicMock(*args, **kwargs)

    @asyncio.coroutine
    def mock_coro(*args, **kwargs):
        return m(*args, **kwargs)

    mock_coro.mock = m
    return mock_coro


@unittest.mock.patch('socketio.server.engineio.AsyncServer')
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
                ],
                'updated': start,
                'arbitrage': {
                    'lowestAskExchange': 'poloniex',
                    'highestBidExchange': 'hitbtc',
                },
                'time_found': start,
            }
        }
        self.expected_spread_data = [
            [start * 1000000000, 1],
            [(start+1) * 1000000000, 1.5],
            [(start+2) * 1000000000, 1.5],
            [(start+3) * 1000000000, 1.5],
            [(start+4) * 1000000000, 2]
        ]

        mgr = mock.MagicMock()
        mgr.emit = AsyncMock()
        mgr.close_room = AsyncMock()
        mgr.trigger_callback = AsyncMock()

        arbit_ccxt.sio = socketio.AsyncServer(client_manager=mgr)

    def test_save_to_influx_at_arbitrage_liquidate(self, eio):
        # should add to arbitrage_history if longer than 50 secs
        # should cut history if more than 100 records
        # should delete pair from arbitrage_stats
        # should save to influx with:

        """Test write points from df in TestDataFrameClient object."""
        expected = (
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=1.0 0\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=1.5 1000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=1.5 2000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=1.5 3000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=2.0 4000000000\n"
        )

        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            arbit_ccxt.arbitrage_stats = self.arbitrage_stats
            loop = asyncio.get_event_loop()
            arbit_ccxt.loop = loop
            loop.run_until_complete(arbit_ccxt.arbitrage_liquidate('ETH/BTC'))

            print(m.last_request.body)
            self.assertEqual(m.last_request.body, expected)


if __name__ == '__main__':
    unittest.main()

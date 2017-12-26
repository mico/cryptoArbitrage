import unittest
import arbit_ccxt
import requests_mock
# from influxdb import DataFrameClient
import asyncio
import socketio
from unittest import mock
from copy import copy
from functools import partial

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
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=2.0 5000000000\n"
            b"spreads,highExchange=hitbtc,lowExchange=poloniex spread=3.0 6000000000\n"
        )

        with requests_mock.Mocker() as m:
            m.register_uri(requests_mock.POST,
                           "http://localhost:8086/write",
                           status_code=204)

            arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
            loop = asyncio.get_event_loop()
            arbit_ccxt.loop = loop
            loop.run_until_complete(arbit_ccxt.arbitrage_liquidate(arbit_ccxt.arbitrage_stats['ETH/BTC'], 'ETH/BTC'))

            self.assertEqual(m.last_request.body, expected)

    def test_save_average_spread_to_history(self, eio):
        arbit_ccxt.arbitrage_stats = copy(self.arbitrage_stats)
        loop = asyncio.get_event_loop()
        arbit_ccxt.loop = loop
        loop.run_until_complete(arbit_ccxt.arbitrage_liquidate(arbit_ccxt.arbitrage_stats['ETH/BTC'], 'ETH/BTC'))

        self.assertEqual(arbit_ccxt.arbitrage_history[-1]['average_spread'], 12.5/7)

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
        try:
            loop.run_until_complete(asyncio.gather(
                self.liquidate_with_delay(),
                self.liquidate_without_delay()
            ))
        except KeyError:
            self.fail("KeyError exception raised")

if __name__ == '__main__':
    unittest.main()

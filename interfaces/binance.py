import json
import websockets
import ccxt.async as ccxt
from ccxt.base import errors
import logging
import traceback
import asyncio
import janus
import time

logger = logging.getLogger('arbit')

orderbooks = {}
last_request = 0
previous_update_ids = {}
symbol_queue = {}

class binance(ccxt.binance):
    global logger

    def parse_message(self, symbol, message):
        global orderbooks, previous_update_ids, symbol_queue

        # While listening to the stream, each new event's U should be equal to the previous event's u+1
        if symbol in previous_update_ids and message['U'] != (previous_update_ids[symbol] + 1):
            #logger.error('%s U is not equal previous u+1!!!' % symbol)
            symbol_queue[symbol].append(message)
            return
        # elif symbol in previous_update_ids:
        #     logger.error('%s U is equal previous u+1' % symbol)

        #if len(symbol_queue[symbol]) > 10:
            #logger.error('%s queue more than 10' % symbol)

        for q_message in symbol_queue[symbol]:
            if q_message['U'] == (previous_update_ids[symbol] + 1):
                symbol_queue[symbol].remove(q_message)
                self.parse_message(symbol, q_message)

        for bid in message['b']:
            # import pdb; pdb.set_trace()
            if float(bid[1]) == 0:
                if float(bid[0]) in orderbooks[symbol]['bids']:
                    del(orderbooks[symbol]['bids'][float(bid[0])])
            else:
                orderbooks[symbol]['bids'][float(bid[0])] = float(bid[1])
        for ask in message['a']:
            if float(ask[1]) == 0:
                if float(ask[0]) in orderbooks[symbol]['asks']:
                    del(orderbooks[symbol]['asks'][float(ask[0])])
            else:
                orderbooks[symbol]['asks'][float(ask[0])] = float(ask[1])

        previous_update_ids[symbol] = message['u']

    async def websocket_subscribe(self, symbol):
        global orderbooks, symbol_queue
        last_update_id = None
        symbol_queue[symbol] = []
        while True:
            try:
                ws_client = websockets.connect('wss://stream.binance.com:9443/ws/%s@depth' % self.market_id(symbol).lower())
                await self.load_markets()
                orderbook = await self.publicGetDepth({'symbol': self.market_id(symbol), 'limit': 100})
                last_update_id = orderbook['lastUpdateId']
                result = self.parse_order_book(orderbook)
                orderbooks[symbol] = {
                    'bids': dict(result['bids']),
                    'asks': dict(result['asks'])
                }
                async with ws_client as websocket:
                    while True:
                        try:
                            message = await websocket.recv()
                            message = json.loads(message)
                            # {'e': 'depthUpdate', 'E': 1514964688998, 's': 'ETHBTC', 'U': 65678497, 'u': 65678505,
                            #  'b': [['0.05758400', '0.02600000', []]], 'a': [['0.05762800', '0.00000000', []], ['0.05764200', '1.36500000', []], ['0.05764500', '9.85000000', []], ['0.05765100', '0.00000000', []], ['0.05765300', '0.00000000', []]]}

                            if message['e'] == 'depthUpdate':
                                # Drop any event where u is <= lastUpdateId in the snapshot
                                if message['u'] <= last_update_id:
                                    continue

                                # The first processed should have U <= lastUpdateId+1 AND u >= lastUpdateId+1
                                if symbol not in previous_update_ids and \
                                   not (message['U'] <= last_update_id + 1 and message['u'] >= last_update_id + 1):
                                    continue

                                self.parse_message(symbol, message)
                                self.queue.sync_q.put(symbol)

                        except Exception as err:
                            logger.error(err)
                            logger.error(traceback.print_exc())
                            # reload everything
                            orderbooks[symbol] = {}
                            break

            except errors.ExchangeError as err:
                logger.error(err)
                logger.error(traceback.print_exc())
                logger.error("sleeping 500 seconds")
                await asyncio.sleep(500)
            except Exception as err:
                logger.error(err)
                logger.error(traceback.print_exc())

    async def websocket_run(self, symbols):
        global orderbooks
        await self.load_markets()
        loop = asyncio.get_event_loop()
        self.queue = janus.Queue(loop=loop)

        for symbol in symbols:
            asyncio.gather(self.websocket_subscribe(symbol))
        # TODO: get finished tasks and run again
        while True:
            market = await self.queue.async_q.get()
            yield ['binance', {
                     'asks': list(sorted(orderbooks[market]['asks'].items())),
                     'bids': list(sorted(orderbooks[market]['bids'].items(), reverse=True))
                    }, market]

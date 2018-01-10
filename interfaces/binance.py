import json
import websockets
import ccxt.async as ccxt
import logging
import traceback
import asyncio
import janus

logger = logging.getLogger('arbit')

orderbooks = {}

class binance(ccxt.binance):
    global logger

    async def websocket_subscribe(self, symbol):
        global orderbooks
        while True:
            try:
                ws_client = websockets.connect('wss://stream.binance.com:9443/ws/%s@depth' % self.market_id(symbol).lower())
                result = await self.fetch_order_book(symbol)
                orderbooks[symbol] = {
                    'bids': dict(result['bids']),
                    'asks': dict(result['asks'])
                }
                async with ws_client as websocket:
                    while True:
                        try:
                            message = await websocket.recv()
                            message = json.loads(message)
                            #import pdb; pdb.set_trace()
                            # {'e': 'depthUpdate', 'E': 1514964688998, 's': 'ETHBTC', 'U': 65678497, 'u': 65678505,
                            #  'b': [['0.05758400', '0.02600000', []]], 'a': [['0.05762800', '0.00000000', []], ['0.05764200', '1.36500000', []], ['0.05764500', '9.85000000', []], ['0.05765100', '0.00000000', []], ['0.05765300', '0.00000000', []]]}
                            if message['e'] == 'depthUpdate':
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
                                # print(orderbooks)
                                self.queue.sync_q.put(symbol)
                        except Exception as err:
                            logger.error(err)
                            logger.error(traceback.print_exc())
                            # reload everything
                            # import pdb; pdb.set_trace()

                            orderbooks[symbol] = {}
                            break
            except Exception:
                # restart market connection
                pass

    async def websocket_run(self, symbols):
        global orderbooks
        await self.load_markets()
        loop = asyncio.get_event_loop()
        self.queue = janus.Queue(loop=loop)

        asyncio.gather(*[self.websocket_subscribe(symbol) for symbol in symbols])
        # TODO: get finished tasks and run again
        while True:
            market = await self.queue.async_q.get()
            yield ['binance', {
                     'asks': list(sorted(orderbooks[market]['asks'].items())),
                     'bids': list(sorted(orderbooks[market]['bids'].items(), reverse=True))
                    }, market]

# loop = asyncio.get_event_loop()
# ex = binance()
# loop.run_until_complete(ex.websocket_run(['ETH/BTC']))

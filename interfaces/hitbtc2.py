import json
import websockets
import ccxt.async as ccxt
from time import time
import logging
import traceback
from ccxt.base import errors

logger = logging.getLogger('arbit')

orderbooks = {}


class hitbtc2(ccxt.hitbtc2):
    global logger

    async def do_load_markets(self):
        try:
            await self.load_markets()
        except errors.RequestTimeout:
            await self.do_load_markets()

    async def websocket_run(self, symbols):
        global orderbooks
        await self.do_load_markets()
        ws_client = websockets.connect('wss://api.hitbtc.com/api/2/ws')
        async with ws_client as websocket:
            for symbol in symbols:
                await websocket.send(json.dumps({'method': 'subscribeOrderbook', 'params': {'symbol': self.market_id(symbol)}}))
                message = await websocket.recv()
                message = json.loads(message)
            while True:
                try:
                    message = await websocket.recv()
                    message = json.loads(message)
                    if 'method' in message:
                        if message['method'] == 'snapshotOrderbook':
                            pair = self.markets_by_id[message['params']['symbol']]['symbol']
                            if pair not in orderbooks and pair in symbols:  # fill only if not exists already
                                orderbooks[pair] = {
                                    'bids': dict([[row['price'], float(row['size'])] for row in message['params']['bid']]),
                                    'asks': dict([[row['price'], float(row['size'])] for row in message['params']['ask']])
                                }
                        elif message['method'] == 'updateOrderbook':
                            pair = self.markets_by_id[message['params']['symbol']]['symbol']
                            if pair in orderbooks and pair in symbols:  # wait until full snapshot come
                                for row in message['params']['ask']:
                                    if float(row['size']) > 0:
                                        orderbooks[pair]['asks'][row['price']] = float(row['size'])
                                    else:
                                        del(orderbooks[pair]['asks'][row['price']])
                                for row in message['params']['bid']:
                                    if float(row['size']) > 0:
                                        orderbooks[pair]['bids'][row['price']] = float(row['size'])
                                    else:
                                        del(orderbooks[pair]['bids'][row['price']])
                                yield ['hitbtc2', {'asks': list(sorted(orderbooks[pair]['asks'].items())),
                                                  'bids': list(sorted(orderbooks[pair]['bids'].items(), reverse=True))
                                                  },
                                       pair]
                # except websockets.exceptions.ConnectionClosed as err:
                #     logger.error("connection closed: %s" % err)
                except websockets.exceptions.ConnectionClosed as err:
                    logger.error("hitbtc2 connection closed, restart")
                    orderbooks = {}
                    break
                except Exception as err:
                    logger.error(err)
                    logger.error(traceback.print_exc())
                    # reload snapshots
                    orderbooks = {}
                    #raise
                    break

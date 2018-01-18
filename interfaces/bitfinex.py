import json
import websockets
import ccxt.async as ccxt
import logging
import traceback
from ccxt.base import errors

logger = logging.getLogger('arbit')

orderbooks = {}
channel_ids = {}


class bitfinex(ccxt.bitfinex):
    global logger

    async def do_load_markets(self):
        try:
            await self.load_markets()
        except errors.RequestTimeout:
            await self.do_load_markets()

    async def websocket_run(self, symbols):
        global orderbooks, channel_ids
        await self.do_load_markets()
        ws_client = websockets.connect('wss://api.bitfinex.com/ws/2')
        async with ws_client as websocket:
            for symbol in symbols:
                await websocket.send(json.dumps({
                    'event': 'subscribe',
                    'channel': 'book',
                    'symbol': self.market_id(symbol),
                    'len': 100,
                }))

            while True:
                try:
                    message = await websocket.recv()
                    message = json.loads(message)
                    if 'event' in message:
                        if message['event'] == 'subscribed' and message['channel'] == 'book':
                            channel_ids[message['chanId']] = message['symbol'].replace('t', '')
                    elif type(message) is list:
                        pair_id = message[0]
                        data = message[1]
                        if data == 'hb':
                            pass
                        else:
                            pair = self.markets_by_id[channel_ids[pair_id]]['symbol']
                            if type(data[0]) is list:
                                # snapshot
                                bids = list(filter(lambda x: x[2] > 0, data))
                                asks = list(filter(lambda x: x[2] < 0, data))

                                orderbooks[pair] = {
                                    'bids': dict([[row[0], float(abs(row[2]))] for row in bids]),
                                    'asks': dict([[row[0], float(abs(row[2]))] for row in asks])
                                }
                            else:
                                if data[1] > 0:
                                    # update
                                    orderbooks[pair][data[2] > 0 and 'bids' or 'asks'][data[0]] = abs(data[2])
                                elif data[1] == 0:
                                    # delete
                                    del(orderbooks[pair][data[2] > 0 and 'bids' or 'asks'][data[0]])
                            yield ['bitfinex',
                                   {'asks': list(sorted(orderbooks[pair]['asks'].items())),
                                    'bids': list(sorted(orderbooks[pair]['bids'].items(), reverse=True))
                                    },
                                   pair]

                except Exception as err:
                    logger.error(err)
                    logger.error(traceback.print_exc())
                    # reload everything
                    orderbooks = channel_ids = {}
                    break

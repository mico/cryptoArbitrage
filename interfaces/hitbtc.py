import json
import websockets
import ccxt.async as ccxt
from time import time

orderbooks = {}

class hitbtc(ccxt.hitbtc2):
    async def websocket_run(self, symbols):
        await self.load_markets()
        #print("symbols: %s" % symbols)
        while True:
            async with websockets.connect('wss://api.hitbtc.com/api/2/ws') as websocket:
                start_at = time()
                #print("subscribe to %s" % self.market_id('ETH/BTC'))
                for symbol in symbols:
                # await asyncio.gather(*([asyncio.ensure_future(websocket.send(json.dumps(
                #     {'method': 'subscribeOrderbook', 'params': {'symbol': self.market_id(symbol)}}))) for symbol in symbols]))
                    await websocket.send(json.dumps({'method': 'subscribeOrderbook', 'params': {'symbol': self.market_id(symbol)}}))
                    message = await websocket.recv()
                    message = json.loads(message)
                    # print("message: %s" % message)
                    # if not message['result']:
                    #     raise Exception('subscription error: %s' % message)
                while True:
                    try:
                        message = await websocket.recv()
                        message = json.loads(message)
                        #print("message: %s" % message)
                        if 'method' in message:
                            if message['method'] == 'snapshotOrderbook':
                                pair = self.markets_by_id[message['params']['symbol']]['symbol']
                                if pair not in orderbooks and pair in symbols:  # fill only if not exists already
                                    orderbooks[pair] = {
                                        'bids': dict([[row['price'], float(row['size'])] for row in message['params']['bid']]),
                                        'asks': dict([[row['price'], float(row['size'])] for row in message['params']['ask']])
                                    }
                            elif message['method'] == 'updateOrderbook':
                                #print("got update: %s after %s seconds " % (message['params']['symbol'], time() - start_at))
                                pair = self.markets_by_id[message['params']['symbol']]['symbol']
                                if pair in orderbooks and pair in symbols:  # wait until full snapshot come
                                    # print("got updates for %s" % (pair))
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
                                    yield ['hitbtc', {'asks': list(sorted(orderbooks[pair]['asks'].items())),
                                                      'bids': list(sorted(orderbooks[pair]['bids'].items(), reverse=True))
                                                      },
                                           pair]
                    except Exception as err:
                        print("hitbtc error!!! %s" % err)
                        raise Exception(err)

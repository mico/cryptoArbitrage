import json
import websockets
import ccxt.async as ccxt

orderbooks = {}

class hitbtc(ccxt.hitbtc2):
    async def websocket_run(self, symbols):
        await self.load_markets()
        async with websockets.connect('ws://api.hitbtc.com:80') as websocket:
            while True:
                message = await websocket.recv()
                message = json.loads(message)
                if 'MarketDataSnapshotFullRefresh' in message:
                    pair = self.markets_by_id[message['MarketDataSnapshotFullRefresh']['symbol']]['symbol']
                    if pair not in orderbooks and pair in symbols:  # fill only if not exists already
                        orderbooks[pair] = {
                            'bids': dict([[row['price'], row['size']/1000] for row in message['MarketDataSnapshotFullRefresh']['bid']]),
                            'asks': dict([[row['price'], row['size']/1000] for row in message['MarketDataSnapshotFullRefresh']['ask']])
                        }
                if 'MarketDataIncrementalRefresh' in message:
                    pair = self.markets_by_id[message['MarketDataIncrementalRefresh']['symbol']]['symbol']
                    if pair in orderbooks and pair in symbols:  # wait until full snapshot come
                        for row in message['MarketDataIncrementalRefresh']['ask']:
                            if row['size'] > 0:
                                orderbooks[pair]['asks'][row['price']] = row['size']/1000
                            else:
                                del(orderbooks[pair]['asks'][row['price']])
                        for row in message['MarketDataIncrementalRefresh']['bid']:
                            if row['size'] > 0:
                                orderbooks[pair]['bids'][row['price']] = row['size']/1000
                            else:
                                del(orderbooks[pair]['bids'][row['price']])
                        yield ['hitbtc', {'asks': list(sorted(orderbooks[pair]['asks'].items())),
                                          'bids': list(sorted(orderbooks[pair]['bids'].items(), reverse=True))
                                          },
                               pair]

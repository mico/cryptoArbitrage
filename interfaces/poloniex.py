import json
import websockets
import ccxt.async as ccxt


class poloniex(ccxt.poloniex):
    def get_market_by_poloniex_id(self, id):
        for market, data in self.markets_by_id.items():
            if data['info']['id'] == id:
                return data['symbol']

    async def websocket_run(self, symbols):
        await self.load_markets()
        async with websockets.connect('wss://api2.poloniex.com') as websocket:
            await websocket.send(json.dumps({'command': 'subscribe', 'channel': 1010}))  # heartbeat
            for symbol in symbols:
                await websocket.send(json.dumps({'command': 'subscribe', 'channel': self.market_id(symbol)}))  # BTC_ETH
            orderbooks = {}
            while True:
                try:
                    message = await websocket.recv()
                    message = json.loads(message)
                    previous_sequence = 0
                    if 'error' in message:
                        print("error: %s" % message['error'])
                    elif message[0] == 1010:  # heartbeat
                        pass
                    else:
                        if len(message) < 2:
                            print("error? %s" % message)
                        else:
                            pass
                        if previous_sequence > message[1]:
                            # TODO: put on queue
                            raise Exception('Previous sequience higher')
                        else:
                            previous_sequence = message[1]
                        for row in message[2]:
                            market = self.get_market_by_poloniex_id(message[0])
                            if row[0] == 'i':
                                orderbooks[market] = {'asks': row[1]['orderBook'][0],
                                                      'bids': row[1]['orderBook'][1]}
                            if row[0] == 'o':
                                if row[3] == '0.00000000':
                                    if row[1] == 1:
                                        del(orderbooks[market]['bids'][row[2]])
                                    else:
                                        try:
                                            del(orderbooks[market]['asks'][row[2]])
                                        except:
                                            import pdb; pdb.set_trace()
                                else:
                                    if row[1] == 1:
                                        orderbooks[market]['bids'][row[2]] = row[3]
                                    else:
                                        orderbooks[market]['asks'][row[2]] = row[3]
                        yield ['poloniex', {'asks': list(sorted(orderbooks[market]['asks'].items())),
                                            'bids': list(sorted(orderbooks[market]['bids'].items(), reverse=True))
                                            },
                               market]

                except Exception as err:
                    print("ERROR!!! %s" % err)
                    raise Exception(err)


def print_orders(pair, orderbooks):
    # print bids/asks
    print(chr(27) + "[2J")
    print("spread: %.8f" % (float(list(sorted(orderbooks[pair]['asks'].items()))[0][0])
                            - float(list(sorted(orderbooks[pair]['bids'].items(), reverse=True))[0][0])))
    print("bids:")
    print(list(sorted(orderbooks[pair]['bids'].items(), reverse=True))[-1])
    for i in sorted(range(0, 10), reverse=True):
        print(list(sorted(orderbooks[pair]['bids'].items(), reverse=True))[i])
    print("asks:")
    for i in range(0, 10):
        print(list(sorted(orderbooks[pair]['asks'].items()))[i])
    print(list(sorted(orderbooks[pair]['asks'].items()))[-1])

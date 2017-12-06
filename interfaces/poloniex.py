import json
import websockets
import ccxt.async as ccxt

ex = ccxt.poloniex()

def fetch_markets(self):
    markets = self.publicGetReturnTicker()
    keys = list(markets.keys())
    result = []
    for p in range(0, len(keys)):
        id = keys[p]
        market = markets[id]
        quote, base = id.split('_')
        base = self.common_currency_code(base)
        quote = self.common_currency_code(quote)
        symbol = base + '/' + quote
        result.append(self.extend(self.fees['trading'], {
            'id': id,
            'symbol': symbol,
            'base': base,
            'quote': quote,
            'lot': self.limits['amount']['min'],
            'info': market,
        }))
    return result


def print_orders(pair, orderbooks):
    # print bids/asks
    print(chr(27) + "[2J")
    # import pdb; pdb.set_trace()
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


async def run(markets):
    tickers = await ex.publicGetReturnTicker()  # {'BTC_ETH': {'id': 7 ...}}
    tickers = dict([[data['id'], ticker] for ticker, data in tickers.items()])
    async with websockets.connect('wss://api2.poloniex.com') as websocket:
        for market in markets:
            ticker = market.split('/')
            ticker.reverse()
            ticker = '_'.join(ticker)
            print("subscribe to %s" % ticker)
            await websocket.send(json.dumps({'command': 'subscribe', 'channel': ticker}))  # BTC_ETH
        orderbooks = {}
        while True:
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
                    if row[0] == 'i':
                        # pair = row[1]['currencyPair']
                        orderbooks[tickers[message[0]]] = {'asks': row[1]['orderBook'][0],
                                                  'bids': row[1]['orderBook'][1]}
                    if row[0] == 'o':
                        if row[3] == '0.00000000':
                            if row[1] == 1:
                                del(orderbooks[tickers[message[0]]]['bids'][row[2]])
                            else:
                                del(orderbooks[tickers[message[0]]]['asks'][row[2]])
                        else:
                            if row[1] == 1:
                                orderbooks[tickers[message[0]]]['bids'][row[2]] = row[3]
                            else:
                                orderbooks[tickers[message[0]]]['asks'][row[2]] = row[3]
                yield ['poloniex', orderbooks, tickers[message[0]]]

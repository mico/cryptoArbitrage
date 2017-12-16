from requests import Session  # pip install requests
import asyncio
import janus
import ccxt.async as ccxt
import sys
import cfscrape

# import sys
sys.path.insert(0, 'signalr-client-py')
from signalr import Connection

# or use this!!! https://github.com/aio-libs/janus

# {'MarketName': None, 'Nounce': 18255, 'Buys': [{'Quantity': 6.81746367, 'Rate': 0.04055002}, {'Quantity': 7.42865764, 'Rate': 0.04055001}, {'Quantity': 25.14801556, 'Rate': 0.04055}
# ({'MarketName': 'BTC-ETH', 'Nounce': 18285, 'Buys': [{'Type': 0, 'Rate': 0.0400334, 'Quantity': 96.1451}, {'Type': 1, 'Rate': 0.04001764, 'Quantity': 0.0}], 'Sells': [], 'Fills': []},)
# 'Fills': [{'OrderType': 'SELL', 'Rate': 0.040522, 'Quantity': 0.1, 'TimeStamp': '2017-12-04T16:27:22.18'}]}

market_connection_ids = {}
orderbooks = {}

# TODO: check Nounce and put on queue

class Connection(Connection):
    def get_send_counter(self):
        return self.__send_counter

def print_error(error):
    print('error: ', error)

class bittrex(ccxt.bittrex):
    def signalr_connected(self, *args, **kwargs):
        if 'R' in kwargs and type(kwargs['R']) is not bool:
            market = market_connection_ids[int(kwargs['I'])]
            orderbooks[market] = {
                'bids': dict([[row['Rate'], row['Quantity']] for row in kwargs['R']['Buys']]),
                'asks': dict([[row['Rate'], row['Quantity']] for row in kwargs['R']['Sells']])
            }
            self.queue.put(market)

    def signalr_message(self, *args, **kwargs):
        # import pdb; pdb.set_trace()
        market = self.markets_by_id[args[0]['MarketName']]['symbol']
        if market in orderbooks:
            if len(args) > 1:
                raise Exception("args more then 1")
            for row in args[0]['Buys']:
                if row['Type'] in [0, 2]: # 0 - remove, 2 - sold/bought I think
                    orderbooks[market]['bids'][row['Rate']] = row['Quantity']
                else:
                    try:
                        del(orderbooks[market]['bids'][row['Rate']])
                    except:
                        pass
            for row in args[0]['Sells']:
                if row['Type'] in [0, 2]:
                    orderbooks[market]['asks'][row['Rate']] = row['Quantity']
                else:
                    try:
                        del(orderbooks[market]['asks'][row['Rate']])
                    except:
                        pass
            self.queue.put(market)

    async def signalr_connect(self, symbols, queue):
        self.queue = queue
        #session = 
        with cfscrape.create_scraper() as session:
            connection = Connection("https://www.bittrex.com/signalR/", session)
            chat = connection.register_hub('corehub')
            connection.received += self.signalr_connected
            connection.error += print_error
            await connection.start()

            chat.client.on('updateExchangeState', self.signalr_message)

            for symbol in symbols:
                await chat.server.invoke('SubscribeToExchangeDeltas', self.market_id(symbol))
                await chat.server.invoke('QueryExchangeState', self.market_id(symbol))
                market_connection_ids[connection.get_send_counter()] = symbol
                # print("I for %s: %s" % (symbol, connection.get_send_counter()))
                # SubscribeToSummaryDeltas ?

            # Value of 1 will not work, you will get disconnected
            # connection.wait(None)

    async def websocket_run(self, symbols):
        await self.load_markets()

        loop = asyncio.get_event_loop()
        queue = janus.Queue(loop=loop)
        await self.signalr_connect(symbols, queue.sync_q)
        while True:
            market = await queue.async_q.get()

            yield ['bittrex', {'asks': list(sorted(orderbooks[market]['asks'].items())),
                               'bids': list(sorted(orderbooks[market]['bids'].items(), reverse=True))
                               }, market]

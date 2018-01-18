import sys
sys.path.insert(0, 'externals/signalr-client-py')
import asyncio
import janus
import ccxt.async as ccxt
import cfscrape
from signalr import Connection
import logging
import traceback

logger = logging.getLogger('arbit')
# {'MarketName': None, 'Nounce': 18255, 'Buys': [{'Quantity': 6.81746367, 'Rate': 0.04055002}, {'Quantity': 7.42865764, 'Rate': 0.04055001}, {'Quantity': 25.14801556, 'Rate': 0.04055}
# ({'MarketName': 'BTC-ETH', 'Nounce': 18285, 'Buys': [{'Type': 0, 'Rate': 0.0400334, 'Quantity': 96.1451}, {'Type': 1, 'Rate': 0.04001764, 'Quantity': 0.0}], 'Sells': [], 'Fills': []},)
# 'Fills': [{'OrderType': 'SELL', 'Rate': 0.040522, 'Quantity': 0.1, 'TimeStamp': '2017-12-04T16:27:22.18'}]}

market_connection_ids = {}
orderbooks = {}
connection_open = True
last_nounce = {}
snapshot_nounce = {}
market_counter = {}

# TODO: check Nounce and put on queue

class Connection(Connection):
    def get_send_counter(self):
        return self.__send_counter

class bittrex(ccxt.bittrex):
    def signalr_connected(self, *args, **kwargs):
        global snapshot_nounce
        # import pdb; pdb.set_trace()
        # save snapshot kwargs['R']['Nounce']
        if 'R' in kwargs and type(kwargs['R']) is not bool:
            market = market_connection_ids[int(kwargs['I'])]
            if market in snapshot_nounce:
                print("snapshot already got before")
            snapshot_nounce[market] = kwargs['R']['Nounce']
            orderbooks[market] = {
                'bids': dict([[row['Rate'], row['Quantity']] for row in kwargs['R']['Buys']]),
                'asks': dict([[row['Rate'], row['Quantity']] for row in kwargs['R']['Sells']])
            }
            self.queue.put(market)
    def parse_message(self, message):
        global last_nounce
        market = self.markets_by_id[message['MarketName']]['symbol']
        if market in orderbooks:
            for row in message['Buys']:
                if row['Type'] in [0, 2]:  # 0 - remove, 2 - sold/bought I think
                    orderbooks[market]['bids'][row['Rate']] = row['Quantity']
                else:
                    try:
                        del(orderbooks[market]['bids'][row['Rate']])
                    except Exception:
                        pass
            for row in message['Sells']:
                if row['Type'] in [0, 2]:
                    orderbooks[market]['asks'][row['Rate']] = row['Quantity']
                else:
                    try:
                        del(orderbooks[market]['asks'][row['Rate']])
                    except Exception:
                        pass
            #print("updated %s" % market)
            last_nounce[market] = message['Nounce']
            self.queue.put(market)

    def signalr_message(self, *args, **kwargs):
        global last_nounce, snapshot_nounce, logger
        try:
            if len(args) > 1:
                raise Exception("args more then 1")

            market = self.markets_by_id[args[0]['MarketName']]['symbol']
            if market not in market_counter:
                market_counter[market] = 1
            else:
                market_counter[market] += 1
            #print(args[0]['Nounce'])
            if market not in snapshot_nounce:
                # TODO: put to queue
                self.pre_queue.append(args[0])
                return
            if len(self.pre_queue) > 0:
                # filter queue by current market
                queue = list(filter(lambda x: self.markets_by_id[x['MarketName']]['symbol'] == market, self.pre_queue))
                for q in queue:
                    if self.markets_by_id[q['MarketName']]['symbol'] == market:
                        # print("q nounce: %s, snapshot nounce: %s" % (q['Nounce'], snapshot_nounce[market]))
                        if q['Nounce'] == snapshot_nounce[market]:
                            # print("found snapshot nounce for %s" % market)
                            pass
                            self.pre_queue.remove(q)
                            queue.remove(q)
                        else:
                            if q['Nounce'] == (snapshot_nounce[market] + 1):
                                # print("found snapshot nounce + 1 for %s" % market)
                                self.parse_message(q)
                                # then parse remaining messages in queue
                                self.pre_queue.remove(q)
                                queue.remove(q)
                                if len(queue) > 0:
                                    for f in queue.sort(key=lambda x: x['Nounce']):
                                        if f['Nounce'] > (snapshot_nounce[market] + 1):
                                            self.parse_message(f)
                                        self.pre_queue.remove(f)
                                    break

            if market in last_nounce:
                if args[0]['Nounce'] < last_nounce[market]:
                    print("%s old Nounce skip" % market)
                    return
                elif args[0]['Nounce'] == last_nounce[market]:
                    # print("nounce the same, skip!!!")
                    return
                elif args[0]['Nounce'] == (last_nounce[market] + 1):
                    self.parse_message(args[0])
                elif args[0]['Nounce'] > (last_nounce[market] + 1):
                    print("sequence too fresh, resync")
                    self.queue.put("closed")
                    # resync!!!
            elif args[0]['Nounce'] == (snapshot_nounce[market] + 1):
                self.parse_message(args[0])
            # else:
            #     if args[0]['Nounce'] < snapshot_nounce[market]:
            #         print("nounce less than in snapshot!!!")
            #         return
            # self.parse_message(args[0])

        except Exception as err:
            logger.error(err)
            logger.error(traceback.print_exc())
            return

    def error(self, error):
        global connection_open
        print('error: ', error)
        if error == 'connection closed':
            connection_open = False
            self.queue.put("closed")

    async def signalr_connect(self, symbols, queue):
        self.queue = queue
        with cfscrape.create_scraper() as session:
            connection = Connection("https://www.bittrex.com/signalR/", session)
            chat = connection.register_hub('corehub')
            connection.received += self.signalr_connected
            connection.error += self.error
            await connection.start()

            chat.client.on('updateExchangeState', self.signalr_message)

            for symbol in symbols:
                await chat.server.invoke('SubscribeToExchangeDeltas', self.market_id(symbol))
                await chat.server.invoke('QueryExchangeState', self.market_id(symbol))
                market_connection_ids[connection.get_send_counter()] = symbol

    async def websocket_run(self, symbols):
        global connection_open
        await self.load_markets()

        loop = asyncio.get_event_loop()
        queue = janus.Queue(loop=loop)
        self.pre_queue = []
        await self.signalr_connect(symbols, queue.sync_q)
        while True:
            market = await queue.async_q.get()
            if market == "closed":
                logger.error("bittrex restart")
                break

            yield ['bittrex', {'asks': list(sorted(orderbooks[market]['asks'].items())),
                               'bids': list(sorted(orderbooks[market]['bids'].items(), reverse=True))
                               }, market]

from requests import Session  # pip install requests
from signalr import Connection  # pip install signalr-client
# import sys
# sys.path.append('python-bittrex-websocket')
#
# import bittrex_websocket
# from time import sleep
#
# if __name__ == "__main__":
#     class MyBittrexSocket(bittrex_websocket.BittrexSocket):
#         def on_open(self):
#             self.nounces = []
#             self.msg_count = 0
#
#         def on_debug(self, **kwargs):
#             pass
#
#         def on_message(self, *args, **kwargs):
#             self.nounces.append(args[0])
#             self.msg_count += 1
#
#
#     t = ['BTC-ETH', 'ETH-1ST', 'BTC-1ST', 'BTC-NEO', 'ETH-NEO']
#     ws = MyBittrexSocket()
#     ws.subscribe_to_orderbook(t)
#     #ws.run()
#     while ws.msg_count < 20:
#         sleep(1)
#         continue
#     else:
#         for msg in ws.nounces:
#             print(msg)
#     ws.stop()
    #order_book.stop()

# def blocking_function():
#     time.sleep(42)
#
# pool = ThreadPoolExecutor(max_workers=multiprocessing.cpu_count())
# loop = asyncio.get_event_loop()
# loop.run_in_executor(pool, blocking_function)
# loop.close()

# or use this!!! https://github.com/aio-libs/janus

# {'MarketName': None, 'Nounce': 18255, 'Buys': [{'Quantity': 6.81746367, 'Rate': 0.04055002}, {'Quantity': 7.42865764, 'Rate': 0.04055001}, {'Quantity': 25.14801556, 'Rate': 0.04055}
# ({'MarketName': 'BTC-ETH', 'Nounce': 18285, 'Buys': [{'Type': 0, 'Rate': 0.0400334, 'Quantity': 96.1451}, {'Type': 1, 'Rate': 0.04001764, 'Quantity': 0.0}], 'Sells': [], 'Fills': []},)
# 'Fills': [{'OrderType': 'SELL', 'Rate': 0.040522, 'Quantity': 0.1, 'TimeStamp': '2017-12-04T16:27:22.18'}]}

market_connection_ids = {}
orderbooks = {}

class Connection(Connection):
    def get_send_counter(self):
        return self.__send_counter

def handle_received(*args, **kwargs):
    # Orderbook snapshot:
    if 'R' in kwargs and type(kwargs['R']) is not bool:
        # kwargs['R'] contains your snapshot
        # import pdb; pdb.set_trace()
        #print(kwargs['R'])
        #print("connection counter: %s" % kwargs['I']) # !!!
        orderbooks[market_connection_ids[int(kwargs['I'])]] = {
            'bids': dict([[row['Rate'], row['Quantity']] for row in kwargs['R']['Buys']]),
            'asks': dict([[row['Rate'], row['Quantity']] for row in kwargs['R']['Sells']])
        }


            # u() && (l || (l = !0, i.server.queryExchangeState(r).done(function(n) {
            #     t("server.queryExchangeState().done()");
            #     t(n);
            #     n && w && s("data-query-exchange-" + r, n);
            #     l = !1
            # })))

# You didn't add the message stream
def msg_received(*args, **kwargs):
    # args[0] contains your stream
    #import pdb; pdb.set_trace()
    if len(args) > 1:
        raise Exception("args more then 1")
    for row in args[0]['Buys']:
        if row['Type'] in [0, 2]: # 0 - remove, 2 - sold/bought I think
            orderbooks[args[0]['MarketName']]['bids'][row['Rate']] = row['Quantity']
        else:
            del(orderbooks[args[0]['MarketName']]['bids'][row['Rate']])

    for row in args[0]['Sells']:
        if row['Type'] in [0, 2]:
            orderbooks[args[0]['MarketName']]['asks'][row['Rate']] = row['Quantity']
        else:
            del(orderbooks[args[0]['MarketName']]['asks'][row['Rate']])
    # print bids/asks
    if args[0]['MarketName'] == 'BTC-NEO':
        print(chr(27) + "[2J")

        print(args)
        print("spread: %.8f" % (float(list(sorted(orderbooks[args[0]['MarketName']]['asks'].items()))[0][0])
                             - float(list(sorted(orderbooks[args[0]['MarketName']]['bids'].items(), reverse=True))[0][0])))
        print("bids:")
        print(list(sorted(orderbooks[args[0]['MarketName']]['bids'].items(), reverse=True))[-1])
        for i in sorted(range(0, 10), reverse=True):
            print(list(sorted(orderbooks[args[0]['MarketName']]['bids'].items(), reverse=True))[i])
        print("asks:")
        for i in range(0, 10):
            print(list(sorted(orderbooks[args[0]['MarketName']]['asks'].items()))[i])
        print(list(sorted(orderbooks[args[0]['MarketName']]['asks'].items()))[-1])



def print_error(error):
    print('error: ', error)


def main():
    with Session() as session:
        connection = Connection("https://www.bittrex.com/signalR/", session)
        chat = connection.register_hub('corehub')
        connection.received += handle_received
        connection.error += print_error
        connection.start()

        # You missed this part
        chat.client.on('updateExchangeState', msg_received)

        for market in ["BTC-ADA", "BTC-NEO"]:
            chat.server.invoke('SubscribeToExchangeDeltas', market)
            chat.server.invoke('QueryExchangeState', market)
            market_connection_ids[connection.get_send_counter()] = market
            print("I for %s: %s" % (market, connection.get_send_counter()))
            # SubscribeToSummaryDeltas ?

        # Value of 1 will not work, you will get disconnected
        connection.wait(120000)

main()

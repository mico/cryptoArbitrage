# import websocket
# import thread
# import time
import json

import asyncio
import websockets
#import ccxt.async as ccxt
import ccxt
import sys

# const ws2SubscriptionToChannelIdMap = {
#   trollbox: 1001,
#   ticker: 1002,
#   footer: 1003,
#   heartbeat: 1010,
# };
ex = ccxt.poloniex()

                # case ws2SubscriptionToChannelIdMap.heartbeat: {
                #   this.emit('heartbeat');
                #   break;


#tickers = ex.publicGetReturnTicker() # {'BTC_ETH': {'id': 7 ...}}
#sys.exit(0)

async def hello():
    async with websockets.connect('wss://api2.poloniex.com') as websocket:
        await websocket.send(json.dumps({'command':'subscribe','channel':'BTC_ETH'}))

        orderbooks = {}
        while True:
            message = await websocket.recv()
            message = json.loads(message)
            previous_sequence = 0
            if 'error' in message:
                print("error: %s" % message['error'])

            if message[0] == 1010: #heartbeat
                pass
            else:
                #print(message)
                if len(message) < 2:
                    print("error? %s" % message)
                else:
                    pass
                    # print({'channelId': message[0],
                    #        'sequence': message[1]})
                if previous_sequence > message[1]:
                    raise Exception('Previous sequience higher')
                else:
                    previous_sequence = message[1]
                for row in message[2]:
                    if row[0] == 'i':
                        pair = row[1]['currencyPair']
                        # print("new orders: %s" % row)
                        # import pdb; pdb.set_trace()
                        orderbooks[message[0]] = {'asks': row[1]['orderBook'][0],
                                                  'bids': row[1]['orderBook'][1]}
                    if row[0] == 'o':
                        if row[3] == '0.00000000':
                            # print("remove order book (%s): rate: %s, amount: %s" %
                            #       ((row[1] == 1 and 'bid' or 'ask'), row[2], row[3]))
                            # import pdb; pdb.set_trace()
                            if row[1] == 1:
                                del(orderbooks[message[0]]['bids'][row[2]])
                            else:
                                del(orderbooks[message[0]]['asks'][row[2]])
                        else:
                            # import pdb; pdb.set_trace()
                            # print("modify order book (%s): rate: %s, amount: %s" %
                            #       ((row[1] == 1 and 'bid' or 'ask'), row[2], row[3]))
                            if row[1] == 1:
                                orderbooks[message[0]]['bids'][row[2]] = row[3]
                            else:
                                orderbooks[message[0]]['asks'][row[2]] = row[3]
                # print bids/asks
                print(chr(27) + "[2J")
                # import pdb; pdb.set_trace()
                print("spread: %.8f" % (float(list(sorted(orderbooks[message[0]]['asks'].items()))[0][0])
                                     - float(list(sorted(orderbooks[message[0]]['bids'].items(), reverse=True))[0][0])))
                print("bids:")
                print(list(sorted(orderbooks[message[0]]['bids'].items(), reverse=True))[-1])
                for i in sorted(range(0, 10), reverse=True):
                    print(list(sorted(orderbooks[message[0]]['bids'].items(), reverse=True))[i])
                print("asks:")
                for i in range(0, 10):
                    print(list(sorted(orderbooks[message[0]]['asks'].items()))[i])
                print(list(sorted(orderbooks[message[0]]['asks'].items()))[-1])
                    # if row[0] == 't':
                    #     print("new trade: %s at %s, amount: %s" % (row[2] == 1 and 'buy' or 'sell', row[3], row[4]))

            #print("{}".format(data_row))


asyncio.get_event_loop().run_until_complete(
    hello())

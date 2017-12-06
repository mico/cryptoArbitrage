import json
import websockets

orderbooks = {}

# pairs as XEMUSD / BTCUSD / NXTETH / DASHUSD / DASHBTC
async def run(markets):
    async with websockets.connect('ws://api.hitbtc.com:80') as websocket:
        while True:
            message = await websocket.recv()
            message = json.loads(message)
            if 'MarketDataSnapshotFullRefresh' in message:
                pair = message['MarketDataSnapshotFullRefresh']['symbol']
                if pair not in orderbooks:  # fill only if not exists already
                    orderbooks[pair] = {
                        'bids': dict([[row['price'], row['size']/1000] for row in message['MarketDataSnapshotFullRefresh']['bid']]),
                        'asks': dict([[row['price'], row['size']/1000] for row in message['MarketDataSnapshotFullRefresh']['ask']])
                    }
                print("%s loaded..." % pair)
            if 'MarketDataIncrementalRefresh' in message:
                pair = message['MarketDataIncrementalRefresh']['symbol']
                if pair in orderbooks:  # wait until full snapshot come
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

                    # print bids/asks
                    # on_update_callback(orderbooks)
                    yield ['hitbtc', orderbooks, pair]
                    # if pair == 'ETHBTC':
                    #     print(chr(27) + "[2J")
                    #     # import pdb; pdb.set_trace()
                    #     print("spread: %.8f" % (float(list(sorted(orderbooks[pair]['asks'].items()))[0][0])
                    #                          - float(list(sorted(orderbooks[pair]['bids'].items(), reverse=True))[0][0])))
                    #     print("bids:")
                    #     print(list(sorted(orderbooks[pair]['bids'].items(), reverse=True))[-1])
                    #     for i in sorted(range(0, 10), reverse=True):
                    #         print(list(sorted(orderbooks[pair]['bids'].items(), reverse=True))[i])
                    #     print("asks:")
                    #     for i in range(0, 10):
                    #         print(list(sorted(orderbooks[pair]['asks'].items()))[i])
                    #     print(list(sorted(orderbooks[pair]['asks'].items()))[-1])


# asyncio.get_event_loop().run_until_complete(
#     run(lambda x: x))
# __all__ = ['run']

from aiohttp import web
import socketio
from influxdb import InfluxDBClient
import yaml

sio = socketio.AsyncServer()
app = web.Application()
sio.attach(app)
config = yaml.safe_load(open("config.yml"))

client = InfluxDBClient(config['influxdb']['host'], config['influxdb']['port'], config['influxdb']['user'],
                        config['influxdb']['password'], config['influxdb']['database'])

async def index(request):
    """Serve the client-side application."""
    with open('index.html') as f:
        return web.Response(text=f.read(), content_type='text/html')

@sio.on('connect', namespace='/chat')
async def connect(sid, environ):
    print("connect ", sid)

    spreads_by_pairs = {}
    for row in client.query('select * from spreads', epoch='s').items()[0][1]:
        print("got %s" % row)
        spreads_by_pairs[row['pair']] = {
            'spreadBidAskMin': ["%.2f" % row['lowestBASpread'], row['lowestAskExchange']],
            'spreadBidAskMax': ["%.2f" % row['highestBASpread'], row['highestBidExchange']],
            'spreadLastPrice': "%.2f" % float((row['highestBidPrice'] - row['lowestAskPrice']) / (row['lowestAskPrice'] / 100)),
            'spreadLastPriceMaxExchange': ["%.8f" % row['highestBidPrice'], row['highestBidExchange']],
            'spreadLastPriceMinExchange': ["%.8f" % row['lowestAskPrice'], row['lowestAskExchange']],
        }

    # exchanges bids/asks
    # {
    #     'ask': '0.0868010',
    #     'bid': '0.0866970',
    #     'bidAskSpread': 0.12,
    #     'exchange': "bitfinex",
    #     'lastPrice': "0.0868010",
    #     'lastTradeTime': "1510244615.9965863",
    #     'lastTradeVolume': '',
    #     'lastUpdated': 1510244616838,
    #     'volume24': "96876.7078",
    # }

    await sio.emit('publicView', {
        'exchangeList': [
            "bitfinex",
            "bitmex",
            "bitstamp",
            "bittrex",
            "cex",
            "gdax",
            "kraken",
            "poloniex"
        ],
        'masterPairs': [[pair, pair] for pair in spreads_by_pairs.keys()],
        'btc_usd': [
            {'1510244645235': [
                {
                    'apiSatus': '',
                    'ask': "7155.9000",
                    'askBuy': "7155.0750",
                    'askLotVolume': '',
                    'bid': "7150.4000",
                    'bidAskSpread': 0.08,
                    'bidLotVolume': '',
                    'bidSell': "7151.2250",
                    'exchange': "bitfinex",
                    'isFrozen': '',
                    'lastPrice': "7150.5000",
                    'lastTradeTime': "1510244612.2000005",
                    'lastTradeVolume': '',
                    'lastUpdated': 1510244615735,
                    'trades24': '',
                    'uniquePair': "BTCUSD",
                    'volume24': "105568.3536",
                    'volume30': '',
                    'vwap': ''
                }
            ]}
        ],
        'data': [{'1510247959': {
            'dataByPairPrice': {'btc_usd': [
                {
                    'apiStatus': '',
                    'ask': '0.0868010',
                    'askBuy': '0.0867854',
                    'askLotVolume': '',
                    'bid': '0.0866970',
                    'bidAskSpread': 0.12,
                    'bidLotVolume': '',
                    'bidSell': "0.0867126",
                    'exchange': "bitfinex",
                    'isFrozen': '',
                    'lastPrice': "0.0868010",
                    'lastTradeTime': "1510244615.9965863",
                    'lastTradeVolume': '',
                    'lastUpdated': 1510244616838,
                    'trades24': '',
                    'uniquePair': "BTCUSD",
                    'volume24': "96876.7078",
                    'volume30': '',
                    'vwap': ''
                },
                {
                    'apiStatus': '',
                    'ask': '0.0838010',
                    'askBuy': '0.0867854', # данные с процентами биржи?
                    'askLotVolume': '',
                    'bid': '0.0836970',
                    'bidAskSpread': 2.13,
                    'bidLotVolume': '',
                    'bidSell': "0.0867126", # данные с процентами биржи?
                    'exchange': "bittrex",
                    'isFrozen': '',
                    'lastPrice': "0.0838010", # совпадает с ask
                    'lastTradeTime': "1510244615.9965863",
                    'lastTradeVolume': '',
                    'lastUpdated': 1510244616838,
                    'trades24': '',
                    'uniquePair': "BTCUSD",
                    'volume24': "96876.7078",
                    'volume30': '',
                    'vwap': ''
                },
            ]},
            'spreads': {
                'minmax': {
                    'byBidAsk': {
                        'max': {
                            'exchange': 'cex',
                            'pair': 'bch_btc',
                            'val': 2.13
                        },
                        'min': {
                            'exchange': 'bittrex',
                            'pair': 'lsk_btc',
                            'val': 0.01
                        }
                    },
                    'byLastPrice': {
                        'max': {
                            'exchangeHigh': 'cex',
                            'exchangeLow': 'kraken',
                            'pair': 'bch_usd',
                            'val': 4.16
                        },
                        'min': {
                            'exchangeHigh': 'bittrex',
                            'exchangeLow': 'bitfinex',
                            'pair': 'neo_btc',
                            'val': 0.05
                        }
                    }
                },
                'pairs': spreads_by_pairs
            },
            'updated': {
                'readable': "Thursday, November 9th 2017, 4:24:05 pm"
            }
        }}]
    }, namespace='/chat')

@sio.on('chat message', namespace='/chat')
async def message(sid, data):
    print("message ", data)
    await sio.emit('reply', room=sid)

@sio.on('disconnect', namespace='/chat')
def disconnect(sid):
    print('disconnect ', sid)

app.router.add_static('/static', 'html')
app.router.add_get('/', index)

if __name__ == '__main__':
    web.run_app(app)

# -*- coding: utf-8 -*-

from aiohttp import web
import socketio

import asyncio
import os
import sys
from time import time
import yaml
from influxdb import InfluxDBClient

import ccxt.async as ccxt # noqa: E402
import pdb, traceback, code
import pickle
import aiohttp.client_exceptions
import logging

# make debug log

# арбитраж между тайскими биржами
# lowestAsk, highestBid
# bid - покупка, ask - продажа (дороже)

# - проверка что кошелек доступен для ввода-вывода
# для yobit = ex.privatePostGetDepositAddress('EXP')
# >>> ex.privatePostGetDepositAddress({'coinName': 'EXP'})
# попробовать withdrawal ошибочный или пустой, который точно не должен сработать (на 0 балансе)
#ccxt.errors.ExchangeError: yobit {"success":0,"error":"No free addresses for such currency. Please try again in 2 minutes."}
# недоступный кошелек на poloniex
# >>> c = ex.publicGetReturnCurrencies()
# >>> c['XVC']
# {'id': 253, 'name': 'Vcash', 'txFee': '0.01000000', 'minConf': 1, 'depositAddress': None, 'disabled': 1, 'delisted': 0, 'frozen': 0}


# - доступный обьем для покупки / продажи
# - проценты за покупку-продажу и за перевод
# - сколько времени он уже доступен (понять успею ли купить-продать), как расчитать что успею продать если буду делать перевод
# проверка символов, что бы не было таких выдач:
#pair BTS/BTC spread 0.01749059 (177209.625%) exchanges: poloniex/bittrex
#buy for 0.00000987 at poloniex, sell for 0.01750046 at bittrex
# - указывать торговую операцию с обьемом и доход с учетом обьема (в usd)

# exchange_ids = ['poloniex', 'bittrex', 'bitfinex', 'bitstamp', 'cryptopia', 'exmo', 'liqui', 'quoine', 'nova', 'livecoin',\
#                 'hitbtc2','coincheck', 'bleutrade', 'bitmex']
# TODO: fix bitfinex rate limit
# TODO: add bitshares dex
exchange_ids = ['poloniex', 'hitbtc2', 'bittrex', 'exmo', 'liqui', 'binance']
exchanges = {}
coins = {}
cheapest_ask = {}
high_bid = {}
current_pair = 0

config = yaml.safe_load(open("config.yml"))
logger = logging.getLogger('arbit')
logger.setLevel(logging.DEBUG)
fh = logging.FileHandler('arbit.log')
fh.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)


if config['use_cached_data']:
    file = open('cache.txt', 'rb')
    try:
        cached_data = pickle.load(file)
    except EOFError:
        cached_data = {}

poloniex_currencies = None
async def poloniex_wallet_disabled(self, currency):
    global poloniex_currencies
    # TODO: cache this query
    if poloniex_currencies == None: poloniex_currencies = await self.publicGetReturnCurrencies()
    return poloniex_currencies[currency]['disabled'] == 1

if config['check_wallets']: ccxt.poloniex.wallet_disabled = poloniex_wallet_disabled

sio = socketio.AsyncServer()
app = web.Application()
sio.attach(app)

def debug(message):
    # print(message)
    pass

def save_wallet_disabled(exchange, currency, value):
    if config['use_cached_data']:
        if exchange not in cached_data['wallet_disabled']:
            cached_data['wallet_disabled'][exchange] = {}
        cached_data['wallet_disabled'][exchange][currency] = {'timestamp': time(), 'value': value}

# TODO: cache it for 1 hour
async def yobit_wallet_disabled(self, currency):
    if config['use_cached_data']:
        if not 'wallet_disabled' in cached_data:
            cached_data['wallet_disabled'] = {}
        if 'yobit' in cached_data['wallet_disabled'] and currency in cached_data['wallet_disabled']['yobit'] \
            and (cached_data['wallet_disabled']['yobit'][currency]['timestamp'] + \
                config['query_base_prices']['cache_expire_in']) > time():
            return cached_data['wallet_disabled']['yobit'][currency]['value']
    try:
        await self.privatePostGetDepositAddress({'coinName': currency})
    except ccxt.errors.ExchangeError as error:
        #print(error)
        save_wallet_disabled('yobit', currency, True)
        return True
    else:
        save_wallet_disabled('yobit', currency, False)
        return False

if config['check_wallets']: ccxt.yobit.wallet_disabled = yobit_wallet_disabled

# hitbtc проверять фьючерсы это или нет
# GET /api/2/public/currency/{currency}
# payinEnabled	Boolean	Is allowed for deposit (false for ICO)
# crypto	Boolean	Is currency belongs to blockchain (false for ICO and fiat, like EUR)

hitbtc2_currencies = None

async def hitbtc2_wallet_disabled(self, currency):
    # TODO: cache this query
    global hitbtc2_currencies
    if hitbtc2_currencies == None: hitbtc2_currencies = await self.publicGetCurrency()
    for row in hitbtc2_currencies:
        if currency == row['id']:
            return row['payinEnabled'] == False
    raise(Exception('currency not found'))

if config['check_wallets']: ccxt.hitbtc2.wallet_disabled = hitbtc2_wallet_disabled

for id in exchange_ids:
    exchanges[id] = getattr(ccxt, id)({**{'enableRateLimit': True}, **(config['exchanges'][id] if id in config['exchanges'] else {})})

markets_error = 0
markets_success = 0

async def get_markets(id):
    global markets_error, markets_success
    logger.info("load markets for %s" % id)
    try:
        await exchanges[id].load_markets()
    except(ccxt.errors.ExchangeNotAvailable, ccxt.errors.DDoSProtection, ccxt.errors.ExchangeError):
        logger.error("exchange %s is not available" % id)
        markets_error += 1
    except ccxt.errors.RequestTimeout: # retry?
        logger.error("exchange %s timed out" % id)
        markets_error += 1
    markets_success += 1
    return [id, exchanges[id].symbols]

orders_error = orders_success = 0

async def get_orders(id, markets):
    global current_request, orders_error, orders_success
    current_market = 1
    logger.info("load orders for %s" % id)
    orders = {}
    while True:
        for market in markets:
            try:
                result = await exchanges[id].fetch_order_book(market)
            except ccxt.errors.RequestTimeout:
                print("%s for %s timeout" % (id, market))
                orders_error += 1
            except TypeError:
                print("%s for %s type error" % (id, market))
                orders_error += 1
            except ccxt.errors.ExchangeError:
                print("%s for %s exchange error" % (id, market))
                orders_error += 1
            except ccxt.errors.DDoSProtection:
                print("%s for %s rate limit" % (id, market))
                orders_error += 1
            except aiohttp.client_exceptions.ClientOSError:
                print("%s for %s connection reset" % (id, market))
                orders_error += 1
            except ccxt.errors.ExchangeNotAvailable:
                print("%s for %s exchange error" % (id, market))
                orders_error += 1
            else:
                debug("%s/%s got %s for %s (%s/%s)" % (current_request, total_requests, market, id,
                                                       current_market, len(markets)))
                #print("got ZRX/BTC for hitbtc2 (got first time)")
                #print("got ZRX/BTC for hitbtc2 (last update at 12:30:33, got 3rd time)")
                orders[market] = result
                yield [id, market, result]
                orders_success += 1
            current_request += 1
            current_market += 1

loop = asyncio.get_event_loop()

if not config['update_cached_data'] and config['use_cached_data'] and 'all_markets' in cached_data:
    all_markets = cached_data['all_markets']
else:
    all_markets = loop.run_until_complete(asyncio.gather(*[asyncio.ensure_future(get_markets(id)) for id in exchange_ids]))

for exchange_id, markets in all_markets:
    if markets == None: continue
    for market in markets:
        if market in coins:
            coins[market] += [exchange_id]
        else:
            coins[market] = [exchange_id]

new_coins = {}

for pair in coins:
    #if pair == 'DASH/BTC': new_coins[pair] = coins[pair]
    if len(coins[pair]) > 1 and (pair.split('/')[1] not in ['USD', 'EUR', 'CNY']): new_coins[pair] = coins[pair]
    #if len(new_coins) > 10: break
total_pairs = len(new_coins.keys())

# make pairs by exchange
coins_by_exchange = {}

for market, exchanges_ids in new_coins.items():
    for exchange in exchanges_ids:
        if exchange in coins_by_exchange:
            coins_by_exchange[exchange] += [market]
        else:
            coins_by_exchange[exchange] = [market]


total_requests = len([item for sublist in coins_by_exchange.values() for item in sublist])
current_request = 1

arbitrage_stats = {}

lowestAskPair = {}
highestBidPair = {}
exchangeAsk = {}
exchangeBid = {}
spreads_by_pairs = {}

async def send_update(pair):
    if pair not in arbitrage_stats:
        # kind of dropping arbitrage
        spreads_by_pairs[pair] = {
            'spreadBidAskMin': [0, 0],
            'spreadBidAskMax': [0, 0],
            'spreadLastPrice': "",
            'spreadLastPriceMaxExchange': [0, 0],
            'spreadLastPriceMinExchange': [0, 0],
        }
    else:
        spreads_by_pairs[pair] = {
            'spreadBidAskMin': ["%.2f" % arbitrage_stats[pair]['lowestBASpread'], arbitrage_stats[pair]['arbitrage']['lowestAskExchange']],
            'spreadBidAskMax': ["%.2f" % arbitrage_stats[pair]['highestBASpread'], arbitrage_stats[pair]['arbitrage']['highestBidExchange']],
            'spreadLastPrice': "%.2f" % float(arbitrage_stats[pair]['arbitrage']['spread_percent']),
            'spreadLastPriceMaxExchange': ["%.8f" % arbitrage_stats[pair]['arbitrage']['highestBidPrice'], arbitrage_stats[pair]['arbitrage']['highestBidExchange']],
            'spreadLastPriceMinExchange': ["%.8f" % arbitrage_stats[pair]['arbitrage']['lowestAskPrice'], arbitrage_stats[pair]['arbitrage']['lowestAskExchange']],
        }

    update_time = int(time())

    logger.info("send update!!!")

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
            {update_time: [
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
        'data': [{update_time: {
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


async def calculate_arbitrage2(pair):
    if pair in lowestAskPair and pair in highestBidPair and lowestAskPair[pair][1] != highestBidPair[pair][1]:
        spread = highestBidPair[pair][0] - lowestAskPair[pair][0]
        spread_percent = spread / (lowestAskPair[pair][0] / 100)
        if not await check_wallets(pair, [lowestAskPair[pair][1],highestBidPair[pair][1]]):
            last_arbitrage = {
                'spread': spread,
                'spread_percent': spread_percent,
                'lowestAskPrice': lowestAskPair[pair][0],
                'highestBidPrice': highestBidPair[pair][0],
                'lowestAskExchange': lowestAskPair[pair][1],
                'highestBidExchange': highestBidPair[pair][1],
            }
            # TODO: store most old exchange record to arbitrage updated time
            # TODO: also update time when arbitrage was not changed
            # TODO: like ETH/BTC for bittrex/poloniex should have updated time for oldest exchange update
            if pair not in arbitrage_stats or arbitrage_stats[pair]['arbitrage'] != last_arbitrage:
                if spread_percent > 1:
                    if pair not in arbitrage_stats:
                        logger.info("found new arbitrage: ")
                    elif arbitrage_stats[pair]['arbitrage'] != last_arbitrage:
                        logger.info("found updated arbitrage: ")

                    updated_time = min(exchange_pair_updated[pair][lowestAskPair[pair][1]],
                        exchange_pair_updated[pair][highestBidPair[pair][1]])

                    arbitrage_stats[pair] = {
                        'time': updated_time,
                        'arbitrage': last_arbitrage,
                        'lowestBASpread': lowestAskPair[pair][2],
                        'highestBASpread': highestBidPair[pair][2]
                    }

                    # show dropped dropped arbitrage (become < 1%)
                    logger.info("pair %s spread %.8f (%.3f%%) exchanges: %s/%s" % (pair,
                          last_arbitrage['spread'], last_arbitrage['spread_percent'],
                          last_arbitrage['lowestAskExchange'], last_arbitrage['highestBidExchange']))
                    logger.info("buy for %.8f at %s, sell for %.8f at %s" %
                          (last_arbitrage['lowestAskPrice'], last_arbitrage['lowestAskExchange'],
                           last_arbitrage['highestBidPrice'], last_arbitrage['highestBidExchange']))
                    await send_update(pair)
                elif pair in arbitrage_stats:
                    logger.info("arbitrage liquidated:")
                    logger.info("pair %s spread %.8f (%.3f%%) exchanges: %s/%s" % (pair,
                          last_arbitrage['spread'], last_arbitrage['spread_percent'],
                          last_arbitrage['lowestAskExchange'], last_arbitrage['highestBidExchange']))
                    logger.info("was alive %.1f seconds" % (time() - arbitrage_stats[pair]['time']))
                    # TODO: save arbitrage history (influxdb)
                    del(arbitrage_stats[pair])
                    await send_update(pair)

async def calculate_arbitrage(pair, exchange_id, lowestAsk, highestBid, BASpread):
    if (not pair in lowestAskPair) or lowestAskPair[pair][0] > lowestAsk or \
        pair in lowestAskPair and lowestAskPair[pair][1] == exchange_id and lowestAskPair[pair][0] < lowestAsk:
        lowestAskPair[pair] = [lowestAsk, exchange_id, BASpread]
        await calculate_arbitrage2(pair)

        # calculate possible arbitrage and send update if changed
    if (not pair in highestBidPair) or highestBidPair[pair][0] < highestBid or \
        pair in highestBidPair and highestBidPair[pair][1] == exchange_id and highestBidPair[pair][0] > highestBid:
        highestBidPair[pair] = [highestBid, exchange_id, BASpread]
        await calculate_arbitrage2(pair)

def calculate_price_by_volume(orderbook):
    prices = []
    total_volume = 0
    for order in orderbook:
        prices.append(order[0])
        total_volume += order[1]
        if total_volume >= config['minimal_volume']: break
    else:
        print("total volume %s instead of %s needed for %s orders" % (total_volume, config['minimal_volume'], len(prices)))

    return sum(prices)/len(prices)

# check if wallet deposit is disabled on exchange
async def check_wallets(pair, wallet_exchanges):
    exchanges_has_check_wallet = list(filter(lambda x: hasattr(exchanges[x], 'wallet_disabled'), wallet_exchanges))
    if len(exchanges_has_check_wallet) > 0:
        for exchange in exchanges_has_check_wallet:
            for currency in pair.split('/'):
                if currency == 'BTC': continue
                try:
                    debug("checking wallet %s at %s" % (currency, exchange))
                    # XXX: use another loop
                    if await exchanges[exchange].wallet_disabled(currency):
                    # if asyncio.get_event_loop().run_until_complete():
                        debug("true")
                        return True
                except ccxt.errors.RequestTimeout:
                    debug("%s request timeout" % exchange)
                    pass
                debug("false")
    return False

async def main(exchange, markets):
    async for (exchange_id, pair, orderbook) in get_orders(exchange, markets):
        logger.debug("got data from %s" % exchange_id)
        # first skip non BTC pairs
        if pair.split('/')[1] != 'BTC': continue
        if not (len(orderbook['asks']) == 0 or len(orderbook['bids']) == 0):
            lowestAsk = calculate_price_by_volume(orderbook['asks'])
            highestBid = calculate_price_by_volume(orderbook['bids'])
            BASpread = (orderbook['asks'][0][0] - orderbook['bids'][0][0]) / (orderbook['asks'][0][0] / 100)
            await calculate_arbitrage(pair, exchange_id, lowestAsk, highestBid, BASpread)

# try:
loop.run_until_complete(asyncio.gather(*([asyncio.ensure_future(main(exchange, markets)) \
                        for exchange, markets in coins_by_exchange.items()]+[asyncio.ensure_future(web.run_app(app))])))

# TODO: save spreads on ctrl-c and load when start
# TODO: show last spreads on connect
# TODO: show spread living time + updated time (n seconds ago)
# except:
#     type, value, tb = sys.exc_info()
#     traceback.print_exc()
#     last_frame = lambda tb=tb: last_frame(tb.tb_next) if tb.tb_next else tb
#     frame = last_frame().tb_frame
#     ns = dict(frame.f_globals)
#     ns.update(frame.f_locals)
#     code.interact(local=ns)

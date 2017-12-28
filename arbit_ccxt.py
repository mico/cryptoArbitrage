# -*- coding: utf-8 -*-

from aiohttp import web
import socketio

import asyncio
import sys
from time import time, mktime
import yaml
from influxdb import InfluxDBClient, DataFrameClient

import ccxt.async as ccxt # noqa: E402
import traceback
import aiohttp.client_exceptions
import logging
import interfaces.hitbtc2
import interfaces.poloniex
import interfaces.bittrex
import numpy
import pandas as pd
import datetime
import functools
import copy

exchange_ids = ['poloniex', 'hitbtc2', 'bittrex']
exchanges = {}
coins = {}
cheapest_ask = {}
high_bid = {}
current_pair = 0
exchange_pair_updated = {}
cached_data = {}
coins_by_exchange = {}
current_request = 1

arbitrage_stats = {}

lowestAskPair = {}
highestBidPair = {}
exchangeAsk = {}
exchangeBid = {}
spreads_by_pairs = {}

last_update_send = 0
last_exchange_update = {}
arbitrage_history = []  # arbitrage profit range, high/low exchange, time found, time was exists
last_influx_pairs_update = 0
influx_pairs = pairs_stats = []
bittrex_currencies = None
hitbtc2_currencies = None
poloniex_currencies = None
markets_error = 0
markets_success = 0
orders_error = orders_success = 0

config = yaml.safe_load(open("config.yml"))
influx_client = DataFrameClient(config['influxdb']['host'], config['influxdb']['port'], config['influxdb']['user'],
                               config['influxdb']['password'], config['influxdb']['database'])

logger = logging.getLogger('arbit')
logger.setLevel(logging.INFO)
fh = logging.FileHandler('arbit.log')
fh.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
# add the handlers to the logger
logger.addHandler(fh)
logger.addHandler(ch)


def save_wallet_disabled(exchange, currency, value):
    if config['use_cached_data']:
        if exchange not in cached_data['wallet_disabled']:
            cached_data['wallet_disabled'][exchange] = {}
        cached_data['wallet_disabled'][exchange][currency] = {'timestamp': time(), 'value': value}


if config['check_wallets']:
    async def bittrex_wallet_disabled(self, currency):
        # TODO: cache this query
        global bittrex_currencies
        for row in bittrex_currencies:
            if currency == row['Currency']:
                return row['IsActive'] is False
        return False

    ccxt.bittrex.wallet_disabled = bittrex_wallet_disabled

    async def hitbtc2_wallet_disabled(self, currency):
        # TODO: cache this query
        global hitbtc2_currencies
        for row in hitbtc2_currencies:
            if currency == row['id']:
                return row['payinEnabled'] is False or row['payoutEnabled'] is False
        return False

    ccxt.hitbtc2.wallet_disabled = hitbtc2_wallet_disabled

    async def poloniex_wallet_disabled(self, currency):
        global poloniex_currencies
        return poloniex_currencies[currency]['disabled'] == 1

    ccxt.poloniex.wallet_disabled = poloniex_wallet_disabled

    async def yobit_wallet_disabled(self, currency):
        if config['use_cached_data']:
            if 'wallet_disabled' not in cached_data:
                cached_data['wallet_disabled'] = {}
            if 'yobit' in cached_data['wallet_disabled'] and currency in cached_data['wallet_disabled']['yobit'] \
                and (cached_data['wallet_disabled']['yobit'][currency]['timestamp'] +
                     config['query_base_prices']['cache_expire_in']) > time():
                return cached_data['wallet_disabled']['yobit'][currency]['value']
        try:
            await asyncio.ensure_future(self.privatePostGetDepositAddress({'coinName': currency}))
        except ccxt.errors.ExchangeError as error:
            save_wallet_disabled('yobit', currency, True)
            return True
        else:
            save_wallet_disabled('yobit', currency, False)
            return False

    ccxt.yobit.wallet_disabled = yobit_wallet_disabled


async def get_markets(id):
    global markets_error, markets_success
    logger.info("load markets for %s" % id)
    try:
        await exchanges[id].load_markets()
    except(ccxt.errors.ExchangeNotAvailable, ccxt.errors.DDoSProtection, ccxt.errors.ExchangeError) as error:
        logger.error("exchange %s is not available (%s)" % (id, error))
        markets_error += 1
    except ccxt.errors.RequestTimeout: # retry?
        logger.error("exchange %s timed out" % id)
        markets_error += 1
    markets_success += 1
    return [id, exchanges[id].symbols]


async def fetch_order_book(id, market):
    global current_request, orders_error, orders_success

    try:
        result = await exchanges[id].fetch_order_book(market)
    except ccxt.errors.RequestTimeout:
        logger.error("%s for %s timeout" % (id, market))
        orders_error += 1
    except TypeError:
        logger.error("%s for %s type error" % (id, market))
        orders_error += 1
    except ccxt.errors.ExchangeError:
        logger.error("%s for %s exchange error" % (id, market))
        orders_error += 1
    except ccxt.errors.DDoSProtection as error:
        logger.error("%s for %s rate limit (%s)" % (id, market, error))
        orders_error += 1
    except aiohttp.client_exceptions.ClientOSError:
        logger.error("%s for %s connection reset" % (id, market))
        orders_error += 1
    except ccxt.errors.ExchangeNotAvailable:
        logger.error("%s for %s exchange error" % (id, market))
        orders_error += 1
    except ConnectionResetError:
        logger.error("%s for %s exchange connection error" % (id, market))
        orders_error += 1
    else:
        logger.debug("%s got %s for %s" % (current_request, market, id
                                               ))
        current_request += 1
        return [market, result]
    return [market, []] # exception happens


async def get_orders(id, markets):
    global current_request, orders_error, orders_success
    total_markets = len(markets)
    logger.info("load orders for %s" % id)
    orders = {}
    finished_times = 0
    while True:
        # async for (exchange_id, pair, orderbook) in get_orders(exchange, markets):
        start_time = time()
        current_market = 1
        success_markets = 0
        error_markets = 0
        tasks = [fetch_order_book(id, market) for market in markets]
        for market, result in await asyncio.gather(*tasks):
            logger.debug("getting %s (%s/%s) for %s" % (market, current_market, total_markets, id))
            if market not in exchange_pair_updated:
                exchange_pair_updated[market] = {id: time()}
            else:
                exchange_pair_updated[market][id] = time()
            orders[market] = result
            current_market += 1
            if len(result) == 0:
                error_markets += 1
            else:
                success_markets += 1
            yield [id, market, result]
        if success_markets != 0: finished_times += 1
        logger.info("(%s/%s) %s finished %s times, eplased %s sec" % (len(markets), success_markets, id, finished_times, (time() - start_time)))


async def send_status_update():
    while True:
        await sio.emit('status', {
            'lastExchangeUpdates': last_exchange_update
        }, namespace='/chat')
        await asyncio.sleep(1)

async def send_arbitrage_history(data, room=None):
    await sio.emit('history', data, namespace='/chat', room=room)

async def send_update(pair, room=None):
    global last_exchange_update
    if pair not in arbitrage_stats:
        # kind of dropping arbitrage
        spreads_by_pairs[pair] = {
            'spreadBidAskMin': [0, 0],
            'spreadBidAskMax': [0, 0],
            'spreadLastPrice': "",
            'spreadLastPriceMaxExchange': [0, 0],
            'spreadLastPriceMinExchange': [0, 0],
            'lastUpdated': time()
        }
    elif pair is not None:
        spreads_by_pairs[pair] = {
            'spreadBidAskMin': ["%.2f" % arbitrage_stats[pair]['lowestBASpread'], arbitrage_stats[pair]['arbitrage']['lowestAskExchange']],
            'spreadBidAskMax': ["%.2f" % arbitrage_stats[pair]['highestBASpread'], arbitrage_stats[pair]['arbitrage']['highestBidExchange']],
            'spreadLastPrice': "%.2f" % float(arbitrage_stats[pair]['arbitrage']['spread_percent']),
            'spreadLastPriceMaxExchange': ["%.8f" % arbitrage_stats[pair]['arbitrage']['highestBidPrice'], arbitrage_stats[pair]['arbitrage']['highestBidExchange']],
            'spreadLastPriceMinExchange': ["%.8f" % arbitrage_stats[pair]['arbitrage']['lowestAskPrice'], arbitrage_stats[pair]['arbitrage']['lowestAskExchange']],
            'lastUpdated': int(arbitrage_stats[pair]['updated']),
            'timeFound': int(arbitrage_stats[pair]['time_found']),
        }

    update_time = int(time())

    await sio.emit('publicView', {
        'data': [{update_time: {'spreads': {'pairs': spreads_by_pairs}}}],
        'influx_pairs': await get_pairs_from_influx()
    }, namespace='/chat', room=room)

def any_exchange_changed(last_arbitrage, previous_arbitrage):
    return last_arbitrage['lowestAskExchange'] != previous_arbitrage['lowestAskExchange'] or \
           last_arbitrage['highestBidExchange'] != previous_arbitrage['highestBidExchange']

def prepare_spreads(stats):
    start_time = int(stats['spread_history'][0][0])
    end_time = int(stats['spread_history'][-1][0])
    periods = end_time - start_time + 1
    dt = pd.date_range(datetime.datetime.utcfromtimestamp(start_time), periods=periods, freq='1s')
    current_index = 0
    data = [None] * periods
    for current_dt in dt:
        for as_row in stats['spread_history']:
            # XXX: slow
            if current_dt.timestamp() == int(as_row[0]):
                data[current_index] = as_row[1]
        current_index += 1

    df = pd.DataFrame(data, columns=["spread"], index=dt)
    return df.ffill()

def calculate_spread(pair, last_arbitrage):
    global arbitrage_stats
    arbitrage_stats[pair]['spread_history'].append([time(), last_arbitrage['spread_percent']])

async def save_to_influx(df, stats):#pair, stats)
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(None, functools.partial(influx_client.write_points, df, 'spreads', tags={
        'lowExchange': stats['arbitrage']['lowestAskExchange'],
        'highExchange': stats['arbitrage']['highestBidExchange'],
        'pair': stats['pair']
    }))
    logger.debug("influx result: %s" % result)

async def get_pairs_from_influx():
    global last_influx_pairs_update, influx_pairs, pairs_stats
    if time() - last_influx_pairs_update > 60:
        #result = await loop.run_in_executor(None, influx_client.query, "show tag values with key = pair")
        result = await loop.run_in_executor(None, influx_client.query,
            "select mean(spread), max(spread), count(spread) from spreads where time > now() - 24h group by pair")
# (Pdb) pp res.items()[0][0]
# ('spreads', {'pair': 'BTCD/BTC'})
# (Pdb) pp list(res.items()[0][1])
# [{'count': 1,
#   'mean': 2.336122613790616,
#   'time': '2017-12-18T12:06:32.772818842Z'}]

        influx_pairs = dict([[row[0][1][0][1], {'count': int(row[1]['count'][0]), 'mean': float(row[1]['mean'][0]), 'max': float(row[1]['max'][0])}] for row in result.items()])

        result = await loop.run_in_executor(
            None, influx_client.query,
            "select mean(spread), max(spread), count(spread) from spreads where time > now() - 24h group by pair, highExchange, lowExchange"
        )
        #import pdb; pdb.set_trace()
        pairs_stats = [dict(row[0][1] + (
            ('count', int(row[1]['count'][0])),
            ('mean', float(row[1]['mean'][0])),
            ('max', float(row[1]['max'][0]))
        )) for row in result.items()]
        last_influx_pairs_update = time()
    return {'pairs': pairs_stats, 'general': influx_pairs}

def is_exchanges_updated(exchanges):
    global last_exchange_update
    for exchange in exchanges:
        if last_exchange_update[exchange] + 10 < time():
            return False
    return True

async def arbitrage_liquidate(stats, pair):
    global arbitrage_history, arbitrage_stats
    logger.debug("was alive %.1f seconds" % (time() - stats['updated']))
    # TODO: save arbitrage history (influxdb) before drop
    stats['finished'] = time()
    stats['pair'] = pair
    # add last value to history until current time to make correct spread in DataFrame
    if int(stats['spread_history'][-1][0]) < int(stats['finished']) - 1:
        stats['spread_history'].append([int(stats['finished'])-1, stats['spread_history'][-1][1]])
    if len(stats['spread_history']) > 0 and \
            is_exchanges_updated([stats['arbitrage'][a] for a in ['highestBidExchange', 'lowestAskExchange']]):
        df = prepare_spreads(stats)
        stats['average_spread'] = df.mean()['spread']
        # make sure previous task was completed

        await save_to_influx(df, stats)
        # add to history only if more than 50 seconds
        if (time() - stats['time_found']) > 50:
            arbitrage_history.append(stats)
            if len(arbitrage_history) > 100:
                arbitrage_history = arbitrage_history[-100:]
            await send_arbitrage_history(stats)
    if pair in arbitrage_stats:
        del(arbitrage_stats[pair])


def arbitrage_update(pair, last_arbitrage, updated_time):
    global arbitrage_stats, lowestAskPair, highestBidPair
    logger.debug("found updated arbitrage: ")

    calculate_spread(pair, last_arbitrage)

    arbitrage_stats[pair]['updated'] = updated_time
    arbitrage_stats[pair]['arbitrage'] = last_arbitrage
    arbitrage_stats[pair]['lowestBASpread'] = lowestAskPair[pair][2]
    arbitrage_stats[pair]['highestBASpread'] = highestBidPair[pair][2]
    if last_arbitrage['spread'] > arbitrage_stats[pair]['max_spread']:
        arbitrage_stats[pair]['max_spread'] = last_arbitrage['spread']
    if last_arbitrage['spread'] < arbitrage_stats[pair]['min_spread']:
        arbitrage_stats[pair]['min_spread'] = last_arbitrage['spread']


def arbitrage_new(pair, last_arbitrage, updated_time):
    global arbitrage_stats

    arbitrage_stats[pair] = {
        'updated': updated_time,
        'time_found': time(),
        'arbitrage': last_arbitrage,
        'lowestBASpread': lowestAskPair[pair][2],
        'highestBASpread': highestBidPair[pair][2],
        'max_spread': last_arbitrage['spread'],
        'min_spread': last_arbitrage['spread'],
        'spread_history': [],
        'last_spread_by_period': [time(), [last_arbitrage['spread_percent']]]
    }
    calculate_spread(pair, last_arbitrage)

async def calculate_arbitrage2(pair):
    global arbitrage_history, arbitrage_stats
    try:
        if pair in lowestAskPair and pair in highestBidPair and lowestAskPair[pair][1] != highestBidPair[pair][1]:
            spread = highestBidPair[pair][0] - lowestAskPair[pair][0]
            spread_percent = spread / (lowestAskPair[pair][0] / 100)
            wallet_disabled = await check_wallets(pair, [lowestAskPair[pair][1],highestBidPair[pair][1]])
            if not wallet_disabled:
                last_arbitrage = {
                    'spread': spread,
                    'spread_percent': spread_percent,
                    'lowestAskPrice': lowestAskPair[pair][0],
                    'highestBidPrice': highestBidPair[pair][0],
                    'lowestAskExchange': lowestAskPair[pair][1],
                    'highestBidExchange': highestBidPair[pair][1],
                }
                updated_time = min(exchange_pair_updated[pair][lowestAskPair[pair][1]],
                                   exchange_pair_updated[pair][highestBidPair[pair][1]])
                if pair not in arbitrage_stats or arbitrage_stats[pair]['arbitrage'] != last_arbitrage:
                    if spread_percent > 1:
                        if pair not in arbitrage_stats or any_exchange_changed(last_arbitrage, arbitrage_stats[pair]['arbitrage']):
                            logger.debug("found new arbitrage: ")
                            arbitrage_new(pair, last_arbitrage, updated_time)

                        elif arbitrage_stats[pair]['arbitrage'] != last_arbitrage:
                            arbitrage_update(pair, last_arbitrage, updated_time)

                        # log arbitrage found or updated
                        logger.debug("pair %s spread %.8f (%.3f%%) exchanges: %s/%s" % (pair,
                              last_arbitrage['spread'], last_arbitrage['spread_percent'],
                              last_arbitrage['lowestAskExchange'], last_arbitrage['highestBidExchange']))
                        logger.debug("buy for %.8f at %s, sell for %.8f at %s" %
                              (last_arbitrage['lowestAskPrice'], last_arbitrage['lowestAskExchange'],
                               last_arbitrage['highestBidPrice'], last_arbitrage['highestBidExchange']))

                        await send_update(pair)  # send update or found
                    elif pair in arbitrage_stats:
                        await arbitrage_liquidate(copy.copy(arbitrage_stats[pair]), pair)
                        await send_update(pair)

                        logger.debug("arbitrage liquidated:")
                        logger.debug("pair %s spread %.8f (%.3f%%) exchanges: %s/%s" % (pair,
                                     last_arbitrage['spread'], last_arbitrage['spread_percent'],
                                     last_arbitrage['lowestAskExchange'], last_arbitrage['highestBidExchange']))

                elif pair in arbitrage_stats:
                    arbitrage_stats[pair]['updated'] = updated_time
                    await send_update(pair)  # send updated time for same data
    except Exception as err:
        logger.error(err)
        logger.error(traceback.print_exc())
        raise

async def getLowest(pair, exchange_id, lowestAsk, highestBid, BASpread):
    try:
        if (not pair in lowestAskPair) or lowestAskPair[pair][0] > lowestAsk or \
            pair in lowestAskPair and lowestAskPair[pair][1] == exchange_id and lowestAskPair[pair][0] < lowestAsk:
            lowestAskPair[pair] = [lowestAsk, exchange_id, BASpread]
            await calculate_arbitrage2(pair)
    except Exception as err:
        print("error!!!: %s" % err)


async def getHighest(pair, exchange_id, lowestAsk, highestBid, BASpread):
    try:
        if (not pair in highestBidPair) or highestBidPair[pair][0] < highestBid or \
            pair in highestBidPair and highestBidPair[pair][1] == exchange_id and highestBidPair[pair][0] > highestBid:
            highestBidPair[pair] = [highestBid, exchange_id, BASpread]
            await calculate_arbitrage2(pair)
    except Exception as err:
        print("error!!!: %s" % err)


async def calculate_arbitrage(pair, exchange_id, lowestAsk, highestBid, BASpread):
    try:
        await asyncio.gather(*[getLowest(pair, exchange_id, lowestAsk, highestBid, BASpread),
                               getHighest(pair, exchange_id, lowestAsk, highestBid, BASpread)])
    except Exception as err:
        print("ERR!!! %s" % err)

def calculate_price_by_volume(currency, orderbook):
    prices = []
    total_volume = 0
    for order in orderbook:
        prices.append(float(order[0]))
        total_volume += (float(order[0]) * float(order[1]))
        if total_volume >= config['minimal_volume'][currency]:
            break
    else:
        logger.debug("total volume %s instead of %s needed for %s orders" % (total_volume,
                     config['minimal_volume'][currency], len(prices)))
    return sum(prices)/len(prices)


# check if wallet deposit is disabled on exchange
async def check_wallets(pair, wallet_exchanges):
    exchanges_has_check_wallet = list(filter(lambda x: hasattr(exchanges[x], 'wallet_disabled'),
                                      wallet_exchanges))
    if len(exchanges_has_check_wallet) > 0:
        for exchange in exchanges_has_check_wallet:
            for currency in pair.split('/'):
                if currency == 'BTC':
                    continue
                try:
                    logger.debug("checking wallet %s at %s" % (currency, exchange))
                    if await exchanges[exchange].wallet_disabled(currency):
                        logger.debug("wallet %s at %s disabled" % (currency, exchange))
                        return True
                except ccxt.errors.RequestTimeout:
                    logger.debug("%s request timeout" % exchange)
                    pass
                logger.debug("false")
    return False

fail_time = None

def check_exchange_updated():
    global last_exchange_update, fail_time
    for exchange, updated_at in last_exchange_update.items():
        if (updated_at + 30) < time():
            if fail_time is None:
                fail_time = time()
            elif fail_time + 60 < time():
                logger.error("!!! %s didn't update for a long time" % exchange)
                import pdb; pdb.set_trace()
            return
    fail_time = None

async def main_websocket(exchange, markets):
    global exchange_pair_updated, last_exchange_update
    while True:
        try:
            ex = getattr(getattr(interfaces, exchange), exchange)()

            async for (exchange_id, orderbook, updated_pair) in ex.websocket_run(markets):
                check_exchange_updated()
                if updated_pair not in exchange_pair_updated:
                    exchange_pair_updated[updated_pair] = {exchange: time()}
                else:
                    exchange_pair_updated[updated_pair][exchange] = time()
                last_exchange_update[exchange] = time()
                # print("got %s from %s" % (updated_pair, exchange_id))
                if updated_pair.split('/')[1] not in config['minimal_volume'].keys(): continue
                if len(orderbook) > 0 and (not (len(orderbook['asks']) == 0 or len(orderbook['bids']) == 0)):
                    #print("got %s from %s" % (updated_pair, exchange_id))
                    lowestAsk = calculate_price_by_volume(updated_pair.split('/')[1], orderbook['asks'])
                    highestBid = calculate_price_by_volume(updated_pair.split('/')[1], orderbook['bids'])
                    BASpread = (float(orderbook['asks'][0][0]) - float(orderbook['bids'][0][0])) / (float(orderbook['asks'][0][0]) / 100)
                    await calculate_arbitrage(updated_pair, exchange_id, lowestAsk, highestBid, BASpread)
        except Exception as err:
            logger.error(sys.exc_info()[0])
            logger.error(traceback.print_exc())
            #raise
            await asyncio.sleep(1)


async def get_exchange_currencies():
    global poloniex_currencies, hitbtc2_currencies, bittrex_currencies
    if 'poloniex' in exchange_ids:
        # TODO: update every 10 minutes
        poloniex_currencies = await exchanges['poloniex'].publicGetReturnCurrencies()
    if 'hitbtc2' in exchange_ids:
        hitbtc2_currencies = await exchanges['hitbtc2'].publicGetCurrency()
    if 'bittrex' in exchange_ids:
        bittrex_currencies = await exchanges['bittrex'].publicGetCurrencies()
        bittrex_currencies = bittrex_currencies['result']


async def update_exchange_data(loop=False):
    if loop:
        while True:
            await asyncio.sleep(600)
            await get_exchange_currencies()
    else:
        await get_exchange_currencies()


async def background_task():
    await update_exchange_data()
    # lock here until first finish
    asyncio.gather(update_exchange_data(True))
    await get_pairs_from_influx()
    for exchange, markets in coins_by_exchange.items():
        asyncio.gather(asyncio.ensure_future(main_websocket(exchange, markets)), return_exceptions=True)
    asyncio.gather(asyncio.ensure_future(send_status_update()), return_exceptions=True)


if __name__ == '__main__':
    for id in exchange_ids:
        exchanges[id] = getattr(ccxt, id)({**{'timeout': 20000, 'enableRateLimit': True},
                                           **(config['exchanges'][id] if id in config['exchanges'] else {})})

    loop = asyncio.get_event_loop()

    if not config['update_cached_data'] and config['use_cached_data'] and 'all_markets' in cached_data:
        all_markets = cached_data['all_markets']
    else:
        all_markets = loop.run_until_complete(asyncio.gather(
            *[asyncio.ensure_future(get_markets(id)) for id in exchange_ids])
        )

    for exchange_id, markets in all_markets:
        if markets is None:
            continue
        for market in markets:
            if market in coins:
                coins[market].append(exchange_id)
            else:
                coins[market] = [exchange_id]

    new_coins = {}

    for pair in coins:
        if len(coins[pair]) > 1 and (pair.split('/')[1] in config['minimal_volume'].keys()):
            new_coins[pair] = coins[pair]
    total_pairs = len(new_coins.keys())
    logger.info("found %s pairs for arbitrage" % total_pairs)
    if total_pairs < 1:
        logger.info("nothing for arbitrage, exit.")
        sys.exit(1)

    # make pairs by exchange

    for market, exchanges_ids in new_coins.items():
        for exchange in exchanges_ids:
            if exchange in coins_by_exchange:
                coins_by_exchange[exchange].append(market)
            else:
                coins_by_exchange[exchange] = [market]

    sio = socketio.AsyncServer()
    app = web.Application()
    sio.attach(app)

    # send current arbitrage and history data
    @sio.on('connect', namespace='/chat')
    async def connect(sid, environ):
        global arbitrage_history
        await send_update(None, sid)
        for data in arbitrage_history:
            await send_arbitrage_history(data, sid)

    sio.start_background_task(background_task)
    web.run_app(app, port=8081)

# TODO: try OrderedDict

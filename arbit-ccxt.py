# -*- coding: utf-8 -*-

import asyncio
import os
import sys
import time
import yaml

import ccxt.async as ccxt # noqa: E402
import pdb
import pickle
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

exchange_ids = ['poloniex', 'yobit', 'bittrex', 'bitfinex', 'bitstamp', 'cryptopia', 'exmo', 'liqui', 'quoine', 'nova', 'livecoin',\
                'hitbtc', 'coincheck', 'bleutrade', 'bitmex']
exchanges = {}
coins = {}
cheapest_ask = {}
high_bid = {}
current_pair = 0

config = yaml.safe_load(open("config.yml"))

async def poloniex_wallet_disabled(self, currency):
    # TODO: cache this query
    currencies = await self.publicGetReturnCurrencies()
    return currencies[currency]['disabled'] == 1

ccxt.poloniex.wallet_disabled = poloniex_wallet_disabled

async def yobit_wallet_disabled(self, currency):
    try:
        await self.privatePostGetDepositAddress({'coinName': currency})
    except ccxt.errors.ExchangeError as error:
        #print(error)
        return True
    else:
        return False

ccxt.yobit.wallet_disabled = yobit_wallet_disabled

# можно одновременно со всех бирж тянуть ордера, будет быстрее в 6 раз
# вместо 200, 40 запросов
# если использовать 10 прокси, будет 4 запроса

for id in exchange_ids:
    exchanges[id] = getattr(ccxt, id)({**{'enableRateLimit': True}, **(config['exchanges'][id] if id in config['exchanges'] else {})})

async def get_markets(id):
    print("load markets for %s" % id)
    #exchanges[id] = getattr(ccxt, id)({**{'enableRateLimit': True}, **(config['exchanges'][id] if id in config['exchanges'] else {})})
    try:
        await exchanges[id].load_markets()
    except(ccxt.errors.ExchangeNotAvailable, ccxt.errors.DDoSProtection, ccxt.errors.ExchangeError):
        print("exchange %s is not available" % id)
    except ccxt.errors.RequestTimeout: # retry?
        print("exchange %s timed out" % id)
    return [id, exchanges[id].symbols]

async def get_orders(id, markets):
    global current_request
    current_market = 1
    print("load orders for %s" % id)
    orders = {}
    for market in markets:
        try:
            result = await exchanges[id].fetch_order_book(market)
        except ccxt.errors.RequestTimeout:
            print("%s for %s timeout" % (id, market))
        except TypeError:
            print("%s for %s type error" % (id, market))
        except ccxt.errors.ExchangeError:
            print("%s for %s exchange error" % (id, market))
        except ccxt.errors.DDoSProtection:
            print("%s for %s rate limit" % (id, market))
        else:
            print("%s/%s got %s for %s (%s/%s)" % (current_request, total_requests, market, id, current_market, len(markets)))
            orders[market] = result
        current_request += 1
        current_market += 1
    return [id, orders]

loop = asyncio.get_event_loop()

if config['use_cached_data']:
    file = open('cache.txt', 'rb')
    cached_data = pickle.load(file)
    all_markets = cached_data['all_markets']
else:
    all_markets = loop.run_until_complete(asyncio.gather(*[asyncio.ensure_future(get_markets(id)) for id in exchange_ids]))

# TODO: cache it

for exchange_id, markets in all_markets:
    if markets == None: continue
    for market in markets:
        if market in coins:
            coins[market] += [exchange_id]
        else:
            coins[market] = [exchange_id]

#print("poloniex XVC disabled? %s" % exchanges['poloniex'].wallet_disabled('XVC'))
#pdb.set_trace()

new_coins = {}

for pair in coins:
    #if pair == 'DASH/BTC': new_coins[pair] = coins[pair]
    if len(coins[pair]) > 1: new_coins[pair] = coins[pair]
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

# TODO: cache it

if config['save_cached_data'] and not config['use_cached_data']:
    all_orders = loop.run_until_complete(asyncio.gather(*[asyncio.ensure_future(get_orders(exchange, markets)) \
        for exchange, markets in coins_by_exchange.items()]))
    file = open('cache.txt', 'wb')
    pickle.dump({'all_markets': all_markets, 'all_orders': all_orders}, file)
    file.close()
else:
    all_orders = cached_data['all_orders']

for exchange_id, orders in all_orders:
        for pair, orderbook in orders.items():
            #print("%s: %s" % (exchange_id, orderbook))
            if not (len(orderbook['asks']) == 0 or len(orderbook['bids']) == 0):
                if (not pair in cheapest_ask) or cheapest_ask[pair][0] > orderbook['asks'][0][0]:
                    cheapest_ask[pair] = [orderbook['asks'][0][0], exchange_id]
                if (not pair in high_bid) or high_bid[pair][0] < orderbook['bids'][0][0]:
                    high_bid[pair] = [orderbook['bids'][0][0], exchange_id]

# считать среднюю цену за указанный обьем в стакане (например все цены на 1btc)
# TODO: делать split пары и проверять обе, если это не BTC
# TODO: отформатировать этот код нормально, что бы читался
for pair in new_coins:
    if pair in high_bid and pair in cheapest_ask:
        spread = high_bid[pair][0] - cheapest_ask[pair][0]
        spread_percent = spread / (cheapest_ask[pair][0] / 100)
        if spread_percent > 1:
            #pdb.set_trace()
            exchanges_check_wallet = list(filter(lambda x: hasattr(exchanges[x], 'wallet_disabled'), \
                [cheapest_ask[pair][1], high_bid[pair][1]]))
            if len(exchanges_check_wallet) == 0 or sum([asyncio.get_event_loop().run_until_complete(exchanges[exchange].wallet_disabled(pair.replace('BTC/', '').replace('/BTC', ''))) for exchange in exchanges_check_wallet]) == 0:
                print("pair %s spread %.8f (%.3f%%) exchanges: %s/%s" % (pair, spread, spread_percent, cheapest_ask[pair][1], high_bid[pair][1]))
                print("buy for %.8f at %s, sell for %.8f at %s" % (cheapest_ask[pair][0], cheapest_ask[pair][1], high_bid[pair][0], high_bid[pair][1]))

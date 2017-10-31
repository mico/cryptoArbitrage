# -*- coding: utf-8 -*-

import asyncio
import os
import sys
import time

import ccxt.async as ccxt # noqa: E402
# lowestAsk, highestBid
# bid - покупка, ask - продажа (дороже)

# - проверка что кошелек доступен для ввода-вывода
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
# btc volume
volume = 0.1
# in %
minimum_spread = 0.5


# можно одновременно со всех бирж тянуть ордера, будет быстрее в 6 раз
# вместо 200, 40 запросов
# если использовать 10 прокси, будет 4 запроса

async def get_markets(id):
    print("load markets for %s" % id)
    exchanges[id] = getattr(ccxt, id)({'enableRateLimit': True})
    try:
        await exchanges[id].load_markets()
    except(ccxt.errors.ExchangeNotAvailable, ccxt.errors.DDoSProtection):
        print("exchange %s is not available" % id)
    return [id, exchanges[id].symbols]

loop = asyncio.get_event_loop()
for exchange_id, markets in loop.run_until_complete(asyncio.gather(*[asyncio.ensure_future(get_markets(id)) for id in exchange_ids])):
    if markets == None: continue
    for market in markets:
        if market in coins:
            coins[market] += [exchange_id]
        else:
            coins[market] = [exchange_id]

new_coins = {}

for pair in coins:
    #if pair == 'DASH/BTC': new_coins[pair] = coins[pair]
    if len(coins[pair]) > 1: new_coins[pair] = coins[pair]
    if len(new_coins) > 100: break
total_pairs = len(new_coins.keys())

# make pairs by exchange
coins_by_exchange = {}

for market, exchanges_ids in new_coins.items():
    for exchange in exchanges_ids:
        if exchange in coins_by_exchange:
            coins_by_exchange[exchange] += [market]
        else:
            coins_by_exchange[exchange] = [market]

async def get_orders(id, markets):
    global current_request
    print("load orders for %s" % id)
    orders = {}
    for market in markets:
        try:
            result = await exchanges[id].fetch_order_book(market)
        except ccxt.errors.RequestTimeout:
            print("%s for %s timeout" % (id, market))
        except TypeError:
            pass
        print("%s/%s got %s for %s" % (current_request, total_requests, market, id))
        current_request += 1
        orders[market] = result
    return [id, orders]

total_requests = len([item for sublist in coins_by_exchange.values() for item in sublist])
current_request = 1

for exchange_id, orders in loop.run_until_complete(asyncio.gather(*[asyncio.ensure_future(get_orders(exchange, markets)) \
    for exchange, markets in coins_by_exchange.items()])):
        for pair, orderbook in orders.items():
            #print("%s: %s" % (exchange_id, orderbook))
            if not (len(orderbook['asks']) == 0 or len(orderbook['bids']) == 0):
                if (not pair in cheapest_ask) or cheapest_ask[pair][0] > orderbook['asks'][0][0]:
                    cheapest_ask[pair] = [orderbook['asks'][0][0], exchange_id]
                if (not pair in high_bid) or high_bid[pair][0] < orderbook['bids'][0][0]:
                    high_bid[pair] = [orderbook['bids'][0][0], exchange_id]

# считать среднюю цену за указанный обьем в стакане (например все цены на 1btc)
for pair in new_coins:
    spread = high_bid[pair][0] - cheapest_ask[pair][0]
    spread_percent = spread / (cheapest_ask[pair][0] / 100)
    if spread_percent > 1:
        print("pair %s spread %.8f (%.3f%%) exchanges: %s/%s" % (pair, spread, spread_percent, cheapest_ask[pair][1], high_bid[pair][1]))
        print("buy for %.8f at %s, sell for %.8f at %s" % (cheapest_ask[pair][0], cheapest_ask[pair][1], high_bid[pair][0], high_bid[pair][1]))

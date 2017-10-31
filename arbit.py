# после нахождения удачной комбинации по price, смотреть по bid/ask, а лучше сразу сравнивать bid/ask в обе стороны!
import requests
import json
import time
import os

minVol = 1 #Minimum volume (In BTC) an exchange should have to be taken into account by this program
exchangedToIgnore = ["hitbtc", "indacoin"]
substitutedNames = {"PINK-btc":"pc-btc"}
alwaysCoins = ["DOGE"]

# XXX: fix BTM mismatching
# Pair: BTM
# Buy at cryptopia for 0.00001318 BTC
# Volume 1.02112844
# Sell at poloniex for 0.00007585 BTC
# Volume 4.0279782499999985
# Potential gain: 475.493%

def getCoinNames(minVol):
  # from poloniex import Poloniex
  # api =  Poloniex()
  coinList = []
  # coins = api.return24hVolume()
  # for market in coins:
  #   if "BTC_" in market and float(coins[market]["BTC"]) > minVol:
  #     coinList.append(market.replace("BTC_","") + "-btc")
  # coinList = [substitutedNames[x] if x in substitutedNames else x for x in coinList]
  output = requests.get("https://www.cryptocompare.com/api/data/coinlist/")
  coins = json.loads(output.content.decode("utf-8"))
  # SortOrder
  for market, data in coins['Data'].items():
      if int(data['SortOrder']) < 100:
        coinList.append(market)
  coinList += alwaysCoins
  return coinList

def getMarketList(pair):
    output = requests.get("https://www.cryptocompare.com/api/data/coinsnapshot/?fsym=" + pair + "&tsym=" + "BTC")
    data = json.loads(output.content.decode("utf-8"))["Data"]
    if len(data) > 0:
      return data["Exchanges"]
    # output = requests.get("https://api.cryptonator.com/api/full/" + pair)
    # markets = json.loads(output.content.decode("utf-8"))["ticker"]["markets"]
    return None

def getLowestHighestMarkets(exchangedToIgnore, minVol, markets):
    lowestMarket = {"price": 10000000000, "volume": 0}
    highestMarket = {"price": 0, "volume": 0}
    for market in markets:
        # print("Market: " + str(market["MARKET"]))
        print("Market data: " + str(market))
        if market["MARKET"].lower() not in exchangedToIgnore:
            market["price"] = marketPrice = float(market["PRICE"])
            market["volume"] = marketVolume = float(market["VOLUME24HOURTO"])

            if float(marketVolume) >= minVol:
                if marketPrice < lowestMarket["price"]:
                    lowestMarket = market

                if marketPrice > highestMarket["price"]:
                    highestMarket = market
    return {"lowestMarket" : lowestMarket, "highestMarket" : highestMarket}

def calcStats(lowestHighestMarkets, pair):
    lowestMarket = lowestHighestMarkets["lowestMarket"]
    highestMarket = lowestHighestMarkets["highestMarket"]
    exchangeUrls = {'yobit' : 'http://yobit.net', 'indacoin' : 'http://indacoin.com', 'kuna' : 'http://en.kuna.com.ua', 'bitstamp' : 'http://bitstamp.net', 'btc-e' : 'http://btc-e.com', 'bittrex' : 'http://bittrex.com', 'cex' : 'http://cex.io', 'bleutrade' : 'http://bleutrade.com', 'exmo' : 'http://exmo.com', 'hitbtc' : 'http://hitbtc.com', 'poloniex' : 'http://poloniex.com', 'bitfinex' : 'http://bitfinex.com', 'livecoin' : 'http://livecoin.net', 'c-cex' : 'http://c-cex.com', 'kraken' :'http://kraken.com'}

    baseCurrency = 'BTC'
    potentialGainPercent = round(highestMarket["price"] / (lowestMarket["price"] / 100) - 100, 3)

    lowestExchangeUrl = lowestMarket["MARKET"].lower()
    highestExchangeUrl = highestMarket["MARKET"].lower()

    lowestExchange = lowestMarket["MARKET"]
    highestExchange = highestMarket["MARKET"]

    lowestPrice = lowestMarket["price"]
    highestPrice = highestMarket["price"]

    return {
        "pair" : pair,
        "baseCurrency" : baseCurrency,
        "potentialGainPercent" : potentialGainPercent,
        "lowestExchangeUrl" : lowestExchangeUrl,
        "highestExchangeUrl" : highestExchangeUrl,
        "lowestPrice" : lowestPrice,
        "highestPrice" : highestPrice,
        "lowestMarket" : lowestMarket,
        "highestMarket" : highestMarket
    }

def getCoinStats():
    coinStats = []
    coinNames = getCoinNames(minVol)
    import os
    for coin in coinNames:
        print(str(round(100 / (len(coinNames) / (coinNames.index(coin) + 1)), 1)) + "%")
        print('getting markets for ' + str(coin))
        markets = getMarketList(coin)
        if markets == None: continue
        lowestHighestMarkets = getLowestHighestMarkets(exchangedToIgnore, minVol, markets)
        if lowestHighestMarkets['lowestMarket']['volume'] == 0: continue
        arbitrageStats = calcStats(lowestHighestMarkets, coin)
        if arbitrageStats["potentialGainPercent"] > 0:
            coinStats.append(arbitrageStats)
    return coinStats

coinStats = getCoinStats()
for coin in sorted(coinStats, key=lambda k: k['potentialGainPercent']):
    stats = coin
    print("\n")
    print("Pair: " + stats["pair"])
    print("Buy at " + stats["lowestExchangeUrl"] + " for " + format(stats["lowestPrice"], '.8f') + " " + stats["baseCurrency"].upper())
    print("Volume " + str(stats["lowestMarket"]["volume"]))
    print("Sell at " + stats["highestExchangeUrl"] + " for " + format(stats["highestPrice"], '.8f') + " " + stats["baseCurrency"].upper())
    print("Volume " + str(stats["highestMarket"]["volume"]))
    print("Potential gain: " + str(stats["potentialGainPercent"]) + "%")
########################################################

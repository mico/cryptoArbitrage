
# cryptoArbitrage
A project which aims to find potentially profitable arbitrage opportunities for cryptocurrencies across exchanges.

## Install requirements
```pip3 install -r requirements.txt```
mac os x:
```brew install influxdb```
create influxdb database and user.
cp config-example.yml config.yml
vim config.yml

## Run
run influxdb
python3 arbit_ccxt.py

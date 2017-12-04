from requests import Session  # pip install requests
from signalr import Connection  # pip install signalr-client

# def blocking_function():
#     time.sleep(42)
#
# pool = ThreadPoolExecutor(max_workers=multiprocessing.cpu_count())
# loop = asyncio.get_event_loop()
# loop.run_in_executor(pool, blocking_function)
# loop.close()

# or use this!!! https://github.com/aio-libs/janus

def handle_received(*args, **kwargs):
    # Orderbook snapshot:
    if 'R' in kwargs and type(kwargs['R']) is not bool:
        # kwargs['R'] contains your snapshot
        print(kwargs['R'])

# You didn't add the message stream
def msg_received(*args, **kwargs):
    # args[0] contains your stream
    import pdb; pdb.set_trace()
    print(args)


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

        for market in ["BTC-ETH"]:
            chat.server.invoke('SubscribeToExchangeDeltas', market)
            chat.server.invoke('QueryExchangeState', market)

        # Value of 1 will not work, you will get disconnected
        connection.wait(120000)

main()

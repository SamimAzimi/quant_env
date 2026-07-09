"""External API keys, loaded from the environment / .env — see .env.example.

The previous version of this file contained hardcoded keys that were
committed to git history: treat every one of them as compromised and rotate
them with the provider. This module keeps the same `API_KEYS` dict interface
so existing notebook code keeps working, but the values now come from the
environment only.
"""

from .secrets import get_secret

# Secret credentials — set these in .env (never commit real values)
_SECRET_NAMES = [
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
    "BINANCE_API_TEST_KEY",
    "BINANCE_SECRET_TEST_KEY",
    "BINANCE_FUTURE_TEST_API_KEY",
    "BINANCE_FUTURE_TEST_SECRET_KEY",
    "POLYGON_API",
    "NASLINK",
    "FRED_API_KEY",
    "FINMODEL",
    "NEWSAPI_KEY",
    "BITQURY_API_KEY",
    "ALPHA_VENTAGE_API",
    "TWELEVE_API",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_BEARER_TOKEN",
    "TWITTER_ACCESS_TOKEN",
    "TIWTTER_ACCESS_TOKEN_SECRET",
    "ETHERSCAN_API_KEY",
    "INFURA_API_KEY",
    "ALCHEMY_API_KEY",
]

API_KEYS = {name: get_secret(name) for name in _SECRET_NAMES}

# Non-secret endpoints
API_KEYS.update({
    "BINANCE_SPOT_BASEURL": "https://api.binance.com",
    "BINANCE_SPOT_TESTURL": "https://testnet.binance.vision/api",
    "ETHERSCAN_HTTP_URL": "https://api.etherscan.io/api",
    "INFURA_HTTP_URL": "https://mainnet.infura.io/v3/",
    "ALCHEMY_RPC_URL": "https://eth-sepolia.g.alchemy.com/v2/",
    "INFURA_WS_URI": "wss://mainnet.infura.io/ws/v3/",
})

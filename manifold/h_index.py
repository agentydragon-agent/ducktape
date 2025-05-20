# http://manifold.markets/api/v0/markets?limit=1&before=id
import urllib

import pandas as pd
import requests
from tqdm.auto import tqdm

BASE_URI = "http://manifold.markets/api/v0"

before = None
# limit: maximum and default is 1000
limit = 1000

markets = []

while True:
    params = {
        "limit": limit,
    }
    if before:
        params["before"] = before
    url = f"{BASE_URI}/markets?" + urllib.parse.urlencode(params)
    print(url)
    result = requests.get(url)
    j = result.json()
    if len(j) < limit:
        print("No more markets")
        break
    before = j[-1]["id"]
    markets.extend(j)

recs = []
for market in tqdm(markets, leave=False):
    # https://manifold.markets/agentydragon/what-will-be-my-10-m-impact-factor
    # at least N markets all of which have at least N bets of at least 10 M$
    if market["creatorUsername"] == "agentydragon":
        # get bets
        url = f"{BASE_URI}/market/{market['id']}"
        result = requests.get(url)
        # bets, comments
        num_bets = 0
        for bet in result.json()["bets"]:
            if bet["amount"] >= 10:
                num_bets += 1
        recs.append(
            {
                "id": market["id"],
                "url": market["url"],
                "num_bets": num_bets,
            }
        )
        # also:
        #   - pool, probability, isResolved, ...

df = pd.DataFrame(recs)
df.sort_values("num_bets", ascending=False, inplace=True)
df.reset_index(inplace=True, drop=True)
print(df)
# creatorName

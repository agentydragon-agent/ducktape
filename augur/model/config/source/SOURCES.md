# Public market-data sources

Snapshots of publicly available market data that augur's market models fit
against. None of this is private; every series is reproducible by following
the steps below. Two files have been trimmed from their upstream form to
keep the checked-in size manageable; the trim is also documented per file.

To refresh any series, replace the file in place using the steps below.

## Files

### FRED series

[FRED](https://fred.stlouisfed.org/) is the St. Louis Fed's economic data
service. For any series `<SERIES_ID>`, the CSV download is:

```
https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
```

(Or equivalently, browse to `https://fred.stlouisfed.org/series/<SERIES_ID>`
and click the **Download → CSV** button.)

The files checked in are **untrimmed** — column shape and date range match
upstream as of the last refresh. Series mapping:

| Local file                          | FRED series ID   | What it is                                                        |
| ----------------------------------- | ---------------- | ----------------------------------------------------------------- |
| `fred_cpi_us.csv`                   | `CPIAUCSL`       | US headline CPI (all items, urban consumers, seasonally adjusted) |
| `fred_sp500.csv`                    | `SP500`          | S&P 500 daily close                                               |
| `fred_mortgage30.csv`               | `MORTGAGE30US`   | 30-year fixed mortgage rate (Freddie Mac PMMS, weekly)            |
| `fred_sfxrsa.csv`                   | `SFXRSA`         | Case-Shiller SF home price index, seasonally adjusted             |
| `fred_fhfa_sf_oakland_berkeley.csv` | `ATNHPIUS41884Q` | FHFA SF-Oakland-Berkeley MSA all-transactions HPI (quarterly)     |
| `fred_sf_rent_cpi.csv`              | `CUURA422SEHA`   | SF-area rent CPI (urban consumers, not seasonally adjusted)       |

### `yahoo_spy_chart_adjusted.json`

State Street SPY ETF daily prices, used as the SP500 total-return proxy
(captures dividend reinvestment, which the raw FRED `SP500` price series does
not).

Source: Yahoo Finance v8 chart API.

```
curl -sS 'https://query2.finance.yahoo.com/v8/finance/chart/SPY?range=max&interval=1d' \
  -H 'User-Agent: Mozilla/5.0' -o yahoo_spy_chart_adjusted.json
```

**Trimmed**. The upstream response carries six daily series under
`chart.result[0].indicators.quote[0]` (open/high/low/close/volume + redundant
adjclose) plus the OHLC/volume bundle, market-meta blocks, and trading-hours
windows. The loader (`augur/model/market_data.py::_read_yahoo_spy_adjusted_close`)
only reads `chart.result[0].timestamp` and
`chart.result[0].indicators.adjclose[0].adjclose`. The checked-in file
preserves only those two arrays plus a minimal `meta.symbol` /
`meta.currency` for traceability. Size: ~1 MB upstream → ~240 KB trimmed.

After a fresh download, re-trim with:

```python
import json, sys
data = json.load(open(sys.argv[1]))
result = data['chart']['result'][0]
trimmed = {
    'chart': {
        'result': [{
            'meta': {'symbol': result['meta']['symbol'], 'currency': result['meta'].get('currency')},
            'timestamp': result['timestamp'],
            'indicators': {'adjclose': [{'adjclose': result['indicators']['adjclose'][0]['adjclose']}]},
        }]
    }
}
json.dump(trimmed, open(sys.argv[2], 'w'), separators=(',', ':'))
```

### `zillow_city_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv`

Zillow's city-level Home Value Index for the mid-tier SFR + condo bucket,
smoothed and seasonally adjusted, monthly. Used as the home-price ground
truth for SF and Vallejo location paths.

Source: [Zillow Research](https://www.zillow.com/research/data/) — pick
**Home values → ZHVI All Homes (SFR, Condo/Co-op) Time Series, Smoothed,
Seasonally Adjusted ($) → City**.

Direct URL (subject to change as Zillow rotates dataset paths):

```
https://files.zillowstatic.com/research/public_csvs/zhvi/City_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv
```

**Trimmed**. The upstream file is the full nationwide CSV with ~21,000 city
rows × ~25 years of monthly columns (~88 MB). The loader
(`augur/model/market_data.py::_read_zillow_city_zhvi`) filters by
`RegionType == "city" && State == "CA" && RegionName ∈ {San Francisco,
Vallejo}`. The checked-in file preserves only those two rows plus the header.
Size: ~88 MB upstream → ~15 KB trimmed.

To re-trim after a fresh download:

```python
import csv, sys
with open(sys.argv[1], newline='') as fin, open(sys.argv[2], 'w', newline='') as fout:
    reader, writer = csv.reader(fin), csv.writer(fout)
    writer.writerow(next(reader))
    for row in reader:
        if row[3] == 'city' and row[5] == 'CA' and row[2] in ('San Francisco', 'Vallejo'):
            writer.writerow(row)
```

Add the corresponding `(RegionName, State)` pair to the filter when extending
the location set.

## Refresh checklist

When refreshing one or more series:

1. Re-download from the source.
2. Apply the trim (Yahoo, Zillow) if applicable.
3. Replace the file in place. Don't rename — paths are referenced from
   `augur/model/config/joint_config.example.json` and equivalents.
4. Re-fit downstream models that depend on the changed series:
   the macro rollout provider's factor calibration, plus any PyMC posterior
   stored downstream of this package.

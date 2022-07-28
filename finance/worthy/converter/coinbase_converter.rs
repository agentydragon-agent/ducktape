// TODO(agentydragon): currently only converts crypto -> base currency.

use async_trait::async_trait;
use bigdecimal::BigDecimal;
use converter::Converter;
use denomination::Denomination;
use exchange_rate::ExchangeRate;
use log::{error, info};
use rust_decimal::prelude::*;
use rust_decimal::Decimal;
use serde::Deserialize;
use std::{
    error::Error,
    fmt,
    fmt::{Display, Formatter},
};

pub struct CoinbaseConverter {}

#[derive(Debug, Deserialize)]
pub struct CoinbaseConverterConfig {}

#[derive(Debug)]
struct CoinbaseError(String);

impl Error for CoinbaseError {}

impl Display for CoinbaseError {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        write!(f, "Oh no, {}", self.0)
    }
}

fn decimal_from_bigdecimal(bd: &BigDecimal) -> Decimal {
    Decimal::from_str(&bd.to_string()).unwrap()
}

// fn lookup_currency(code: &str) -> Option<Denomination> {
//     let known_cryptocurrencies: HashSet<&str> =
//         vec!["BTC", "BCH", "BSV", "ETH"].into_iter().collect();
//     if iso::find(code).is_some() {
//         // Assume it's an ISO currency code.
//         Some(Denomination::Currency {
//             currency: code.to_string(),
//         })
//     } else if known_cryptocurrencies.contains(code) {
//         // TODO: use rusty_money's crypto set when possible
//         Some(Denomination::Cryptocurrency {
//             symbol: code.to_string(),
//         })
//     } else {
//         warn!("unknown coinbase currency {}", code);
//         None
//     }
// }

#[async_trait]
impl Converter for CoinbaseConverter {
    type Config = CoinbaseConverterConfig;

    async fn take_snapshot(
        _config: &Self::Config,
        denominations: &'life1 [&Denomination],
        base: &Denomination,
    ) -> Result<Vec<ExchangeRate>, Box<dyn Error>> {
        let client = coinbase_rs::Public::new(coinbase_rs::MAIN_URL);

        let cryptos = denominations.iter().filter_map(|d| match d {
            Denomination::Cryptocurrency { symbol } => Some(symbol),
            _ => None,
        });

        let base_symbol = match base {
            Denomination::Currency { currency } => currency,
            _ => panic!("argh"),
        };

        //let currencies: Vec<_> = denominations
        //    .iter()
        //    .filter_map(|d| match d {
        //        Denomination::Currency { symbol } => Some(symbol),
        //        _ => None,
        //    })
        //    .collect();

        //        let currencies = client.currencies().collect::<Vec<_>>().await;
        //        info!("Coinbase supported currencies: {:?}", currencies);
        //        // Try to fetch price to sell all cryptos, ideally to base rate.
        //        let currency_symbols = currencies
        //            .iter()
        //            .flat_map(|c| {
        //                let x: &Vec<_> = c.as_ref().unwrap();
        //                x.iter().map(|c2| c2.id.as_str())
        //            })
        //            .collect::<HashSet<&str>>();

        // TODO(agentydragon): Do this in parallel.
        let mut res = Vec::new();
        for crypto_symbol in cryptos {
            //if !currency_symbols.contains(crypto_symbol.as_str()) {
            //if crypto_symbol == "BSV" || crypto_symbol == "BCH" {
            //    warn!("Coinbase does not support {}", crypto_symbol);
            //    continue;
            //}
            let pair = format!("{}-{}", crypto_symbol, base_symbol);
            info!("pair: {}", pair);
            //pub fn currencies<'a>(&'a self) -> impl Stream<Item = Result<Vec<Currency>>> + 'a {
            //    let limit = 100;
            //    let uri = UriTemplate::new("/v2/currencies{?query*}")
            //        .set("query", &[("limit", limit.to_string().as_ref())])
            //        .build();
            //    let request = self.request(&uri);
            //    self.get_stream(request)
            //}

            let rate = client
                .sell_price(&pair)
                .await
                .map_err(|e: coinbase_rs::CBError| {
                    error!("error for currency {}: {:?}", crypto_symbol, e);
                    CoinbaseError(e.to_string())
                })?
                .amount;
            res.push(ExchangeRate {
                from: Denomination::Cryptocurrency {
                    symbol: crypto_symbol.clone(),
                },
                to: base.clone(),
                rate: decimal_from_bigdecimal(&rate),
            })
        }
        Ok(res)

        //    let er = if let Denomination::Currency { currency } = base {
        //        client.exchange_rates_with_base(currency).await
        //    } else {
        //        client.exchange_rates().await
        //    };
        //    let exchange_rates = er.map_err(|e: coinbase_rs::CBError| CoinbaseError(e.to_string()))?;
        //    let base = lookup_currency(&exchange_rates.currency)
        //        .ok_or(CoinbaseError(format!("returned base currency not known")))?;
        //    exchange_rates
        //        .rates
        //        .into_iter()
        //        .filter_map(|(target_currency, rate)| -> Option<(Denomination, _)> {
        //            lookup_currency(&target_currency).map(|c| (c, rate))
        //        })
        //        .map(
        //            |(target_currency, rate)| -> Result<ExchangeRate, Box<dyn Error>> {
        //                let rate = Decimal::from_str(&rate.to_string())?;
        //                Ok(ExchangeRate {
        //                    from: base.clone(),
        //                    to: target_currency,
        //                    rate,
        //                })
        //            },
        //        )
        //        .collect()
    }
}

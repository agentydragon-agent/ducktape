use asset::Asset;
use async_trait::async_trait;
use denomination::Denomination;
use futures::pin_mut;
use futures::stream::StreamExt;
use log::{debug, info};
use rust_decimal::prelude::*;
use rust_decimal::Decimal;
use serde::Deserialize;
use source::Source;
use std::{
    error::Error,
    fmt,
    fmt::{Display, Formatter},
};

pub struct CoinbaseSource {}

#[derive(Debug, Deserialize)]
pub struct CoinbaseSourceConfig {
    api_key: String,
    api_secret: String,
}

#[derive(Debug)]
struct CoinbaseError(String);

impl Error for CoinbaseError {}

impl Display for CoinbaseError {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        write!(f, "Oh no, {}", self.0)
    }
}

#[async_trait]
impl Source for CoinbaseSource {
    type Config = CoinbaseSourceConfig;

    async fn take_snapshot(config: &Self::Config) -> Result<Vec<Asset>, Box<dyn Error>> {
        let CoinbaseSourceConfig {
            api_key,
            api_secret,
        } = config;
        let client = coinbase_rs::Private::new(coinbase_rs::MAIN_URL, api_key, api_secret);

        //while let Some(currencies_result) = currencies.next().await {
        //    for currency in currencies_result.unwrap() {
        //        println!(
        //            "Currency {} mininum size = {}",
        //            currency.name, currency.min_size
        //        );
        //    }

        let accounts = client.accounts();
        pin_mut!(accounts);
        let mut res = Vec::new();
        while let Some(accounts2) = accounts.next().await {
            debug!("Accounts from Coinbase: {:?}", accounts2);
            if let Ok(accountsx) = accounts2 {
                for account in accountsx {
                    //if account.is_err() {
                    //    error!("{:?}", account);
                    //    panic!("error in account");
                    //}
                    //let account = account.unwrap();
                    if account.balance.amount.is_zero() {
                        continue;
                    }
                    let balance = Decimal::from_str(&account.balance.amount.to_string())?;
                    // TODO: check that the currency code is indeed a crypto asset, and ideally
                    // should also be known by rusty-money
                    info!("{:?}", account.balance);
                    res.push(Asset {
                        denomination: Denomination::Cryptocurrency {
                            symbol: account.balance.currency.clone(),
                        },
                        amount: balance,
                    });
                }
            }
        }
        Ok(res)
        //accounts
        //    .iter()
        //    .filter(|account| !account.balance.amount.is_zero())
        //    .map(|account| -> Result<Asset, Box<dyn Error>> {
        //        let balance = Decimal::from_str(&account.balance.amount.to_string())?;
        //        // TODO: check that the currency code is indeed a crypto asset, and ideally
        //        // should also be known by rusty-money
        //        info!("{:?}", account.balance);
        //        Ok(Asset {
        //            denomination: Denomination::Cryptocurrency {
        //                symbol: account.balance.currency.clone(),
        //            },
        //            amount: balance,
        //        })
        //    })
        //    .collect()
    }
}

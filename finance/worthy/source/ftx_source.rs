use asset::Asset;
use async_trait::async_trait;
use denomination::Denomination;
use ftx::rest::Rest;
use log::info;
use rust_decimal::Decimal;
use serde::Deserialize;
use source::Source;
use std::error::Error;

pub struct FtxSource {}

#[derive(Debug, Deserialize)]
pub struct FtxSourceConfig {
    api_key: String,
    api_secret: String,
}

#[async_trait]
impl Source for FtxSource {
    type Config = FtxSourceConfig;

    async fn take_snapshot(config: &Self::Config) -> Result<Vec<Asset>, Box<dyn Error>> {
        let FtxSourceConfig {
            api_key,
            api_secret,
        } = config;
        let client = Rest::new(ftx::options::Options {
            endpoint: ftx::options::Endpoint::Com,
            key: Some(api_key.clone()),
            secret: Some(api_secret.clone()),
            subaccount: None,
        });

        let balances = client.get_wallet_balances().await.unwrap();
        info!("{:#?}", balances);
        let mut total = Decimal::ZERO;
        for balance in balances {
            total += balance.usd_value.unwrap();
        }
        Ok(vec![Asset {
            denomination: Denomination::Currency {
                currency: "USD".to_string(),
            },
            amount: total,
        }])
    }
}

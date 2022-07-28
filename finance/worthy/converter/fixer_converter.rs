use async_trait::async_trait;
use converter::Converter;
use denomination::Denomination;
use exchange_rate::ExchangeRate;
use reqwest::StatusCode;
use rust_decimal::prelude::*;
use serde::Deserialize;
use std::collections::HashMap;
use std::error::Error;
use url::Url;

pub struct FixerConverter {}

#[derive(Debug, Deserialize)]
pub struct FixerConverterConfig {
    api_key: String,
}

#[derive(Debug, Deserialize)]
pub struct RatesResponse {
    pub success: bool,
    // "timestamp":1613851867
    pub base: String,
    // "date":"2021-02-20"
    pub rates: HashMap<String, Decimal>,
    // if base = USD and rates[CZK] = 0, then 1 USD is 20 CZK.
}

#[async_trait]
impl Converter for FixerConverter {
    type Config = FixerConverterConfig;

    async fn take_snapshot(
        config: &Self::Config,
        _denominations: &'life1 [&Denomination],
        _base: &Denomination,
    ) -> Result<Vec<ExchangeRate>, Box<dyn Error>> {
        let FixerConverterConfig { api_key } = config;

        let mut url = Url::parse("http://data.fixer.io/api/latest")?;
        url.query_pairs_mut()
            .clear()
            .append_pair("access_key", api_key);

        let response = reqwest::get(url).await?;
        assert_eq!(response.status(), StatusCode::OK);

        let r: RatesResponse = response.json().await?;

        let base = r.base;
        Ok(r.rates
            .into_iter()
            .map(|(to_symbol, rate)| ExchangeRate {
                from: Denomination::Currency {
                    currency: base.clone(),
                },
                to: Denomination::Currency {
                    currency: to_symbol,
                },
                rate,
            })
            .collect())
    }
}

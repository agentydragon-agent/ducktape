use async_trait::async_trait;
use converter::Converter;
use currency_layer::Client;
use denomination::Denomination;
use exchange_rate::ExchangeRate;
use rusty_money::Money;
use serde::Deserialize;
use std::error::Error;

pub struct CurrencyLayerConverter {}

#[derive(Debug, Deserialize)]
pub struct CurrencyLayerConverterConfig {
    api_key: String,
}

#[async_trait]
impl Converter for CurrencyLayerConverter {
    type Config = CurrencyLayerConverterConfig;

    async fn take_snapshot(
        config: &Self::Config,
        denominations: &'life1 [&Denomination],
        _base: &Denomination,
    ) -> Result<Vec<ExchangeRate>, Box<dyn Error>> {
        let CurrencyLayerConverterConfig { api_key } = config;
        let client = Client::new(api_key);

        let currencies = denominations
            .iter()
            .filter_map(|d| match d {
                Denomination::Currency { currency } => Some(currency.as_str()),
                _ => None,
            })
            .collect();
        // Do this for all currencies.
        // Will return everything relative to USD. Ugh.
        let res = client.get_live_rates(currencies).await.unwrap();

        Ok(res
            .quotes
            .values()
            .map(|exchange_rate| ExchangeRate {
                from: Denomination::Currency {
                    currency: exchange_rate.from.iso_alpha_code.to_string(),
                },
                to: Denomination::Currency {
                    currency: exchange_rate.to.iso_alpha_code.to_string(),
                },
                rate: *exchange_rate
                    .convert(&Money::from_major(1, exchange_rate.from))
                    .unwrap()
                    .amount(),
            })
            .collect())
    }
}

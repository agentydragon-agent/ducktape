use async_trait::async_trait;
use converter::Converter;
use denomination::Denomination;
use exchange_rate::ExchangeRate;
use headless_chrome::{Browser, LaunchOptionsBuilder};
use log::trace;
use regex::Regex;
use rust_decimal::prelude::*;
use rust_decimal::Decimal;
use serde::Deserialize;
use std::error::Error;
use std::{
    fmt,
    fmt::{Display, Formatter},
};

pub struct SwissFundDataConverter {}

#[derive(Deserialize, Debug)]
pub struct SwissFundDataConverterConfig {}

#[derive(Debug, PartialEq)]
enum SwissFundDataError {
    JSError,
    RegexError,
}

impl Error for SwissFundDataError {}

impl Display for SwissFundDataError {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        // TODO
        write!(f, "JS error")
    }
}

async fn get_price_in_chf(isin: &str) -> Result<Decimal, Box<dyn Error>> {
    let browser = Browser::new(
        LaunchOptionsBuilder::default() /* TODO: .headless(false)*/
            .build()?,
    )?;
    let tab = browser.wait_for_initial_tab()?;

    let mut url: String = "https://www.swissfunddata.ch/sfdpub/en/funds/overview?text=".to_owned();
    url.push_str(isin);

    // I was sometimes getting a timeout in the navigate_to below.
    // Not sure whether this actually works, but trying to set a longer timeout...
    tab.set_default_timeout(std::time::Duration::from_secs(120));
    tab.navigate_to(&url)?;
    trace!("navigated to: {}", url);

    // TODO: this breaks here - server returns an error
    // Click away annoying legal disclaimer.
    tab.wait_for_element("input[type=submit][value='I agree']")?
        .click()?;
    trace!("clicked agree button");

    // TODO: div#tab-1 > table > tbody should have 1 row
    tab.wait_for_element("table > tbody a[href^='/sfdpub/en/funds/show/']")?
        .click()?;

    let mut rows = tab.wait_for_elements("tr")?;
    let re = Regex::new(
        r"Current Price[\s*]*(?P<price>\d+\.\d+)\s*CHF\s*(?P<date>\d{1,2}\.\d{1,2}\.\d{4})",
    )?;
    for row in rows.iter_mut() {
        let content = row
            .call_js_fn("function() { return this.innerText; }", true)?
            .value
            .ok_or(SwissFundDataError::JSError)?;
        match content {
            serde_json::Value::String(s) => {
                if !re.is_match(&s) {
                    continue;
                }
                let cap = re.captures(&s).ok_or(SwissFundDataError::RegexError)?;
                let cap_str: &str = &cap[1];
                let price = Decimal::from_str(cap_str)?;
                return Ok(price);
                // "date": &cap[2],
            }
            _ => panic!("argh"),
        }
    }
    panic!("Did not find price of fund {} in {}", isin, url)
}

#[async_trait]
impl Converter for SwissFundDataConverter {
    type Config = SwissFundDataConverterConfig;

    async fn take_snapshot(
        _config: &Self::Config,
        denominations: &'life1 [&Denomination],
        _base: &Denomination,
    ) -> Result<Vec<ExchangeRate>, Box<dyn Error>> {
        let isins: Vec<&String> = denominations
            .iter()
            .filter_map(|d| match d {
                Denomination::FundIsin { fund_isin } => Some(fund_isin),
                _ => None,
            })
            .collect();
        let mut res = Vec::new();
        // TODO(agentydragon): Do this in parallel.
        for isin in isins {
            let rate = get_price_in_chf(isin).await?;
            res.push(ExchangeRate {
                from: Denomination::FundIsin {
                    fund_isin: isin.to_string(),
                },
                to: Denomination::Currency {
                    currency: "CHF".to_string(),
                },
                rate,
            })
        }
        Ok(res)
    }
}

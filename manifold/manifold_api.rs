use serde::{Serialize, Deserialize};
use url::Url;
use log::{info, trace};
use std::error::Error;
use reqwest::StatusCode;
use rust_decimal::Decimal;

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "outcomeType", rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OutcomeType {
    Binary {
        /// Between 0 and 100.
        #[serde(rename = "initialProb")]
        initial_probability: u8,
    },
    FreeResponse,
    Numeric {
        min: i32,
        max: i32,
    },
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct CreateMarketRequest {
    #[serde(flatten)]
    outcome_type: OutcomeType,
    question: String,
    description: String,
    /// Milliseconds since Unix epoch.
    close_time: i64,
}

#[derive(Serialize, Deserialize, Debug, Default)]
pub struct GetMarketsRequest {
    pub limit: Option<u32>,
    pub before: Option<String>,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct LiteMarket {
    pub id: String,
    // Creator attributes.
    creator_username: String,
    creator_name: String,
    created_time: i64,
    creator_avatar_url: Option<String>,
    // Market attributes, times in milliseconds.
    close_time: Option<i64>,
    question: String,
    description: String,
    tags: Vec<String>,
    url: String,

    pool: Option<Decimal>,
    probability: Option<Decimal>, // TODO: what? decimal? maybe float? int? docs say "number".
    volume_7_days: Decimal,
    volume_24_hours: Decimal,
    is_resolved: bool,
    resolution_time: Option<i64>,
    resolution: Option<String>,
}
const ENDPOINT: &str =
    "https://manifold.markets/api/v0";

// TODO: reqwest: get
pub async fn get_markets(
    request: &GetMarketsRequest,
//) -> Result<Vec<LiteMarket>, Box<dyn Error>> {
) -> Vec<LiteMarket> {
    let mut url = Url::parse(ENDPOINT).unwrap();//?;
    url.path_segments_mut()
        .expect("path segments")
        .push("markets");
    // TODO: serde_qs
    {
        let mut query = url.query_pairs_mut();
        if let Some(limit) = &request.limit {
            query.append_pair("limit", &limit.to_string());
        }
        if let Some(before) = &request.before {
            query.append_pair("before", &before.to_string());
        }
    }
    let response = reqwest::get(url).await.unwrap();//?;
    if response.status() != StatusCode::OK {
        panic!("non-ok status: {:?}", response.status());
    }
    // match r.status() {
    //     StatusCode::OK => Ok(()),
    //     status => Err(IBFlexError::HttpError { status }),
    // }

    let text = response.text().await.unwrap();//?;
    trace!("{:?}", text);
    // serde_json::from_str(&text).unwrap()//?

    let deserializer = &mut serde_json::Deserializer::from_str(&text);

    serde_path_to_error::deserialize(deserializer).unwrap()
}

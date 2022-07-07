// General idea: make a queue that will create markets with a rate limit.
// The rate limit is based on the free mana given by Manifold every N hours.
// That should allow experimenting with whatever else at the rate limit allowed
// by Manifold.
// Even just "this market resolves as TRUE at date X".
//
// I could ask questions that could be resolved by code.
//
// The prediction market could be used to answer any generic question, by
// community polling. Basically Keynesian beauty contest.
//
//
//
// Ideas:
//   - Prediction market for weight on every day in the next couple weeks.
//     Not good, that would be a numeric market.
//   - Will SP500 close higher, or lower?
//     Could be fun to see if it could be worth $1 as a signal.
//     Could be also done on a given stock.
//     ("On the trading day X, will GOOG close higher than it opened?")
//   - How much money will I have on a given day?
//   - Something having to do with futarchy.
//     - "If I do [thing], it'll have a good outcome"
//     - "If I [meditate], I'll [have higher subjective happiness]."
//   - sports events - anything that people would be interested in betting on
//   - how many followers will Soatok have on Twitter at time X?
//   - "Should I do [X]?"
//     - Things I'd be considering:
//       - Fixed waking schedule
//       - Cancelling specific tasks
//       - Doing specific tasks
//   - Research into properties of prediction markets
//     - Does monetary incentive help?
//
// What sort of stuff is decision relevant for me?
//   - Who will we choose as our 4th flatmate?
//   - Which papers should I read?
//   - What should I be working on on a given day?
//
// Will I still work for OpenAI at [datetime]?

extern crate serde;
//extern crate serde_millis;

use std::default::Default;
use log::info;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;

#[derive(Serialize, Deserialize, Debug)]
#[serde(tag = "outcome_type", rename_all = "SCREAMING_SNAKE_CASE")]
enum QueueOutcomeType {
    Binary {
        /// Between 0 and 100.
        initial_probability: u8,
    },
    FreeResponse,
    Numeric {
        min: i32,
        max: i32,
    },
}

#[derive(Serialize, Deserialize, Debug)]
struct QueueItem {
    #[serde(flatten)]
    outcome_type: QueueOutcomeType,

    queue_id: String,
    question: String,
    description: String,
    // TODO: close_time can be any sort of specification of time
    close_time: String,
}

#[derive(Serialize, Deserialize, Debug)]
struct QueueFile {
    // TODO: hashmap from id
    queue: Vec<QueueItem>,
}

#[derive(Serialize, Deserialize, Debug)]
enum QueueState {
    NotCreated,
    Created { manifold_id: String },
}

#[derive(Serialize, Deserialize, Debug)]
struct QueueCache {
    queue_cache: HashMap<String, QueueState>,
}

// TODO: structopt - parse command-line
struct Opt {
    queue_path: String,
    queue_cache_path: String,
}

#[tokio::main]
async fn main() {
    env_logger::init();
    let queue_file: QueueFile = toml::from_str(
        &fs::read_to_string(
            // "queue.toml"
            "/home/agentydragon/repos/ducktape/manifold/queue.toml",
        )
        .unwrap(),
    )
    .unwrap();
    info!("{:?}", queue_file);

    // TODO: Load the queue.
    // TODO: Load queue status.
    //     TODO: alternatively, load it from embedded tags.
    //           store our mapping in Manifold:
    //               [queue ID || hash(salt || Manifold ID || queue ID)]
    // TODO: Look at first item in queue that is not loaded yet.
    // TODO: send create-request for it, look it up.
    // TODO: save queue status.

    // TODO: this should be probs part of API
    const LIMIT: u32 = 1000;

    let mut before: Option<String> = None;

    loop {
        //&Default::default()
        let markets = manifold_api::get_markets(
                  &manifold_api::GetMarketsRequest{before, limit: Some(LIMIT)}
                  ).await;
        before = Some(markets[markets.len()-1].id.clone());
        info!("{:?}", markets);
        if markets.len() < usize::try_from(LIMIT).unwrap() {
            info!("done");
            break;
        }
    }
    info!("done done");

}

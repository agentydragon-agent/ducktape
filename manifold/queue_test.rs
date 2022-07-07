fn test_parse_create_market_tequest() {
    let example = r#"{
      "outcomeType":"BINARY",
      "question":"Is there life on Mars?",
      "description":"I'm not going to type some long ass example description.",
      "closeTime":1700000000000,
      "initialProb":25
    }"#;

    let r: CreateMarketRequest = serde_json::from_str(example).unwrap();
    println!("{:?}", r);
    // TODO: not sure what the server actually returns given this.
}

fn test_parse_queue_toml() {
    let example = r#"
      # TODO: save which markets already exist into some file somewhere
      [[queue]]
      id = 'openai-2022-09'
      outcome_type = 'BINARY'
      question = 'Will I still work at OpenAI at date of market close?'
      description = 'Resolves to YES if by time of market close I am still employed at OpenAI.'
      # Pacific time
      close_time = '2022-09-01T00:00:00-07:00'
      initial_probability = 50

      [[queue]]
      id = 'openai-2022-10'
      outcome_type = 'BINARY'
      question = 'Will I still work at OpenAI at date of market close?'
      description = 'Resolves to YES if by time of market close I am still employed at OpenAI.'
      # Pacific time
      close_time = '2022-10-01T00:00:00-07:00'
      initial_probability = 50
    "#;
    let q: QueueFile = toml::from_str(example).unwrap();
    println!("{:?}", q);
}

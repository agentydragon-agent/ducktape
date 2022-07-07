use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
struct Person {
    #[serde(rename = "nameRust")]
    nameJson: String,
    age: u8,
}

fn main() -> Result<(), serde_json::Error> {
    let example = r#"{"nameJson":"John","age":25}"#;
    let p: Person = serde_json::from_str(example)?;
    // Output: Person { nameRust: "John", age: 25 }
    println!("{:?}", p);
    Ok(())
}

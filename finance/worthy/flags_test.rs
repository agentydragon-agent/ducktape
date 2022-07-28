use flags::{Command, Opt};
use std::path::PathBuf;
use structopt::StructOpt;

#[test]
fn test_flag_parsing() {
    assert_eq!(
        Opt::from_iter(&[
            "worthy",
            "--json_output_path=/home/test.json",
            "--command=csv",
            "--write_to_solid"
        ]),
        Opt {
            json_output_path: Some(PathBuf::from("/home/test.json")),
            command: Command::Csv,
            write_to_solid: true
        }
    );
}

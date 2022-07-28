/// Run like this:
///   bazel run //example:swiss_fund_data -- --isin=CH0413292308
use converter::Converter;
use denomination::Denomination;
use structopt::StructOpt;
use swiss_fund_data_converter::SwissFundDataConverter;
use swiss_fund_data_converter::SwissFundDataConverterConfig;

#[derive(Debug, StructOpt)]
pub struct Opt {
    #[structopt(long = "isin")]
    pub isin: String,
}

#[tokio::main]
async fn main() {
    env_logger::init();
    let opt = Opt::from_args();
    let rates = SwissFundDataConverter::take_snapshot(
        &SwissFundDataConverterConfig {},
        &[&Denomination::FundIsin {
            fund_isin: opt.isin,
        }],
        &Denomination::Currency {
            currency: "CHF".to_string(),
        },
    )
    .await
    .unwrap();
    println!("{:?}", rates)
}

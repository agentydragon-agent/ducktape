// foaf:primaryTopic, foaf:maker

use asset::Asset;
use chrono::{DateTime, FixedOffset};
use denomination::Denomination;
use exchange_rate::ExchangeRate;
use ns::worthy;
use sophia::graph::inmem::FastGraph;
use sophia::graph::MutableGraph;
use sophia::ns::Namespace;
use sophia::ns::{rdf, xsd};
use sophia::term::literal::convert::AsLiteral;
use sophia::term::Term;
use std::error::Error;
use uuid::Uuid;

fn new_blank_node() -> Term<String> {
    Term::new_bnode(format!("_{}", &Uuid::new_v4().as_simple())).unwrap()
}

pub struct SourceSnapshot {
    pub source_id: String,
    pub timestamp: DateTime<FixedOffset>,
    pub assets: Vec<Asset>,
    // TODO: source type
}

pub fn add_denomination(
    graph: &mut FastGraph,
    iri: &Term<String>,
    denomination: &Denomination,
) -> Result<(), Box<dyn Error>> {
    match denomination {
        Denomination::Currency { currency } => {
            graph.insert(iri, &rdf::type_, &worthy::Currency)?;
            graph.insert(iri, &worthy::iso4217Code, &currency.as_literal())?;
        }
        Denomination::Cryptocurrency { symbol } => {
            graph.insert(iri, &rdf::type_, &worthy::Cryptocurrency)?;
            graph.insert(iri, &worthy::unofficialCode, &symbol.as_literal())?;
        }
        Denomination::Stock { stock } => {
            graph.insert(iri, &rdf::type_, &worthy::Stock)?;
            graph.insert(iri, &worthy::stockSymbol, &stock.as_literal())?;
        }
        Denomination::FundIsin { fund_isin } => {
            graph.insert(iri, &rdf::type_, &worthy::Security)?;
            graph.insert(iri, &worthy::isin, &fund_isin.as_literal())?;
        }
    }
    Ok(())
}

fn add_asset(
    graph: &mut FastGraph,
    iri: &Term<String>,
    asset: &Asset,
) -> Result<(), Box<dyn Error>> {
    graph.insert(iri, &rdf::type_, &worthy::Asset)?;
    graph.insert(
        iri,
        &worthy::assetAmount,
        &Term::<String>::new_literal_dt(asset.amount.to_string(), xsd::decimal)?,
    )?;

    let denomination_iri = new_blank_node();
    graph.insert(iri, &worthy::assetDenomination, &denomination_iri)?;

    add_denomination(graph, &denomination_iri, &asset.denomination)?;
    Ok(())
}

pub fn add_source_snapshot(
    graph: &mut FastGraph,
    iri: &Term<String>,
    snapshot: SourceSnapshot,
) -> Result<(), Box<dyn Error>> {
    let dcterms = Namespace::new("http://purl.org/dc/terms/")?;

    graph.insert(iri, &rdf::type_, &worthy::SourceSnapshot)?;

    let source_iri = new_blank_node();
    // TODO: try to use a blank node instead...
    graph.insert(iri, &worthy::snapshotSource, &source_iri)?;
    graph.insert(&source_iri, &rdf::type_, &worthy::Snapshot)?;
    graph.insert(
        &source_iri,
        &worthy::sourceId,
        &snapshot.source_id.as_literal(),
    )?;
    graph.insert(
        &source_iri,
        &dcterms.get("issued")?,
        &Term::<String>::new_literal_dt(snapshot.timestamp.to_rfc3339(), xsd::dateTime)?,
    )?;

    for asset in snapshot.assets {
        let asset_iri = new_blank_node();
        add_asset(graph, &asset_iri, &asset)?;
        graph.insert(iri, &worthy::sourceSnapshotAsset, &asset_iri)?;
    }

    Ok(())
}

pub struct ConverterSnapshot {
    pub converter_id: String,
    // TODO: add timestamp to exchange rates
    pub exchange_rates: Vec<ExchangeRate>,
    // TODO: add converter type
}

pub fn add_converter_snapshot(
    graph: &mut FastGraph,
    iri: &Term<String>,
    snapshot: ConverterSnapshot,
) -> Result<(), Box<dyn Error>> {
    graph.insert(iri, &rdf::type_, &worthy::ConverterSnapshot)?;

    let converter_iri = new_blank_node();
    // TODO: try to use a blank node instead...
    graph.insert(iri, &worthy::snapshotConverter, &converter_iri)?;
    graph.insert(&converter_iri, &rdf::type_, &worthy::Converter)?;
    graph.insert(
        &converter_iri,
        &worthy::converterId,
        &snapshot.converter_id.as_literal(),
    )?;

    for exchange_rate in snapshot.exchange_rates {
        let exchange_rate_iri = new_blank_node();
        graph.insert(&exchange_rate_iri, &rdf::type_, &worthy::ExchangeRate)?;
        graph.insert(iri, &worthy::converterExchangeRate, &exchange_rate_iri)?;
        {
            let from_iri = new_blank_node();
            graph.insert(&exchange_rate_iri, &worthy::from, &from_iri)?;
            add_denomination(graph, &from_iri, &exchange_rate.from)?;
        }

        {
            let to_iri = new_blank_node();
            graph.insert(&exchange_rate_iri, &worthy::to, &to_iri)?;
            add_denomination(graph, &to_iri, &exchange_rate.to)?;
        }

        graph.insert(
            &exchange_rate_iri,
            &worthy::rate,
            &Term::<String>::new_literal_dt(exchange_rate.rate.to_string(), xsd::decimal)?,
        )?;
    }

    Ok(())
}

pub struct Snapshot {
    pub source_snapshots: Vec<SourceSnapshot>,
    pub converter_snapshots: Vec<ConverterSnapshot>,
    pub total: Asset,
}

pub fn add_snapshot(
    graph: &mut FastGraph,
    iri: &Term<String>,
    snapshot: Snapshot,
) -> Result<(), Box<dyn Error>> {
    graph.insert(iri, &rdf::type_, &worthy::Snapshot)?;
    for source_snapshot in snapshot.source_snapshots {
        let snapshot_iri = new_blank_node();
        add_source_snapshot(graph, &snapshot_iri, source_snapshot)?;
        graph.insert(iri, &worthy::snapshotSourceSnapshot, &snapshot_iri)?;
    }
    for converter_snapshot in snapshot.converter_snapshots {
        let converter_iri = new_blank_node();
        add_converter_snapshot(graph, &converter_iri, converter_snapshot)?;
        graph.insert(iri, &worthy::snapshotConverterSnapshot, &converter_iri)?;
    }
    let total_iri = new_blank_node();
    add_asset(graph, &total_iri, &snapshot.total)?;
    graph.insert(iri, &worthy::snapshotTotal, &total_iri)?;
    // TODO: add datetime
    Ok(())
}

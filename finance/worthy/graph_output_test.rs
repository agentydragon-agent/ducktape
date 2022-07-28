use asset::Asset;
use chrono::DateTime;
use denomination::Denomination;
use exchange_rate::ExchangeRate;
use graph_output::{ConverterSnapshot, Snapshot, SourceSnapshot};
use rust_decimal_macros::*;
use sophia::graph::inmem::FastGraph;
use sophia::graph::isomorphic_graphs;
use sophia::parser::turtle::TurtleParser;
use sophia::parser::TripleParser;
use sophia::serializer::turtle::TurtleSerializer;
use sophia::serializer::Stringifier;
use sophia::serializer::TripleSerializer;
use sophia::term::iri::Iri;
use sophia::triple::stream::TripleSource;

fn parse_turtle(turtle: &str, base: &str) -> FastGraph {
    let mut g = FastGraph::new();
    let p = TurtleParser {
        base: Some(base.into()),
    };
    p.parse_str(turtle).add_to_graph(&mut g).unwrap();
    g
}

fn get_turtle(graph: &FastGraph) -> String {
    let mut nt_stringifier = TurtleSerializer::new_stringifier();
    nt_stringifier.serialize_graph(graph).unwrap();
    nt_stringifier.to_string()
}

fn isomorphic_to_turtle(actual_graph: &FastGraph, turtle: &str) -> bool {
    // let expected_graph = parse_turtle(turtle, "http://base");
    let expected_graph = parse_turtle(turtle, "http://base");
    let are_same = isomorphic_graphs(&expected_graph, actual_graph).unwrap();
    if !are_same {
        println!(
            "expected:\n{}\nactual\n{}",
            get_turtle(&expected_graph),
            //turtle,
            get_turtle(actual_graph)
        );
    }
    are_same
}

#[test]
fn source_snapshot() {
    let _ = env_logger::builder().is_test(true).try_init();
    let snapshot = SourceSnapshot {
        source_id: "sourceid".to_string(),
        timestamp: DateTime::parse_from_rfc3339("1996-12-19T16:39:57-08:00").unwrap(),
        assets: vec![
            Asset {
                amount: dec!(111.11),
                denomination: Denomination::Currency {
                    currency: "USD".to_string(),
                },
            },
            Asset {
                amount: dec!(222.22),
                denomination: Denomination::Cryptocurrency {
                    symbol: "BTC".to_string(),
                },
            },
            Asset {
                amount: dec!(333.33),
                denomination: Denomination::Stock {
                    stock: "GOOG".to_string(),
                },
            },
            Asset {
                amount: dec!(444.44),
                denomination: Denomination::FundIsin {
                    fund_isin: "ABC123".to_string(),
                },
            },
        ],
    };

    let mut actual_graph = FastGraph::new();
    let iri = Iri::<String>::new("http://base/test/").unwrap();
    graph_output::add_source_snapshot(&mut actual_graph, &iri.into(), snapshot).unwrap();

    let turtle = r#"
        @base <http://base/test/> .
        @prefix worthy: <https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl#> .
        @prefix dcterms: <http://purl.org/dc/terms/>.
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#>.
        @prefix : <#>.

        <> a worthy:SourceSnapshot ;
          worthy:snapshotSource [
            a worthy:Snapshot ;
            worthy:sourceId "sourceid" ;
            dcterms:issued "1996-12-19T16:39:57-08:00"^^xsd:dateTime
          ] ;
          worthy:sourceSnapshotAsset [
            a worthy:Asset ;
            worthy:assetAmount "111.11"^^xsd:decimal ;
            worthy:assetDenomination [
              a worthy:Currency ;
              worthy:iso4217Code "USD"
            ]
          ], [
            a worthy:Asset ;
            worthy:assetAmount "222.22"^^xsd:decimal ;
            worthy:assetDenomination [
              a worthy:Cryptocurrency ;
              worthy:unofficialCode "BTC"
            ]
          ], [
            a worthy:Asset ;
            worthy:assetAmount "333.33"^^xsd:decimal ;
            worthy:assetDenomination [
              a worthy:Stock ;
              worthy:stockSymbol "GOOG"
            ]
          ], [
            a worthy:Asset ;
            worthy:assetAmount "444.44"^^xsd:decimal ;
            worthy:assetDenomination [
              a worthy:Security ;
              worthy:isin "ABC123"
            ]
          ] .
    "#;

    assert!(isomorphic_to_turtle(&actual_graph, turtle));
}

#[test]
fn converter_snapshot() {
    let _ = env_logger::builder().is_test(true).try_init();
    let snapshot = ConverterSnapshot {
        converter_id: "converterid".to_string(),
        exchange_rates: vec![
            ExchangeRate {
                from: Denomination::Cryptocurrency {
                    symbol: "BTC".to_string(),
                },
                to: Denomination::Currency {
                    currency: "USD".to_string(),
                },
                rate: dec!(10000.0),
            },
            ExchangeRate {
                from: Denomination::Currency {
                    currency: "CHF".to_string(),
                },
                to: Denomination::Currency {
                    currency: "USD".to_string(),
                },
                rate: dec!(1.1),
            },
        ],
    };

    let mut actual_graph = FastGraph::new();
    let iri = Iri::<String>::new("http://base/test/").unwrap();
    graph_output::add_converter_snapshot(&mut actual_graph, &iri.into(), snapshot).unwrap();

    let turtle = r#"
        @base <http://base/test/> .
        @prefix worthy: <https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#>.
        @prefix : <#>.

        <> a worthy:ConverterSnapshot ;
          worthy:snapshotConverter [
            a worthy:Converter ;
            worthy:converterId "converterid"
          ] ;
          worthy:converterExchangeRate [
            a worthy:ExchangeRate ;
            worthy:from [
              a worthy:Cryptocurrency ;
              worthy:unofficialCode "BTC"
            ] ;
            worthy:to [ a worthy:Currency ; worthy:iso4217Code "USD" ] ;
            worthy:rate "10000.0"^^xsd:decimal
          ], [
            a worthy:ExchangeRate ;
            worthy:from [ a worthy:Currency ; worthy:iso4217Code "CHF" ] ;
            worthy:to [ a worthy:Currency ; worthy:iso4217Code "USD" ] ;
            worthy:rate "1.1"^^xsd:decimal
          ] .
    "#;

    assert!(isomorphic_to_turtle(&actual_graph, turtle));
}

#[test]
fn snapshot() {
    let _ = env_logger::builder().is_test(true).try_init();
    let snapshot = Snapshot {
        total: Asset {
            amount: dec!(1.1),
            denomination: Denomination::Currency {
                currency: "USD".to_string(),
            },
        },
        source_snapshots: vec![SourceSnapshot {
            source_id: "sourceid".to_string(),
            timestamp: DateTime::parse_from_rfc3339("1996-12-19T16:39:57-08:00").unwrap(),
            assets: vec![Asset {
                amount: dec!(2.2),
                denomination: Denomination::Currency {
                    currency: "CZK".to_string(),
                },
            }],
        }],
        converter_snapshots: vec![ConverterSnapshot {
            converter_id: "converterid".to_string(),
            exchange_rates: vec![ExchangeRate {
                from: Denomination::Currency {
                    currency: "CZK".to_string(),
                },
                to: Denomination::Currency {
                    currency: "USD".to_string(),
                },
                rate: dec!(0.5),
            }],
        }],
    };

    let mut actual_graph = FastGraph::new();
    let iri = Iri::<String>::new("http://base/test/").unwrap();
    graph_output::add_snapshot(&mut actual_graph, &iri.into(), snapshot).unwrap();

    let turtle = r#"
        @base <http://base/test/> .
        @prefix worthy: <https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl#> .
        @prefix dcterms: <http://purl.org/dc/terms/>.
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#>.
        @prefix : <#>.

        <> a worthy:Snapshot ;
          worthy:snapshotTotal [
            a worthy:Asset ;
            worthy:assetAmount "1.1"^^xsd:decimal ;
            worthy:assetDenomination [
              a worthy:Currency ;
              worthy:iso4217Code "USD"
            ]
          ] ;
          worthy:snapshotSourceSnapshot [
            a worthy:SourceSnapshot ;
            worthy:snapshotSource [
              a worthy:Snapshot ;
              worthy:sourceId "sourceid" ;
              dcterms:issued "1996-12-19T16:39:57-08:00"^^xsd:dateTime
            ] ;
            worthy:sourceSnapshotAsset [
              a worthy:Asset ;
              worthy:assetAmount "2.2"^^xsd:decimal ;
              worthy:assetDenomination [
                a worthy:Currency ;
                worthy:iso4217Code "CZK"
              ]
            ]
          ] ;
          worthy:snapshotConverterSnapshot [
            a worthy:ConverterSnapshot ;
            worthy:snapshotConverter [
              a worthy:Converter ;
              worthy:converterId "converterid"
            ] ;
            worthy:converterExchangeRate [
              a worthy:ExchangeRate ;
              worthy:from [
                a worthy:Currency ;
                worthy:iso4217Code "CZK"
              ] ;
              worthy:to [ a worthy:Currency ; worthy:iso4217Code "USD" ] ;
              worthy:rate "0.5"^^xsd:decimal
            ]
          ] .
    "#;

    assert!(isomorphic_to_turtle(&actual_graph, turtle));
}

#[test]
fn bnodes_isomorphic() {
    let turtle = r#"
        @prefix : <>.

        :a :b [
          :c "hello" ;
          :d :e
        ] .

        :b :e [
          :c "foo" ;
          :d :a
        ] .
    "#;
    let parsed = parse_turtle(turtle, "http://base/");
    let round_tripped = parse_turtle(&get_turtle(&parsed), "http://base/");

    assert!(isomorphic_graphs(&parsed, &round_tripped).unwrap());
}

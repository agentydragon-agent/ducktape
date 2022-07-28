use sophia::graph::inmem::FastGraph;
use sophia::graph::Graph;
use sophia::parser::turtle::TurtleParser;
use sophia::parser::TripleParser;
use sophia::term::SimpleIri;
use sophia::triple::stream::TripleSource;

fn parse_turtle(turtle: &str, base: &str) -> FastGraph {
    let mut g = FastGraph::new();
    let p = TurtleParser {
        base: Some(base.into()),
    };
    p.parse_str(turtle).add_to_graph(&mut g).unwrap();
    g
}

#[test]
fn no_registered_path() {
    let _ = env_logger::builder().is_test(true).try_init();
    let graph = parse_turtle(
        r#"
        @prefix worthy: <https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl#> .
        @prefix solid: <http://www.w3.org/ns/solid/terms#> .

        <#123> a solid:TypeRegistration .
    "#,
        "http://base",
    );
    let result = solid_io::find_registered_path(&graph.as_dataset());
    assert!(result.is_ok());
    assert_eq!(result.unwrap(), None);
}

#[test]
fn one_registered_path() {
    let _ = env_logger::builder().is_test(true).try_init();
    let graph = parse_turtle(
        r#"
        @prefix worthy: <https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl#> .
        @prefix solid: <http://www.w3.org/ns/solid/terms#> .

        <#123> a solid:TypeRegistration;
           solid:forClass worthy:Snapshot;
           solid:instance </instances> .
    "#,
        "http://base",
    );
    let result = solid_io::find_registered_path(&graph.as_dataset());
    assert!(result.is_ok());
    assert_eq!(result.unwrap(), Some("http://base/instances".to_string()));
}

#[test]
fn find_private_type_index() {
    let _ = env_logger::builder().is_test(true).try_init();
    let graph = parse_turtle(
        r#"
        @prefix solid: <http://www.w3.org/ns/solid/terms#> .

        <http://me> solid:privateTypeIndex </private-type-index> .
    "#,
        "http://base",
    );
    let webid_iri = SimpleIri::new("http://me", None).unwrap();
    let result = solid_io::find_private_type_index(&webid_iri, &graph.as_dataset());
    assert!(result.is_ok());
    assert_eq!(
        result.unwrap(),
        "http://base/private-type-index".to_string()
    );
}

// TODO: test if there's no privat type index

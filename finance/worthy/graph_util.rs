use sophia::{
    graph::MutableGraph,
    term::{CopyTerm, Term},
    triple::Triple,
};
use std::error::Error;

/// Removes all triples from the graph.
pub fn truncate_graph<G>(graph: &mut G) -> Result<(), Box<dyn Error>>
where
    G: MutableGraph,
{
    let mut triples: Vec<[Term<String>; 3]> = Vec::new();
    for t in graph.triples() {
        let t = t?;
        triples.push([
            CopyTerm::copy(t.s()),
            CopyTerm::copy(t.p()),
            CopyTerm::copy(t.o()),
        ]);
    }
    for triple in triples {
        // TODO: check true result
        graph.remove(triple.s(), triple.p(), triple.o())?;
    }
    Ok(())
}

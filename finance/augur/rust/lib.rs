//! Clean-sheet deterministic Augur simulator.
//!
//! Money is represented exclusively as integer currency quanta. The crate has
//! no floating-point monetary type and does not deserialize JSON numbers into
//! one.

pub mod engine;
pub mod fixture;
pub mod ledger;
pub mod money;
pub mod tax;

pub use engine::{
    SimulationError, ValidatedFixture, simulate, simulate_summaries, simulate_summaries_validated,
};
pub use fixture::{Fixture, PopulationOutput, SimulationOutput};

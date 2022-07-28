// TODO: would be nice if we could use this from sophia...
// This code is copied from sophia macros.
macro_rules! ns_iri {
    ($prefix:expr, $ident:ident) => {
        ns_iri!($prefix, $ident, stringify!($ident));
    };
    ($prefix:expr, $ident:ident, $suffix:expr) => {
        /// Generated term.
        #[allow(non_upper_case_globals)]
        pub static $ident: sophia::term::SimpleIri =
            sophia::term::SimpleIri::new_unchecked($prefix, Some($suffix));
    };
}

macro_rules! namespace {
    ($iri_prefix:expr, $($suffix:ident),*; $($r_id:ident, $r_sf:expr),*) => {
        /// Prefix used in this namespace.
        pub static PREFIX:&'static str = $iri_prefix;
        $(
            ns_iri!($iri_prefix, $suffix);
        )*
        $(
            ns_iri!($iri_prefix, $r_id, $r_sf);
        )*

        /// Test module for checking tha IRIs are valid
        #[cfg(test)]
        mod test_valid_iri {
            #[test]
            $(
                #[allow(non_snake_case)]
                #[test]
                fn $suffix() {
                    $crate::term::SimpleIri::new($iri_prefix, Some(stringify!($suffix))).expect(stringify!($suffix));
                }
            )*
            $(
                #[allow(non_snake_case)]
                #[test]
                fn $r_id() {
                    $crate::term::SimpleIri::new($iri_prefix, Some($r_sf)).expect($r_sf);
                }
            )*
        }
    };
    ($iri_prefix:expr, $($suffix:ident),*) => {
        namespace!($iri_prefix, $($suffix),*;);
    };
}

// TODO(agentydragon): could we autogenerate this?
pub mod worthy {
    namespace!(
        "https://agentydragon.solidcommunity.net/private/worthy/vocabulary.ttl#",
        // classes
        Snapshot,
        Currency,
        Cryptocurrency,
        SourceSnapshot,
        sourceId,
        snapshotSource,
        Asset,
        assetAmount,
        sourceSnapshotAsset,
        assetDenomination,
        ConverterSnapshot,
        snapshotConverter,
        Converter,
        converterId,
        ExchangeRate,
        converterExchangeRate,
        from,
        to,
        rate,
        unofficialCode,
        Stock,
        stockSymbol,
        Security,
        isin,
        iso4217Code,
        snapshotTotal,
        snapshotConverterSnapshot,
        snapshotSourceSnapshot;
    );
}

pub mod solid {
    namespace!(
        "http://www.w3.org/ns/solid/terms#",
        TypeRegistration,
        forClass,
        instance,
        publicTypeIndex,
        privateTypeIndex;
    );
}

pub mod space {
    namespace!(
        "http://www.w3.org/ns/pim/space#",
        preferencesFile,
        storage;
    );
}

pub mod ldp {
    namespace!(
        "http://www.w3.org/ns/ldp#",
        Container,
        contains;
    );
}

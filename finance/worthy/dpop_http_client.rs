// TODO(agentydragon): renewing tokens
// TODO(agentydragon): revoking tokens
use biscuit::jwk::{
    AlgorithmParameters, EllipticCurve, EllipticCurveKeyParameters, EllipticCurveKeyType,
};
use chrono::{serde::ts_seconds, DateTime, Utc};
use jwt::{
    algorithm::{openssl::PKeyWithDigest, AlgorithmType},
    header::JoseHeader,
    SignWithKey, Token,
};
use oauth2::reqwest::async_http_client;
use openssl::{
    bn::{BigNum, BigNumContext},
    ec::{EcGroup, EcKey, EcPointRef},
    hash::MessageDigest,
    nid::Nid,
    pkey::{PKey, Private},
};
use rand::Rng;
use reqwest::{
    header::{HeaderName, HeaderValue},
    Method,
};
use serde::Serialize;
use std::error::Error;
use std::str::FromStr;
use url::Url;

/// "DPoP" HTTP header
const HEADER_DPOP: &str = "DPoP";

#[derive(Serialize)]
struct DpopClaims<'a> {
    jti: String,
    #[serde(rename = "htm")]
    http_method: &'a str,
    #[serde(rename = "htu")]
    http_url: &'a str,
    #[serde(with = "ts_seconds", rename = "iat")]
    issued_at: DateTime<Utc>,
}

fn make_random_string<R>(rng: &mut R) -> String
where
    R: Rng,
{
    let mut random_data = [0u8; 64];
    rng.fill(&mut random_data);
    base64_urlsafe_nopad(&random_data)
}

fn base64_urlsafe_nopad(data: &[u8]) -> String {
    base64::encode_config(data, base64::URL_SAFE_NO_PAD)
}

/// HTTP client for oauth2 that signs requests with a DPoP header.
/// Used for requests that do not yet have an access token, like the first
/// token request.
pub struct DPoPSigningHttpClient<R>
where
    R: Rng,
{
    curve: EcGroup,
    key: EcKey<Private>,
    /// For generating random nonces for DPoP header.
    rng: R,
}

impl<R> DPoPSigningHttpClient<R>
where
    R: Rng,
{
    pub fn new(rng: R, key: EcKey<Private>) -> Result<Self, Box<dyn Error>> {
        Ok(DPoPSigningHttpClient {
            curve: EcGroup::from_curve_name(Nid::X9_62_PRIME256V1)?,
            key,
            rng,
        })
    }

    fn get_keypair(&self) -> Result<PKeyWithDigest<Private>, Box<dyn Error>> {
        Ok(PKeyWithDigest::<Private> {
            digest: MessageDigest::sha256(),
            key: PKey::from_ec_key(self.key.clone())?,
        })
    }

    fn make_token_for(&mut self, url: &Url, method: &Method) -> Result<String, Box<dyn Error>> {
        let header = DpopJwtHeader {
            typ: String::from("dpop+jwt"),
            alg: AlgorithmType::Es256,
            jwk: from_es256_public_key(self.key.public_key(), &self.curve)?,
        };

        let claims = DpopClaims {
            jti: make_random_string(&mut self.rng),
            http_method: method.as_str(),
            http_url: url.as_str(),
            issued_at: Utc::now(),
        };

        let token = Token::new(header, claims).sign_with_key(&self.get_keypair()?)?;
        Ok(String::from(token.as_str()))
    }

    /// Builds a DPoP header for the given URL and method.
    pub fn get_dpop_header(
        &mut self,
        url: &Url,
        method: &Method,
    ) -> Result<(HeaderName, HeaderValue), Box<dyn Error>> {
        Ok((
            HeaderName::from_str(HEADER_DPOP).unwrap(),
            HeaderValue::from_str(&self.make_token_for(url, method)?)?,
        ))
    }

    /// Signs the request before calling `oauth2::reqwest::http_client`.
    pub async fn execute_async(
        &mut self,
        mut request: oauth2::HttpRequest,
    ) -> Result<oauth2::HttpResponse, impl std::error::Error> {
        // TODO
        let dpop_header = self.get_dpop_header(&request.url, &request.method).unwrap();
        request.headers.insert(dpop_header.0, dpop_header.1);
        async_http_client(request).await
    }
}

#[derive(Serialize)]
struct DpopJwtHeader {
    typ: String,
    alg: AlgorithmType,
    jwk: AlgorithmParameters,
}

impl JoseHeader for DpopJwtHeader {
    fn algorithm_type(&self) -> AlgorithmType {
        AlgorithmType::Es256
    }
}

fn from_es256_public_key(
    pubkey: &EcPointRef,
    group: &EcGroup,
) -> Result<AlgorithmParameters, openssl::error::ErrorStack> {
    let mut ctx = BigNumContext::new()?;
    let mut x = BigNum::new()?;
    let mut y = BigNum::new()?;
    pubkey.affine_coordinates_gfp(group, &mut x, &mut y, &mut ctx)?;
    Ok(AlgorithmParameters::EllipticCurve(
        EllipticCurveKeyParameters {
            key_type: EllipticCurveKeyType::EC,
            curve: EllipticCurve::P256,
            x: x.to_vec(),
            y: y.to_vec(),
            d: None, // Private key
        },
    ))
}

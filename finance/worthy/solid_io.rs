// TODO(agentydragon): renewing tokens
// TODO(agentydragon): revoking tokens
extern crate base64;
extern crate biscuit;
extern crate chrono;
extern crate env_logger;
extern crate jwt;
extern crate log;
extern crate rand;
extern crate reqwest;
extern crate serde;
extern crate serde_json;
extern crate sophia;
extern crate sophia_term;
extern crate tokio;
extern crate url;
extern crate warp;

use chrono::{serde::ts_seconds, DateTime, Utc};
use dpop_http_client::DPoPSigningHttpClient;
use graph_util::truncate_graph;
use jwt::Token;
use log::*;
use ns::{ldp, solid, space, worthy};
use oauth2::{
    basic::BasicClient, AuthUrl, AuthorizationCode, ClientId, ClientSecret, CsrfToken,
    PkceCodeChallenge, RedirectUrl, Scope, TokenResponse, TokenUrl,
};
use openssl::{
    ec::{EcGroup, EcKey},
    nid::Nid,
};
use rand::{thread_rng, Rng};
use reqwest::{
    header::{HeaderMap, AUTHORIZATION, CONTENT_TYPE},
    Method, StatusCode,
};
use serde::{Deserialize, Serialize};
use sophia::{
    dataset::{inmem::FastDataset, Dataset, MutableDataset},
    graph::{inmem::FastGraph, Graph},
    ns::{owl, rdf, rdfs},
    parser::{turtle::TurtleParser, TripleParser},
    quad::Quad,
    serializer::{nt::NtSerializer, turtle::TurtleSerializer, Stringifier, TripleSerializer},
    term::{iri::Iri, SimpleIri, TTerm},
    triple::stream::TripleSource,
};
use sophia_term::matcher::ANY;
use std::{
    collections::HashSet,
    error::Error,
    fmt::{self, Display, Formatter},
    fs::{File, OpenOptions},
    path::PathBuf,
    sync::{Arc, Mutex},
};
use tokio::sync::mpsc;
use url::Url;
use warp::Filter;

const PORT: u16 = 3030;
// const REFRESH_TOKEN: &str = "refresh_token";
const CLIENT_SECRET_BASIC: &str = "client_secret_basic";
const CONTENT_TYPE_TURTLE: &str = "text/turtle";

fn get_redirect_uri() -> String {
    return format!("http://localhost:{}", PORT);
}

#[derive(Deserialize, Debug, Serialize)]
struct OpenIDConfiguration {
    registration_endpoint: Url,
    authorization_endpoint: Url,
    token_endpoint: Url,

    issuer: String,
    jwks_uri: Url,
    response_types_supported: Vec<String>,
    token_types_supported: Vec<String>,
    response_modes_supported: Vec<String>,
    grant_types_supported: Vec<String>,
    subject_types_supported: Vec<String>,
    id_token_signing_alg_values_supported: Vec<String>,
    // TODO(agentydragon): should this be one-or-array?
    token_endpoint_auth_methods_supported: String,
    token_endpoint_auth_signing_alg_values_supported: Vec<String>,
    display_values_supported: Vec<String>,
    claim_types_supported: Vec<String>,
    //claims_suported: Vec<String>,
    claims_parameter_supported: bool,
    request_parameter_supported: bool,
    request_uri_parameter_supported: bool,
    require_request_uri_registration: bool,
    check_session_iframe: Option<Url>,
    end_session_endpoint: Option<Url>,
    userinfo_endpoint: Url,
}

#[derive(Debug, Clone)]
struct ClientSecretBasicNotAvailable;

impl Display for ClientSecretBasicNotAvailable {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        write!(f, "client_secret_basic not available")
    }
}
impl Error for ClientSecretBasicNotAvailable {}

async fn fetch_openid_configuration(issuer: &str) -> Result<OpenIDConfiguration, Box<dyn Error>> {
    let url = format!("{}.well-known/openid-configuration", issuer);
    let response = reqwest::get(&url).await?;
    check_http_status(&response, StatusCode::OK)?;
    let openid_configuration: OpenIDConfiguration = response.json().await?;
    if openid_configuration.token_endpoint_auth_methods_supported != CLIENT_SECRET_BASIC {
        return Err(Box::new(ClientSecretBasicNotAvailable {}));
    }
    Ok(openid_configuration)
}

#[derive(Serialize)]
struct ClientRegistrationRequest {
    redirect_uris: Vec<String>,
    client_name: String,
    // TODO(agentydragon): "client_name#ja-Jpan-JP": "\u30AF\u30E9\u30A4\u30A2\u30F3\u30C8\u540D"
    token_endpoint_auth_method: String,
    // TODO(agentydragon): Optional things we might add: client_uri, logo_uri,
    // contacts, tos_uri, policy_uri, jkws_uri, software_id, software_version
}

#[derive(Deserialize, Serialize)]
struct ClientRegistrationResponse {
    redirect_uris: Vec<String>,
    client_id: String,
    client_secret: String,
    response_types: Vec<String>,
    grant_types: Vec<String>,
    application_type: String,
    client_name: String,
    id_token_signed_response_alg: String,
    token_endpoint_auth_method: String,
    registration_access_token: String,
    registration_client_uri: Url,
    #[serde(with = "ts_seconds")]
    client_id_issued_at: DateTime<Utc>,
    #[serde(with = "ts_seconds")]
    client_secret_expires_at: DateTime<Utc>,
}

/// Returns new client ID.
async fn register_client(
    provider_config: &OpenIDConfiguration,
) -> Result<ClientRegistrationResponse, Box<dyn Error>> {
    let client = reqwest::Client::new();
    let response = client
        .post(provider_config.registration_endpoint.clone())
        .json(&ClientRegistrationRequest {
            redirect_uris: vec![get_redirect_uri()],
            client_name: String::from("Rai's awesome thing"),
            token_endpoint_auth_method: String::from(CLIENT_SECRET_BASIC),
        })
        .send()
        .await?;
    check_http_status(&response, StatusCode::CREATED)?;
    Ok(response.json().await?)
}

#[derive(Deserialize, Debug, Clone)]
struct OAuthCallbackRequest {
    code: AuthorizationCode,
    state: String,
}

#[derive(Debug, Clone)]
struct UnexpectedHttpStatus {
    expected: StatusCode,
    actual: StatusCode,
    headers: HeaderMap,
    url: Url,
}

impl Display for UnexpectedHttpStatus {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        write!(
            f,
            "unexpected http status on {} (expected {}, got {}); headers: {:?}",
            self.url, self.expected, self.actual, self.headers
        )
    }
}

impl Error for UnexpectedHttpStatus {}

fn check_http_status(
    response: &reqwest::Response,
    expected_status: StatusCode,
) -> Result<(), UnexpectedHttpStatus> {
    match response.status() {
        s if s == expected_status => Ok(()),
        s => Err(UnexpectedHttpStatus {
            expected: expected_status,
            actual: s,
            headers: response.headers().clone(),
            url: response.url().clone(),
        }),
    }
}

// #[derive(Serialize)]
// struct RefreshTokenRequest<'a> {
//     grant_type: &'a str,
//     refresh_token: &'a str,
//     //client_id: &'a str,
//     //client_secret: &'a str,
// }

#[derive(Deserialize, Debug)]
struct AccessTokenClaims {
    /// Example: https://agentydragon.solidcommunity.net/profile/card#me
    webid: String,

    /// Issuer. https://tools.ietf.org/html/rfc7519#section-4.1.1
    #[serde(rename = "iss")]
    issuer: String,

    /// Expiration time.
    /// https://tools.ietf.org/html/rfc7519#section-4.1.6
    #[serde(with = "ts_seconds", rename = "exp")]
    expiration_time: DateTime<Utc>,

    client_id: String,

    /// Issued at.
    /// https://tools.ietf.org/html/rfc7519#section-4.1.6
    #[serde(with = "ts_seconds", rename = "iat")]
    issued_at: DateTime<Utc>,

    /// Audience.
    /// https://tools.ietf.org/html/rfc7519#section-4.1.3
    // solid
    #[serde(rename = "aud")]
    audience: String,

    // cnf: {"jkt": "cQZwUTYejqpoaRZMV3hBoweOFS97edr2QUKl0SQTd30"}
    // https://curity.io/resources/architect/oauth/dpop-overview/
    // base64 encoding of sha-256 thumbprint of public key used to sign the dpop token
    /// Subject.
    /// https://tools.ietf.org/html/rfc7519#section-4.1.2
    #[serde(rename = "sub")]
    subject: String,
}

fn graph_to_turtle<G>(graph: G) -> Result<String, Box<dyn Error>>
where
    G: Graph,
{
    let mut stringifier = TurtleSerializer::new_stringifier();
    stringifier.serialize_graph(&graph)?;
    // TODO: should be possible to stream the turtle and do this lazily...
    Ok(stringifier.to_string())
}

fn graph_to_nt<G>(graph: G) -> Result<String, Box<dyn Error>>
where
    G: Graph,
{
    let mut stringifier = NtSerializer::new_stringifier();
    stringifier.serialize_graph(&graph)?;
    // TODO: should be possible to stream the turtle and do this lazily...
    Ok(stringifier.to_string())
}

impl<R> AuthenticatedClient<R>
where
    R: Rng,
{
    // Pending https://github.com/solid/node-solid-server/issues/1533
    //async fn refresh_access_token(&mut self) -> Result<(), Box<dyn Error>> {
    //    let url = &self.client.openid_configuration.token_endpoint;
    //    // https://stackoverflow.com/questions/55576538/401-malformed-http-basic-authorization-header-error-on-executing-api-through-re
    //    let auth_header = format!(
    //        "Basic {}",
    //        base64_urlsafe_nopad(
    //            // TODO: percent-encode?
    //            format!("{}:{}", self.client.client_id, self.client.client_secret).as_bytes()
    //        )
    //    );
    //    let response = self
    //        .http_client
    //        .post(url.clone())
    //        .form(&RefreshTokenRequest {
    //            grant_type: REFRESH_TOKEN,
    //            refresh_token: self.refresh_token.as_ref().unwrap(),
    //            //client_id: &self.client.client_id,
    //            //client_secret: &self.client.client_secret,
    //        })
    //        .headers(self.add_dpop_header(&url, &Method::POST, HeaderMap::new())?)
    //        // https://github.com/panva/node-openid-client/blob/588bee948b1af83446b7e3d8f4076131d1f2d343/lib/helpers/client.js#L86
    //        // TODO: client secret and id should also be URL encoded
    //        .header("Authorization", auth_header)
    //        .send()
    //        .await?;
    //}

    fn request(
        &mut self,
        method: Method,
        url: Url,
    ) -> Result<reqwest::RequestBuilder, Box<dyn Error>> {
        let dpop_header = self.signing_client.get_dpop_header(&url, &method)?;
        Ok(reqwest::Client::new()
            .request(method, url)
            .header(
                AUTHORIZATION,
                format!("DPoP {}", self.access_token.as_ref().unwrap().secret()),
            )
            .header(dpop_header.0, dpop_header.1))
    }

    async fn get_graph<DS>(&mut self, url: Url, dataset: &mut DS) -> Result<(), Box<dyn Error>>
    where
        DS: MutableDataset,
    {
        info!("Getting from: {}", &url);
        let response = self.request(Method::GET, url.clone())?.send().await?;
        check_http_status(&response, StatusCode::OK)?;
        let new_turtle = response.text().await?;

        let doc = SimpleIri::new(url.as_str(), None)?;
        let mut graph = dataset.graph_mut(Some(&doc));
        truncate_graph(&mut graph)?;
        TurtleParser {
            base: Some(url.to_string()),
        }
        .parse_str(&new_turtle)
        .add_to_graph(&mut graph)?;

        Ok(())
    }

    async fn insert_triples<G>(&mut self, url: Url, trips: G) -> Result<(), Box<dyn Error>>
    where
        G: Graph,
    {
        // DELETE DATA { <> <http://purl.org/dc/terms/title> "Basic container" };
        // INSERT DATA { <> <http://purl.org/dc/terms/title> "My data container" }
        let mut s = String::new();
        s.push_str("INSERT DATA {");
        s.push_str(&graph_to_nt(trips)?);
        s.push('}');
        info!("would patch: {}", s);

        let response = self
            .request(Method::PATCH, url)?
            .body(s)
            .header(CONTENT_TYPE, "application/sparql-update")
            .send()
            .await?;
        info!("status: {:?}", response.status());
        info!("headers: {:?}", response.headers());
        check_http_status(&response, StatusCode::OK)?;
        Ok(())
    }

    async fn put_graph<G>(&mut self, url: Url, graph: G) -> Result<(), Box<dyn Error>>
    where
        G: Graph,
    {
        let response = self
            .request(Method::PUT, url)?
            .body(graph_to_turtle(graph)?)
            .header(CONTENT_TYPE, CONTENT_TYPE_TURTLE)
            .send()
            .await?;
        info!("Status: {:?}", response.status());
        check_http_status(&response, StatusCode::CREATED)?;
        Ok(())
    }

    /// Returns location (like /private/worthydir/todo-agentydragon-make-slug.ttl)
    async fn post_graph<G>(
        &mut self,
        base_url: Url,
        slug: String,
        graph: G,
    ) -> Result<String, Box<dyn Error>>
    where
        G: Graph,
    {
        let response = self
            .request(Method::POST, base_url)?
            .body(graph_to_turtle(graph)?)
            .header(CONTENT_TYPE, CONTENT_TYPE_TURTLE)
            .header("Slug", slug)
            .send()
            .await?;
        info!("Status: {:?}", response.status());
        info!("headers: {:?}", response.headers());
        // TODO(agentydragon): Display response text in errors, it's useful:
        check_http_status(&response, StatusCode::CREATED)?;
        Ok(response.headers()["location"].to_str()?.to_string())
    }
}

struct SolidView<R, DS>
where
    R: Rng,
    DS: MutableDataset,
{
    authenticated_client: AuthenticatedClient<R>,
    dataset: DS,
    webid: String,
}

impl<R, DS> SolidView<R, DS>
where
    R: Rng,
    DS: MutableDataset,
{
    fn webid_iri(&self) -> Result<SimpleIri, Box<dyn Error>> {
        Ok(SimpleIri::new(self.webid.as_str(), None)?)
    }

    async fn refresh_resource(&mut self, url: Url) -> Result<(), Box<dyn Error>> {
        self.authenticated_client
            .get_graph(url, &mut self.dataset)
            .await
    }

    async fn load_extended_profile(&mut self) -> Result<(), Box<dyn Error>> {
        // Fetch the profile: https://github.com/solid/solid/blob/main/proposals/app-discovery.md#fetching-the-profile
        let webid_url = Url::parse(&self.webid)?;
        let mut loaded: HashSet<Url> = HashSet::new();
        let profile_url = strip_fragment(&webid_url);
        loaded.insert(profile_url.clone());
        self.refresh_resource(profile_url).await?;

        let mut pref_files = Vec::new();
        for t in self.dataset.quads_matching(
            &self.webid_iri()?,
            &[&space::preferencesFile, &rdfs::seeAlso, &owl::sameAs],
            &ANY,
            &ANY,
        ) {
            let val: String = t?.o().value().to();
            pref_files.push(Url::parse(&val)?);
        }
        for file in pref_files {
            self.refresh_resource(file.clone()).await?;
            loaded.insert(file);
        }

        // TODO: in case some of those preference files returned more, load them as well.
        Ok(())
    }

    async fn load_type_indices(&mut self) -> Result<(), Box<dyn Error>> {
        let type_indices: Result<HashSet<String>, Box<dyn Error>> = self
            .dataset
            .quads_matching(
                &self.webid_iri()?,
                &[&solid::publicTypeIndex, &solid::privateTypeIndex],
                &ANY,
                &ANY,
            )
            .into_iter()
            .map(|t| Ok(t?.o().value().to()))
            .collect();
        // TODO: this can be done in parallel
        let type_indices: Result<Vec<Url>, _> = type_indices?
            .into_iter()
            .map(|file| Url::parse(&file))
            .collect();
        for type_index in type_indices? {
            self.refresh_resource(type_index).await?;
        }
        Ok(())
    }

    async fn find_registered_path_or_register(&mut self) -> Result<String, Box<dyn Error>> {
        Ok(match find_registered_path(&self.dataset)? {
            Some(path) => {
                info!("Worthy snapshots already registered: {:?}", &path);
                path
            }
            None => {
                info!("Worthy snapshots not registered in type index yet. Will register them.");
                self.create_new_registration().await?;
                find_registered_path(&self.dataset)?
                    .expect("after registration, still could not find registration")
            }
        })
    }

    async fn create_new_registration(&mut self) -> Result<(), Box<dyn Error>> {
        let webid_iri = self.webid_iri()?;
        let private_index = find_private_type_index(&webid_iri, &self.dataset)?;
        let trip = self
            .dataset
            .quads_matching(&webid_iri, &space::storage, &ANY, &ANY)
            .into_iter()
            .next()
            .expect("need next")?;
        // TODO: should have exactly 1 storage
        let t: String = trip.o().value().to();
        // "https://agentydragon.solidcommunity.net/"
        info!("storage: {:?}", t);

        // TODO: ask people where they want to put it, instead of assuming a location
        let our_dir = format!("{}private/worthydir/", t);
        let our_dir_iri = SimpleIri::new(&our_dir, None)?;

        // TODO: check for existence of the dir before trying to create it

        // try to create it
        self.authenticated_client
            .put_graph(
                Url::parse(&our_dir)?,
                vec![[our_dir_iri, rdf::type_, ldp::Container]],
            )
            .await?;

        // Find the private one.
        let private_index_url: Url = Url::parse(&private_index.to_string())?;
        let entry_path = format!("{}#worthy", private_index);
        let elem = SimpleIri::new(&entry_path, None)?;
        self.authenticated_client
            .insert_triples(
                private_index_url.clone(),
                vec![
                    [elem, rdf::type_, solid::TypeRegistration],
                    [elem, solid::forClass, worthy::Snapshot],
                    [elem, solid::instance, our_dir_iri],
                ],
            )
            .await?;

        // Reload the private type index.
        self.refresh_resource(private_index_url).await?;

        Ok(())
    }
}

// TODO: add method for removing type index registration:
//  :worthy a ter:TypeRegistration; ter:forClass voc:Snapshot.

// TODO: if we get variants of 401, reset token

async fn obtain_code_and_state() -> Result<OAuthCallbackRequest, Box<dyn Error>> {
    let request: Arc<Mutex<Option<OAuthCallbackRequest>>> = Arc::new(Mutex::new(None));
    let (tx, mut rx) = mpsc::channel(1);

    let c_request = Arc::clone(&request);

    let routes = warp::query().map(move |oauth_request: OAuthCallbackRequest| {
        tx.try_send(()).expect("shutdown webserver");
        *c_request.lock().unwrap() = Some(oauth_request);
        "We got an access token, you can go back to your CLI.".to_string()
    });

    let (_addr, server) =
        warp::serve(routes).bind_with_graceful_shutdown(([127, 0, 0, 1], PORT), async move {
            rx.recv().await;
        });

    tokio::task::spawn(server).await?;

    Ok(Arc::try_unwrap(request)
        .expect("Arc has >1 strong reference?")
        .into_inner()
        .expect("cannot lock mutex?")
        .expect("no OAuthCallbackRequest present"))
}

struct AuthenticatedClient<R>
where
    R: Rng,
{
    access_token: Option<oauth2::AccessToken>,
    signing_client: DPoPSigningHttpClient<R>,
}

#[derive(Serialize, Deserialize)]
struct Cache {
    client_registration: ClientRegistrationResponse,
    openid_configuration: OpenIDConfiguration,
    access_token: Option<oauth2::AccessToken>,
    refresh_token: Option<String>,

    /// PEM format private key.
    private_key: Vec<u8>,
}

pub fn find_private_type_index<DS>(
    webid_iri: &SimpleIri,
    dataset: &DS,
) -> Result<String, Box<dyn Error>>
where
    DS: Dataset,
{
    let type_indices: Result<HashSet<String>, Box<dyn Error>> = dataset
        .quads_matching(webid_iri, &solid::privateTypeIndex, &ANY, &ANY)
        .into_iter()
        .map(|t| Ok(t?.o().value().to()))
        .collect();
    let type_indices = type_indices?;
    assert_eq!(type_indices.len(), 1, "argh no priate type index");
    Ok(type_indices.into_iter().next().unwrap())
}

pub fn find_registered_path<DS>(dataset: &DS) -> Result<Option<String>, Box<dyn Error>>
where
    DS: Dataset,
{
    // TODO: maybe we should only be looking specifically within the type registers?
    // <#ab09fd> a solid:TypeRegistration;
    //     solid:forClass vcard:AddressBook;
    //     solid:instance </contacts/myPublicAddressBook.ttl>.
    let mut registrations: Vec<String> = Vec::new();
    for t in dataset.quads_matching(&ANY, &rdf::type_, &solid::TypeRegistration, &ANY) {
        let t = t?;
        if !dataset.contains(t.s(), &solid::forClass, &worthy::Snapshot, t.g())? {
            continue;
        }
        for t2 in dataset.quads_matching(t.s(), &solid::instance, &ANY, &t.g()) {
            registrations.push(t2?.o().value().to());
        }
    }
    match registrations.len() {
        0 => Ok(None),
        1 => Ok(Some(registrations[0].clone())),
        _ => panic!("multiple registrations!"),
    }
    // TODO: use queries:
    //   let registration_var = RcTerm::new_variable("registration").unwrap();
    //   let instance_var = RcTerm::new_variable("instance").unwrap();
    //   let mut q = Query::Triples(vec![
    //     [registration_var.clone(), &rdf::type_, &solid::TypeRegistration],
    //     [registration_var.clone(), &solid::forClass, &worthy::Snapshot],
    //     [registration_var.clone(), &solid::instance, instance_var.clone()],
    //   ]);
    //   let results: Result<Vec<BindingMap>, _> = q.process(&g).collect();
    //   let results = results?;
}

fn strip_fragment(url: &Url) -> Url {
    let mut url = url.clone();
    url.set_fragment(None);
    url
}

fn extract_webid(access_token: &oauth2::AccessToken) -> Result<String, Box<dyn Error>> {
    // TODO: could we verify those?
    #[derive(Debug, Deserialize)]
    struct WebIdHeader {}
    #[derive(Debug, Deserialize)]
    struct WebIdClaim {
        webid: String,
    }
    let sec = access_token.clone().secret().clone();
    let tok: Token<WebIdHeader, WebIdClaim, _> = Token::parse_unverified(&sec)?;
    Ok(tok.claims().webid.clone())
}

pub async fn write_to_solid(
    issuer: &str,
    cache_file: &PathBuf,
    snapshot: graph_output::Snapshot,
    slug: String,
) -> Result<(), Box<dyn Error>> {
    let mut cache = if cache_file.exists() {
        serde_json::from_reader(File::open(cache_file)?)?
    } else {
        info!("Registering new client.");
        let openid_configuration = fetch_openid_configuration(issuer).await?;
        let client_registration = register_client(&openid_configuration).await?;
        let curve = EcGroup::from_curve_name(Nid::X9_62_PRIME256V1)?;
        Cache {
            client_registration,
            openid_configuration,
            private_key: EcKey::generate(&curve)?.private_key_to_pem()?,
            access_token: None,
            refresh_token: None,
        }
    };
    let private_key = EcKey::private_key_from_pem(cache.private_key.as_slice())?;
    let mut signing_client = DPoPSigningHttpClient::new(thread_rng(), private_key)?;

    // TODO: if access token times out soon, set it to None and reset it
    if cache.access_token.is_none() {
        // Create an OAuth2 client by specifying client stuff.
        let oauth2_client = BasicClient::new(
            ClientId::new(cache.client_registration.client_id.clone()),
            Some(ClientSecret::new(
                cache.client_registration.client_secret.clone(),
            )),
            AuthUrl::new(
                cache
                    .openid_configuration
                    .authorization_endpoint
                    .to_string(),
            )?,
            Some(TokenUrl::new(
                cache.openid_configuration.token_endpoint.to_string(),
            )?),
        )
        .set_redirect_uri(RedirectUrl::new(get_redirect_uri())?);
        // TODO: check that redirect URI is still the same!
        // Generate a PKCE challenge.
        let (pkce_challenge, pkce_verifier) = PkceCodeChallenge::new_random_sha256();
        let (the_url, csrf_token) = oauth2_client
            .authorize_url(CsrfToken::new_random)
            .add_scope(Scope::new("openid".to_string()))
            // TODO: https://solid.github.io/authentication-panel/solid-oidc-primer/
            // says "open_id", "profile" offline_access also requests a refresh token.
            .add_scope(Scope::new("offline_access".to_string()))
            .set_pkce_challenge(pkce_challenge)
            .url();
        println!("Open this URL to authorize access to the pod: {}", the_url);

        let oauth_callback_request = obtain_code_and_state().await?;
        assert_eq!(&oauth_callback_request.state, csrf_token.secret());
        // Exchange auth code for access token.
        let token_result = oauth2_client
            .exchange_code(oauth_callback_request.code.clone())
            .set_pkce_verifier(pkce_verifier)
            .request_async(|request| signing_client.execute_async(request))
            .await?;

        cache.access_token = Some(token_result.access_token().clone());
        cache.refresh_token = token_result.refresh_token().map(|rt| rt.secret().clone());
    }

    let mut solid_view = SolidView {
        authenticated_client: AuthenticatedClient {
            signing_client,
            access_token: cache.access_token.clone(),
        },
        dataset: FastDataset::new(),
        webid: extract_webid(
            cache
                .access_token
                .as_ref()
                .expect("should have access token at this point"),
        )?,
    };

    solid_view.load_extended_profile().await?;
    solid_view.load_type_indices().await?;

    let registered_path = solid_view.find_registered_path_or_register().await?;

    {
        info!("Uploading new snapshot with slug {}...", &slug);
        let mut graph = FastGraph::new();
        // With <> as URL, Solid will automatically point to the URI of the new entity.
        let iri = Iri::<String>::new("").unwrap();
        graph_output::add_snapshot(&mut graph, &iri.into(), snapshot).unwrap();
        let new_location = solid_view
            .authenticated_client
            .post_graph(Url::parse(&registered_path)?, slug, graph)
            .await?;
        // TODO: it can be a relative URL
        info!("New location: {}", new_location);
    }

    serde_json::to_writer(
        OpenOptions::new()
            .write(true)
            .create(true)
            .open(cache_file)?,
        &cache,
    )?;
    Ok(())
}

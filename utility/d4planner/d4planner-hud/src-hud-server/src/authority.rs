//! Validate the transport's parsed authority against this listener, never a
//! forwarded header. HTTP/2 represents :authority in the request URI.
use crate::model::Error;
use axum::http::{header::HOST, Request, Version};

pub(crate) fn validate<B>(request: &Request<B>, origin: &str) -> Result<(), Error> {
    let reject = || Error::new(403, "HOST_REJECTED");
    let (scheme, expected) = origin.split_once("://").ok_or_else(reject)?;
    let mut hosts = request.headers().get_all(HOST).iter();
    let host = hosts
        .next()
        .map(|v| v.to_str())
        .transpose()
        .map_err(|_| reject())?;
    if hosts.next().is_some() || host.is_some_and(|value| value != expected) {
        return Err(reject());
    }
    let authority = request.uri().authority().map(|value| value.as_str());
    if authority.is_some_and(|value| value != expected)
        || request
            .uri()
            .scheme_str()
            .is_some_and(|value| value != scheme)
    {
        return Err(reject());
    }
    match request.version() {
        Version::HTTP_10 | Version::HTTP_11 if host == Some(expected) => Ok(()),
        Version::HTTP_2 if authority == Some(expected) => Ok(()),
        _ => Err(reject()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn versioned_authority_matrix_is_fail_closed() {
        let origin = "https://192.168.1.20:6090";
        for (version, uri, host, accepted) in [
            (Version::HTTP_11, "/", Some("192.168.1.20:6090"), true),
            (Version::HTTP_10, "/", Some("192.168.1.20:6090"), true),
            (Version::HTTP_11, origin, Some("192.168.1.20:6090"), true),
            (Version::HTTP_11, origin, None, false),
            (
                Version::HTTP_11,
                "https://attacker.example:6090/",
                Some("192.168.1.20:6090"),
                false,
            ),
            (Version::HTTP_2, origin, None, true),
            (Version::HTTP_2, origin, Some("192.168.1.20:6090"), true),
            (
                Version::HTTP_2,
                origin,
                Some("attacker.example:6090"),
                false,
            ),
            (
                Version::HTTP_2,
                "https://attacker.example:6090/",
                Some("192.168.1.20:6090"),
                false,
            ),
            (Version::HTTP_2, "/", Some("192.168.1.20:6090"), false),
            (Version::HTTP_2, "/", None, false),
            (Version::HTTP_2, "https://192.168.1.20:6091/", None, false),
            (Version::HTTP_2, "https://192.168.1.20/", None, false),
            (Version::HTTP_2, "http://192.168.1.20:6090/", None, false),
            (
                Version::HTTP_2,
                "https://user@192.168.1.20:6090/",
                None,
                false,
            ),
            (Version::HTTP_3, origin, Some("192.168.1.20:6090"), false),
        ] {
            let mut builder = Request::builder().version(version).uri(uri);
            if let Some(host) = host {
                builder = builder.header(HOST, host);
            }
            let request = builder.body(()).unwrap();
            assert_eq!(
                validate(&request, origin).is_ok(),
                accepted,
                "{version:?} {uri} {host:?}"
            );
        }
        for values in [
            vec!["192.168.1.20:6090", "192.168.1.20:6090"],
            vec!["192.168.1.20:6090", "attacker.example:6090"],
        ] {
            let mut request = Request::builder()
                .version(Version::HTTP_2)
                .uri(origin)
                .body(())
                .unwrap();
            for value in values {
                request.headers_mut().append(HOST, value.parse().unwrap());
            }
            assert!(validate(&request, origin).is_err());
        }
        let request = Request::builder()
            .header("x-forwarded-host", "192.168.1.20:6090")
            .body(())
            .unwrap();
        assert!(validate(&request, origin).is_err());
    }
}

use crate::{model::*, router, Feed, HttpState};
use std::{net::TcpListener, sync::Arc, time::Duration};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

/// Runs inside the caller's Tokio runtime and process. Owns only this listener;
/// stopping it never stops the Backend, Rule Kit, or a foreign listener.
pub struct RunningServer {
    handle: axum_server::Handle,
    stop: CancellationToken,
    task: Option<JoinHandle<std::io::Result<()>>>,
    planner_handle: axum_server::Handle,
    planner_task: Option<JoinHandle<std::io::Result<()>>>,
    pub url: String,
    dispatcher: crate::Dispatcher,
}
impl RunningServer {
    pub async fn start(config: Config, host: Arc<dyn Host>) -> Result<Self, Error> {
        config.validate()?;
        if host.asset("index.html").is_none() {
            return Err(Error::new(503, "WEB_ASSETS_UNAVAILABLE"));
        }
        let listener = TcpListener::bind(config.socket(false))
            .map_err(|_| Error::new(503, "WEB_PORT_UNAVAILABLE"))?;
        listener
            .set_nonblocking(true)
            .map_err(|_| Error::new(503, "WEB_START_FAILED"))?;
        let planner_listener = TcpListener::bind(config.socket(true))
            .map_err(|_| Error::new(503, "WEB_PORT_UNAVAILABLE"))?;
        planner_listener
            .set_nonblocking(true)
            .map_err(|_| Error::new(503, "WEB_START_FAILED"))?;
        let tls = match (&config.certificate, &config.private_key) {
            (Some(cert), Some(key)) => {
                // Explicit provider avoids feature-unification-dependent defaults.
                let _ = rustls::crypto::ring::default_provider().install_default();
                Some(
                    axum_server::tls_rustls::RustlsConfig::from_pem_file(cert, key)
                        .await
                        .map_err(|_| Error::new(503, "WEB_TLS_UNAVAILABLE"))?,
                )
            }
            _ => None,
        };
        let url = config.origin(false);
        let stop = CancellationToken::new();
        let feed = Feed::spawn(host.clone(), stop.clone());
        let state = HttpState::new(config, host)?.with_feed(feed);
        let dispatcher = state.dispatcher.clone();
        let app = router(state.clone());
        let planner_app = crate::relay::router(state);
        let planner_handle = axum_server::Handle::new();
        let ph = planner_handle.clone();
        let ptls = tls.clone();
        let planner_task = tokio::spawn(async move {
            match ptls {
                Some(tls) => {
                    axum_server::from_tcp_rustls(planner_listener, tls)
                        .handle(ph)
                        .serve(planner_app.into_make_service())
                        .await
                }
                None => {
                    axum_server::from_tcp(planner_listener)
                        .handle(ph)
                        .serve(planner_app.into_make_service())
                        .await
                }
            }
        });
        let handle = axum_server::Handle::new();
        let server_handle = handle.clone();
        let task = tokio::spawn(async move {
            match tls {
                Some(tls) => {
                    axum_server::from_tcp_rustls(listener, tls)
                        .handle(server_handle)
                        .serve(app.into_make_service())
                        .await
                }
                None => {
                    axum_server::from_tcp(listener)
                        .handle(server_handle)
                        .serve(app.into_make_service())
                        .await
                }
            }
        });
        // This checks the actual server accept loop, not just successful bind.
        if tokio::time::timeout(Duration::from_secs(5), handle.listening())
            .await
            .ok()
            .flatten()
            .is_none()
        {
            stop.cancel();
            handle.shutdown();
            planner_handle.shutdown();
            task.abort();
            planner_task.abort();
            return Err(Error::new(503, "WEB_START_FAILED"));
        }
        if tokio::time::timeout(Duration::from_secs(5), planner_handle.listening())
            .await
            .ok()
            .flatten()
            .is_none()
        {
            stop.cancel();
            handle.shutdown();
            planner_handle.shutdown();
            task.abort();
            planner_task.abort();
            return Err(Error::new(503, "WEB_START_FAILED"));
        }
        Ok(Self {
            handle,
            stop,
            task: Some(task),
            planner_handle,
            planner_task: Some(planner_task),
            url,
            dispatcher,
        })
    }
    pub fn is_running(&self) -> bool {
        self.task.as_ref().is_some_and(|task| !task.is_finished())
            && self
                .planner_task
                .as_ref()
                .is_some_and(|task| !task.is_finished())
    }
    pub async fn shutdown(mut self) -> Result<(), Error> {
        self.stop.cancel();
        self.dispatcher.close();
        self.handle.graceful_shutdown(Some(Duration::from_secs(2)));
        self.planner_handle
            .graceful_shutdown(Some(Duration::from_secs(2)));
        if let Some(mut task) = self.planner_task.take() {
            if tokio::time::timeout(Duration::from_secs(3), &mut task)
                .await
                .is_err()
            {
                self.planner_handle.shutdown();
                task.abort();
                let _ = task.await;
            }
        }
        if let Some(mut task) = self.task.take() {
            match tokio::time::timeout(Duration::from_secs(3), &mut task).await {
                Ok(Ok(Ok(()))) => {}
                Ok(_) => return Err(Error::new(503, "WEB_SHUTDOWN_FAILED")),
                Err(_) => {
                    self.handle.shutdown();
                    task.abort();
                    let _ = task.await;
                    return Err(Error::new(503, "WEB_SHUTDOWN_TIMEOUT"));
                }
            }
        }
        self.dispatcher.drain().await?;
        Ok(())
    }
}
impl Drop for RunningServer {
    fn drop(&mut self) {
        self.dispatcher.close();
        self.stop.cancel();
        self.handle.shutdown();
        self.planner_handle.shutdown();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{json, Value};
    use sha2::{Digest, Sha256};
    struct Fake;
    impl Host for Fake {
        fn read_hud(&self) -> Result<Option<Value>, Error> {
            Ok(None)
        }
        fn bootstrap(&self) -> Result<Bootstrap, Error> {
            Err(Error::unavailable())
        }
        fn runtime(&self) -> Result<Value, Error> {
            Ok(json!({"state":"STOPPED"}))
        }
        fn operation(&self, _: Operation, _: Value, _: Actor) -> Result<Value, Error> {
            Err(Error::unavailable())
        }
        fn asset(&self, path: &str) -> Option<Asset> {
            (path == "index.html").then(|| Asset {
                body: b"shared-react-build".to_vec(),
                content_type: "text/html".into(),
            })
        }
    }
    fn config(port: u16) -> Config {
        Config {
            address: "127.0.0.1".parse().unwrap(),
            port,
            planner_port: if port == 6091 { 6092 } else { 6091 },
            certificate: None,
            private_key: None,
            credentials: vec![Credential {
                subject: "test".into(),
                sha256: format!("{:x}", Sha256::digest(b"01234567890123456789012345678901")),
                permissions: ["hud.read".into()].into(),
            }],
        }
    }
    #[tokio::test]
    async fn real_http_shutdown_releases_only_owned_port() {
        let reservation = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = reservation.local_addr().unwrap().port();
        drop(reservation);
        let server = RunningServer::start(config(port), Arc::new(Fake))
            .await
            .unwrap();
        assert!(server.is_running());
        let response = reqwest::get(&server.url).await.unwrap();
        assert_eq!(response.status(), 200);
        assert_eq!(response.text().await.unwrap(), "shared-react-build");
        let foreign = TcpListener::bind("127.0.0.1:0").unwrap();
        let foreign_port = foreign.local_addr().unwrap().port();
        assert_eq!(
            RunningServer::start(config(foreign_port), Arc::new(Fake))
                .await
                .err()
                .unwrap()
                .code,
            "WEB_PORT_UNAVAILABLE"
        );
        server.shutdown().await.unwrap();
        let rebound = TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, port)).unwrap();
        assert!(TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, foreign_port)).is_err());
        drop(rebound);
        drop(foreign);
    }
}

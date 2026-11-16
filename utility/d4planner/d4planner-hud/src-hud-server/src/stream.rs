use crate::model::*;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use std::{sync::Arc, time::Duration};
use tokio::sync::watch;
use tokio_tungstenite::tungstenite::{client::IntoClientRequest, Message};
use tokio_util::sync::CancellationToken;

/// Full, validated projection. Notifications are only invalidation hints and are
/// never exposed as display data. The native Host validates the SQLite schema.
#[derive(Clone)]
pub struct Feed {
    pub receiver: watch::Receiver<Value>,
}
impl Feed {
    pub fn spawn(host: Arc<dyn Host>, stop: CancellationToken) -> Self {
        let (sender, receiver) = watch::channel(
            json!({"schemaVersion":VERSION,"type":"state","connected":false,"snapshot":null,"runtime":null,"sequence":0}),
        );
        tokio::spawn(observe(host, sender, stop));
        Self { receiver }
    }
}
async fn observe(host: Arc<dyn Host>, sender: watch::Sender<Value>, stop: CancellationToken) {
    let mut sequence = 0u64;
    let mut previous = Value::Null;
    loop {
        if stop.is_cancelled() {
            break;
        }
        publish(&host, &sender, false, &mut previous, &mut sequence).await;
        let h = host.clone();
        let bootstrap = tokio::task::spawn_blocking(move || h.bootstrap()).await;
        if let Ok(Ok(bootstrap)) = bootstrap {
            // Never use a remote endpoint supplied by a malformed bootstrap.
            let safe = reqwest::Url::parse(&bootstrap.endpoint).is_ok_and(|url| {
                url.scheme() == "ws"
                    && matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))
                    && url.username().is_empty()
                    && url.password().is_none()
            });
            if safe {
                // BE validates the HTTP Origin as well as the authenticated hello.
                // Native clients must supply the same approved origin explicitly.
                let Ok(mut request) = bootstrap.endpoint.clone().into_client_request() else {
                    continue;
                };
                let Ok(origin) = bootstrap.origin.parse() else {
                    continue;
                };
                request.headers_mut().insert("origin", origin);
                let connection = tokio::select! {_ = stop.cancelled()=>break, result=tokio::time::timeout(Duration::from_secs(5),tokio_tungstenite::connect_async(request))=>result};
                if let Ok(Ok((mut socket, _))) = connection {
                    let id = uuid::Uuid::new_v4().to_string();
                    let hello = json!({"protocolVersion":"d4planner-notify/v1","type":"hello","messageId":id,"credential":bootstrap.credential,"origin":bootstrap.origin});
                    if socket
                        .send(Message::Text(hello.to_string().into()))
                        .await
                        .is_ok()
                    {
                        let mut accepted = false;
                        let mut ticker = tokio::time::interval(Duration::from_secs(2));
                        ticker.tick().await;
                        loop {
                            tokio::select! {
                                _=stop.cancelled()=>{let _=socket.close(None).await;return;}
                                _=ticker.tick()=>{
                                    if !accepted {break;}
                                    publish(&host,&sender,true,&mut previous,&mut sequence).await;
                                }
                                message=socket.next()=>{
                                    match message {
                                        Some(Ok(Message::Text(text)))=>{
                                            let Ok(value)=serde_json::from_str::<Value>(&text) else{break;};
                                            if value["protocolVersion"]!="d4planner-notify/v1" {break;}
                                            if !accepted && value["type"]=="hello.accepted" && value["correlationId"]==id {
                                                accepted=true;
                                                publish(&host,&sender,true,&mut previous,&mut sequence).await;
                                            } else if accepted && value["type"]=="hud.committed" {
                                                publish(&host,&sender,true,&mut previous,&mut sequence).await;
                                            } else {break;}
                                        }
                                        Some(Ok(Message::Ping(data)))=>{if socket.send(Message::Pong(data)).await.is_err(){break;}}
                                        _=>break,
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        tokio::select! {_=stop.cancelled()=>break,_=tokio::time::sleep(Duration::from_secs(2))=>{}}
    }
}
async fn publish(
    host: &Arc<dyn Host>,
    sender: &watch::Sender<Value>,
    connected: bool,
    previous: &mut Value,
    sequence: &mut u64,
) {
    let h = host.clone();
    // Serial observation bounds the number of native reads; never spawn an
    // unbounded sequence of detached readers on a slow database.
    let result = tokio::task::spawn_blocking(move || (h.read_hud(), h.runtime())).await;
    let (snapshot, runtime) = match result {
        Ok((Ok(snapshot), Ok(runtime))) => (snapshot, runtime),
        _ => {
            let mut stale = previous.clone();
            if let Some(object) = stale.as_object_mut() {
                object.insert("connected".into(), json!(false));
            }
            if stale != *previous {
                *previous = stale.clone();
                *sequence += 1;
                stale["sequence"] = json!(sequence);
                sender.send_replace(stale);
            }
            return;
        }
    };
    let old = &previous["snapshot"];
    if let Some(current) = &snapshot {
        if current["dbId"] == old["dbId"]
            && current["epoch"] == old["epoch"]
            && current["hudRevision"]
                .as_u64()
                .zip(old["hudRevision"].as_u64())
                .is_some_and(|(a, b)| a < b)
        {
            let mut stale = previous.clone();
            stale["connected"] = json!(false);
            if stale != *previous {
                *previous = stale.clone();
                *sequence += 1;
                stale["sequence"] = json!(sequence);
                sender.send_replace(stale);
            }
            return;
        }
    }
    let value = json!({"schemaVersion":VERSION,"type":"state","connected":connected,"snapshot":snapshot,"runtime":runtime});
    if &value != previous {
        *previous = value.clone();
        *sequence += 1;
        let mut envelope = value;
        envelope["sequence"] = json!(sequence);
        sender.send_replace(envelope);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;
    struct Fake {
        endpoint: String,
        value: Mutex<Value>,
    }
    impl Host for Fake {
        fn read_hud(&self) -> Result<Option<Value>, Error> {
            Ok(Some(self.value.lock().unwrap().clone()))
        }
        fn bootstrap(&self) -> Result<Bootstrap, Error> {
            Ok(Bootstrap {
                endpoint: self.endpoint.clone(),
                credential: "fixture-credential-never-export-000".into(),
                origin: "tauri://localhost".into(),
            })
        }
        fn runtime(&self) -> Result<Value, Error> {
            Ok(json!({"backend":{"state":"READY"}}))
        }
        fn operation(&self, _: Operation, _: Value, _: Actor) -> Result<Value, Error> {
            Err(Error::unavailable())
        }
        fn asset(&self, _: &str) -> Option<Asset> {
            None
        }
    }
    #[tokio::test]
    async fn notification_rereads_projection_and_disconnect_preserves_last_known() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let host = Arc::new(Fake {
            endpoint: format!("ws://{}", listener.local_addr().unwrap()),
            value: Mutex::new(
                json!({"dbId":"db","epoch":"one","hudRevision":12,"hud":{"marker":"from-db"}}),
            ),
        });
        let stop = CancellationToken::new();
        let mut feed = Feed::spawn(host.clone(), stop.clone()).receiver;
        let (tcp, _) = tokio::time::timeout(Duration::from_secs(3), listener.accept())
            .await
            .unwrap()
            .unwrap();
        let mut socket = tokio_tungstenite::accept_hdr_async(
            tcp,
            |request: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
                assert_eq!(
                    request.headers().get("origin").unwrap(),
                    "tauri://localhost"
                );
                Ok(response)
            },
        )
        .await
        .unwrap();
        let hello = socket.next().await.unwrap().unwrap();
        let hello: Value = serde_json::from_str(hello.to_text().unwrap()).unwrap();
        socket.send(Message::Text(json!({"protocolVersion":"d4planner-notify/v1","type":"hello.accepted","correlationId":hello["messageId"]}).to_string().into())).await.unwrap();
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                feed.changed().await.unwrap();
                if feed.borrow_and_update()["connected"] == true {
                    break;
                }
            }
        })
        .await
        .unwrap();
        assert_eq!(feed.borrow()["snapshot"]["hud"]["marker"], "from-db");
        host.value.lock().unwrap()["hudRevision"] = json!(20);
        socket.send(Message::Text(json!({"protocolVersion":"d4planner-notify/v1","type":"hud.committed","hudRevision":9999}).to_string().into())).await.unwrap();
        tokio::time::timeout(Duration::from_secs(3), async {
            loop {
                feed.changed().await.unwrap();
                if feed.borrow_and_update()["snapshot"]["hudRevision"] == 20 {
                    break;
                }
            }
        })
        .await
        .unwrap();
        assert_eq!(feed.borrow()["snapshot"]["hudRevision"], 20);
        socket.close(None).await.unwrap();
        tokio::time::timeout(Duration::from_secs(4), async {
            loop {
                feed.changed().await.unwrap();
                if feed.borrow_and_update()["connected"] == false {
                    break;
                }
            }
        })
        .await
        .unwrap();
        assert_eq!(feed.borrow()["snapshot"]["hudRevision"], 20);
        stop.cancel();
    }
    #[tokio::test]
    async fn duplicate_revision_and_regression_do_not_replace_authoritative_value() {
        let host: Arc<dyn Host> = Arc::new(Fake {
            endpoint: String::new(),
            value: Mutex::new(json!({"dbId":"db","epoch":"one","hudRevision":10})),
        });
        let (sender, receiver) = watch::channel(Value::Null);
        let mut prior = json!({"schemaVersion":VERSION,"type":"state","connected":true,"snapshot":{"dbId":"db","epoch":"one","hudRevision":20},"runtime":null});
        let mut sequence = 1;
        publish(&host, &sender, true, &mut prior, &mut sequence).await;
        assert_eq!(receiver.borrow()["snapshot"]["hudRevision"], 20);
        assert_eq!(receiver.borrow()["connected"], false);
        let last = sequence;
        publish(&host, &sender, true, &mut prior, &mut sequence).await;
        assert_eq!(sequence, last);
    }
}

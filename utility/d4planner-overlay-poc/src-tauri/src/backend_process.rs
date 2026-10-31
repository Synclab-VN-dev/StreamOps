use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::Duration,
};
use wait_timeout::ChildExt;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ProcessState {
    Stopped,
    Starting,
    Ready,
    Stopping,
    Exited,
    Failed,
}

#[derive(Clone, Debug)]
pub struct LaunchSpecification {
    pub executable: PathBuf,
    pub args: Vec<String>,
    pub working_directory: PathBuf,
    pub environment: BTreeMap<String, String>,
    pub owner_instance_id: String,
    pub child_instance_id: String,
    pub generation: u64,
    pub readiness_timeout: Duration,
    pub graceful_stop_timeout: Duration,
    pub kill_timeout: Duration,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReadyInfo {
    pub pid: u32,
    pub child_instance_id: String,
    pub generation: u64,
    pub ws_endpoint: WsEndpoint,
    pub health: BackendHealth,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
pub struct WsEndpoint {
    pub host: String,
    pub port: u16,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendHealth {
    pub durable_state: String,
    pub target_repository: String,
    pub target_json_count: u64,
    pub ws_transport: String,
    pub rule_kit_worker: String,
}

pub trait ProcessDriver: Send + Sync + 'static {
    type Child: Clone + Send + Sync + 'static;
    fn spawn(&self, specification: &LaunchSpecification) -> Result<Self::Child, String>;
    fn await_ready(
        &self,
        child: &Self::Child,
        specification: &LaunchSpecification,
    ) -> Result<ReadyInfo, String>;
    fn request_graceful_stop(
        &self,
        child: &Self::Child,
        specification: &LaunchSpecification,
    ) -> Result<(), String>;
    fn wait_for_exit(&self, child: &Self::Child, timeout: Duration) -> Result<bool, String>;
    /// Wait for an exit notification without claiming or terminating the child.
    /// Implementations must return after `timeout` so lifecycle invalidation can
    /// notice an explicit stop/restart and retire the watcher.
    fn observe_exit(&self, child: &Self::Child, timeout: Duration) -> Result<bool, String>;
    fn terminate_owned_child(&self, child: &Self::Child) -> Result<(), String>;
}

type PendingCommands = Arc<Mutex<BTreeMap<String, (serde_json::Value, mpsc::Sender<Result<serde_json::Value, String>>)>>>;

fn bounded_line(reader: &mut impl BufRead) -> Result<Option<String>, String> {
    let mut bytes = Vec::new();
    reader.take(1_048_577).read_until(b'\n', &mut bytes).map_err(|_| "CONTROL_READ_FAILED")?;
    if bytes.is_empty() { return Ok(None); }
    if bytes.len() > 1_048_576 { return Err("CONTROL_FRAME_TOO_LARGE".into()); }
    String::from_utf8(bytes).map(Some).map_err(|_| "CONTROL_INVALID_UTF8".into())
}

#[derive(Clone)]
pub struct StdChild {
    pending: PendingCommands,
    process: Arc<Mutex<Child>>,
    stdin: Arc<Mutex<ChildStdin>>,
    ready: Arc<Mutex<mpsc::Receiver<Result<ReadyEnvelope, String>>>>,
}

#[derive(Clone, Default)]
pub struct StdProcessDriver;

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReadyEnvelope {
    event: String,
    protocol: String,
    contract_version: String,
    owner_instance_id: String,
    child_instance_id: String,
    generation: u64,
    pid: u32,
    ws_endpoint: WsEndpoint,
    health: BackendHealth,
}

impl ProcessDriver for StdProcessDriver {
    type Child = StdChild;

    fn spawn(&self, specification: &LaunchSpecification) -> Result<Self::Child, String> {
        let mut command = Command::new(&specification.executable);
        command
            .args(&specification.args)
            .current_dir(&specification.working_directory)
            .env_clear()
            .envs(&specification.environment)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());
        // A managed console child must not create a visible console beside HUD.
        // Pipes and owned process handle remain unchanged.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let mut process = command
            .spawn()
            .map_err(|error| format!("spawn failed: {error}"))?;
        let stdin = process
            .stdin
            .take()
            .ok_or("managed child stdin unavailable")?;
        let stdout = process
            .stdout
            .take()
            .ok_or("managed child stdout unavailable")?;
        let (tx, rx) = mpsc::channel();
        let pending: PendingCommands = Arc::new(Mutex::new(BTreeMap::new()));
        let dispatcher = pending.clone();
        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let result = bounded_line(&mut reader).and_then(|line| {
                let line = line.ok_or("child exited before READY")?;
                serde_json::from_str::<ReadyEnvelope>(&line).map_err(|_| "invalid READY handshake".into())
            });
            let _ = tx.send(result);
            while let Ok(Some(line)) = bounded_line(&mut reader) {
                let Ok(value) = serde_json::from_str::<serde_json::Value>(&line) else { continue; };
                if value["type"] != "response" || value["protocolVersion"] != "d4planner-control/v1" { continue; }
                let Some(id) = value["requestId"].as_str() else { continue; };
                if let Ok(mut pending) = dispatcher.lock() {
                    let matches = pending.get(id).map(|(request, _)| {
                        ["ownerInstanceId", "childInstanceId", "generation"].iter().all(|key| value[*key] == request[*key])
                    }).unwrap_or(false);
                    if matches {
                        if let Some((_, sender)) = pending.remove(id) { let _ = sender.send(Ok(value)); }
                    }
                }
            }
            if let Ok(mut pending) = dispatcher.lock() {
                for (_, (_, sender)) in std::mem::take(&mut *pending) { let _ = sender.send(Err("BACKEND_OFFLINE".into())); }
            }
        });
        Ok(StdChild {
            pending,
            process: Arc::new(Mutex::new(process)),
            stdin: Arc::new(Mutex::new(stdin)),
            ready: Arc::new(Mutex::new(rx)),
        })
    }

    fn await_ready(
        &self,
        child: &Self::Child,
        specification: &LaunchSpecification,
    ) -> Result<ReadyInfo, String> {
        let envelope = child
            .ready
            .lock()
            .map_err(|_| "READY receiver lock poisoned")?
            .recv_timeout(specification.readiness_timeout)
            .map_err(|error| format!("READY timeout/channel failure: {error}"))??;
        if envelope.event != "READY"
            || envelope.protocol != "d4planner-managed/v1"
            || envelope.contract_version != "d4planner-r1-contract/1.0.0-candidate.6"
            || envelope.owner_instance_id != specification.owner_instance_id
            || envelope.child_instance_id != specification.child_instance_id
            || envelope.generation != specification.generation
        {
            return Err("READY ownership/protocol/version mismatch".into());
        }
        let actual_pid = child
            .process
            .lock()
            .map_err(|_| "child lock poisoned")?
            .id();
        if envelope.pid != actual_pid {
            return Err("READY PID does not match owned child".into());
        }
        if !matches!(envelope.ws_endpoint.host.as_str(), "127.0.0.1" | "::1") {
            return Err("READY endpoint is not loopback".into());
        }
        Ok(ReadyInfo {
            pid: envelope.pid,
            child_instance_id: envelope.child_instance_id,
            generation: envelope.generation,
            ws_endpoint: envelope.ws_endpoint,
            health: envelope.health,
        })
    }

    fn request_graceful_stop(
        &self,
        child: &Self::Child,
        specification: &LaunchSpecification,
    ) -> Result<(), String> {
        let message = serde_json::json!({
            "type": "shutdown",
            "ownerInstanceId": specification.owner_instance_id,
            "childInstanceId": specification.child_instance_id,
            "generation": specification.generation,
        });
        let mut stdin = child
            .stdin
            .lock()
            .map_err(|_| "child stdin lock poisoned")?;
        writeln!(stdin, "{message}").map_err(|error| format!("shutdown write failed: {error}"))?;
        stdin
            .flush()
            .map_err(|error| format!("shutdown flush failed: {error}"))
    }

    fn wait_for_exit(&self, child: &Self::Child, timeout: Duration) -> Result<bool, String> {
        let mut process = child.process.lock().map_err(|_| "child lock poisoned")?;
        process
            .wait_timeout(timeout)
            .map(|status| status.is_some())
            .map_err(|error| format!("wait failed: {error}"))
    }

    fn observe_exit(&self, child: &Self::Child, timeout: Duration) -> Result<bool, String> {
        self.wait_for_exit(child, timeout)
    }

    fn terminate_owned_child(&self, child: &Self::Child) -> Result<(), String> {
        child
            .process
            .lock()
            .map_err(|_| "child lock poisoned")?
            .kill()
            .map_err(|error| format!("owned-child termination failed: {error}"))
    }
}

struct Inner<C> {
    // A spawned lifetime consumes its generation even if READY fails.
    last_spawned_generation: Option<u64>,
    state: ProcessState,
    child: Option<C>,
    ready: Option<ReadyInfo>,
}

pub struct BackendProcessWrapper<D: ProcessDriver> {
    driver: Arc<D>,
    operation: Mutex<()>,
    specification: Mutex<LaunchSpecification>,
    inner: Arc<Mutex<Inner<D::Child>>>,
}

impl BackendProcessWrapper<StdProcessDriver> {
    /// Same owned pipe as lifecycle. A deadline retires only this request.
    pub fn request(&self, method: &str, params: serde_json::Value, timeout: Duration) -> Result<serde_json::Value, String> {
        if !matches!(method, "target.list" | "target.select") || timeout.is_zero() || timeout > Duration::from_secs(60) {
            return Err("INVALID_CONTROL_REQUEST".into());
        }
        // Serialize admission with restart, but release before waiting for reply.
        let (child, id, rx) = {
            let _operation = self.operation.lock().map_err(|_| "operation lock poisoned")?;
            let spec = self.specification.lock().map_err(|_| "specification lock poisoned")?;
            let inner = self.inner.lock().map_err(|_| "state lock poisoned")?;
            if inner.state != ProcessState::Ready { return Err("BACKEND_OFFLINE".into()); }
            let child = inner.child.clone().ok_or("BACKEND_OFFLINE")?;
            static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
            let id = format!("{}-{}", spec.generation, NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed));
            let message = serde_json::json!({"protocolVersion":"d4planner-control/v1", "type":"request", "requestId":id,
                "ownerInstanceId":spec.owner_instance_id, "childInstanceId":spec.child_instance_id, "generation":spec.generation,
                "method":method, "params":params});
            let bytes = serde_json::to_vec(&message).map_err(|_| "CONTROL_ENCODE_FAILED")?;
            if bytes.len() >= 1_048_576 { return Err("CONTROL_FRAME_TOO_LARGE".into()); }
            let (tx, rx) = mpsc::channel();
            {
                let mut pending = child.pending.lock().map_err(|_| "pending lock poisoned")?;
                if pending.len() >= 32 { return Err("CONTROL_QUEUE_FULL".into()); }
                pending.insert(id.clone(), (message, tx));
            }
            let written = (|| -> Result<(), std::io::Error> {
                let mut stdin = child.stdin.lock().map_err(|_| std::io::Error::other("pipe lock poisoned"))?;
                stdin.write_all(&bytes)?; stdin.write_all(b"\n")?; stdin.flush()
            })();
            if written.is_err() {
                if let Ok(mut pending) = child.pending.lock() { pending.remove(&id); }
                return Err("BACKEND_OFFLINE".into());
            }
            (child, id, rx)
        };
        let result = rx.recv_timeout(timeout).map_err(|_| "CONTROL_TIMEOUT".to_owned());
        if let Ok(mut pending) = child.pending.lock() { pending.remove(&id); }
        let response = result??;
        if !response["error"].is_null() { return Err(response["error"]["code"].as_str().unwrap_or("CONTROL_FAILED").to_owned()); }
        Ok(response["result"].clone())
    }
}

impl<D: ProcessDriver> BackendProcessWrapper<D> {
    pub fn new(driver: Arc<D>, specification: LaunchSpecification) -> Self {
        Self {
            driver,
            operation: Mutex::new(()),
            specification: Mutex::new(specification),
            inner: Arc::new(Mutex::new(Inner {
                last_spawned_generation: None,
                state: ProcessState::Stopped,
                child: None,
                ready: None,
            })),
        }
    }

    pub fn state(&self) -> ProcessState {
        self.inner
            .lock()
            .map(|inner| inner.state)
            .unwrap_or(ProcessState::Failed)
    }

    pub fn ready_info(&self) -> Option<ReadyInfo> {
        self.inner.lock().ok().and_then(|inner| inner.ready.clone())
    }

    /// Serialized Template Method: preflight/specification is constructed by the
    /// composition root; this method owns spawn -> READY -> cleanup on failure.
    pub fn start(&self) -> Result<ReadyInfo, String> {
        let _operation = self
            .operation
            .lock()
            .map_err(|_| "operation lock poisoned")?;
        self.start_operation()
    }

    fn start_operation(&self) -> Result<ReadyInfo, String> {
        let specification = self
            .specification
            .lock()
            .map_err(|_| "specification lock poisoned")?
            .clone();
        let mut inner = self.inner.lock().map_err(|_| "lifecycle lock poisoned")?;
        if inner.state == ProcessState::Ready {
            return inner
                .ready
                .clone()
                .ok_or("READY state missing receipt".into());
        }
        if !matches!(
            inner.state,
            ProcessState::Stopped | ProcessState::Exited | ProcessState::Failed
        ) {
            return Err(format!("cannot start from {:?}", inner.state));
        }
        if inner.child.is_some() {
            return Err("owned child cleanup pending; stop must confirm exit before start".into());
        }
        if inner
            .last_spawned_generation
            .is_some_and(|used| specification.generation <= used)
        {
            return Err("backend generation already used; provision a fresh bootstrap and call restart_with".into());
        }
        inner.state = ProcessState::Starting;
        let child = match self.driver.spawn(&specification) {
            Ok(child) => child,
            Err(error) => {
                inner.state = ProcessState::Failed;
                return Err(error);
            }
        };
        inner.last_spawned_generation = Some(specification.generation);
        inner.child = Some(child.clone());
        match self.driver.await_ready(&child, &specification) {
            Ok(ready) => {
                inner.ready = Some(ready.clone());
                inner.state = ProcessState::Ready;
                drop(inner);
                self.spawn_exit_watcher(child, ready.generation);
                Ok(ready)
            }
            Err(error) => {
                inner.ready = None;
                inner.state = ProcessState::Failed;
                match self.cleanup_owned_child(&child, &specification) {
                    Ok(()) => {
                        inner.child = None;
                        Err(error)
                    }
                    Err(cleanup) => Err(format!("{error}; cleanup pending: {cleanup}")),
                }
            }
        }
    }

    fn spawn_exit_watcher(&self, child: D::Child, generation: u64) {
        let driver = self.driver.clone();
        let inner = self.inner.clone();
        thread::spawn(move || loop {
            let observed = driver.observe_exit(&child, Duration::from_millis(50));
            let mut lifecycle = match inner.lock() {
                Ok(lifecycle) => lifecycle,
                Err(_) => return,
            };
            let still_owned_ready = lifecycle.state == ProcessState::Ready
                && lifecycle
                    .ready
                    .as_ref()
                    .map(|ready| ready.generation == generation)
                    .unwrap_or(false);
            if !still_owned_ready {
                return;
            }
            match observed {
                Ok(false) => continue,
                Ok(true) => {
                    lifecycle.child = None;
                    lifecycle.ready = None;
                    lifecycle.state = ProcessState::Failed;
                    return;
                }
                Err(_) => {
                    // Observation failure is not evidence of process exit.
                    lifecycle.ready = None;
                    lifecycle.state = ProcessState::Failed;
                    return;
                }
            }
        });
    }

    pub fn stop(&self) -> Result<(), String> {
        let _operation = self
            .operation
            .lock()
            .map_err(|_| "operation lock poisoned")?;
        self.stop_operation()
    }

    fn stop_operation(&self) -> Result<(), String> {
        let specification = self
            .specification
            .lock()
            .map_err(|_| "specification lock poisoned")?
            .clone();
        let mut inner = self.inner.lock().map_err(|_| "lifecycle lock poisoned")?;
        if matches!(inner.state, ProcessState::Stopped | ProcessState::Exited) {
            return Ok(());
        }
        let child = match inner.child.clone() {
            Some(child) => child,
            None => {
                inner.state = ProcessState::Stopped;
                return Ok(());
            }
        };
        inner.state = ProcessState::Stopping;
        inner.ready = None;
        match self.cleanup_owned_child(&child, &specification) {
            Ok(()) => {
                inner.child = None;
                inner.state = ProcessState::Exited;
                Ok(())
            }
            Err(error) => {
                inner.state = ProcessState::Failed;
                Err(error)
            }
        }
    }

    /// Only a confirmed exit releases ownership, even if shutdown/kill fails.
    /// Both waits are bounded by the driver contract. Retrying stop is safe.
    fn cleanup_owned_child(
        &self,
        child: &D::Child,
        spec: &LaunchSpecification,
    ) -> Result<(), String> {
        let mut errors = Vec::new();
        if let Err(error) = self.driver.request_graceful_stop(child, spec) {
            errors.push(error);
        }
        match self.driver.wait_for_exit(child, spec.graceful_stop_timeout) {
            Ok(true) => return Ok(()),
            Err(error) => errors.push(error),
            Ok(false) => {}
        }
        if let Err(error) = self.driver.terminate_owned_child(child) {
            errors.push(error);
        }
        match self.driver.wait_for_exit(child, spec.kill_timeout) {
            Ok(true) => Ok(()),
            result => {
                if let Err(error) = result {
                    errors.push(error);
                }
                Err(format!(
                    "owned child exit unconfirmed; {}",
                    errors.join("; ")
                ))
            }
        }
    }

    pub fn restart_with(&self, next: LaunchSpecification) -> Result<ReadyInfo, String> {
        let _operation = self
            .operation
            .lock()
            .map_err(|_| "operation lock poisoned")?;
        {
            let current = self
                .specification
                .lock()
                .map_err(|_| "specification lock poisoned")?;
            if next.owner_instance_id != current.owner_instance_id
                || next.child_instance_id == current.child_instance_id
                || next.generation <= current.generation
            {
                return Err("restart requires same owner, new child and higher generation".into());
            }
        }
        self.stop_operation()?;
        {
            let mut current = self
                .specification
                .lock()
                .map_err(|_| "specification lock poisoned")?;
            *current = next;
        }
        self.start_operation()
    }

    /// Presentation state is deliberately outside process lifecycle.
    pub fn presentation_hidden(&self) -> ProcessState {
        self.state()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    #[derive(Clone)]
    struct FakeChild;

    struct FakeDriver {
        spawns: AtomicUsize,
        stops: AtomicUsize,
        terminates: AtomicUsize,
        terminated: AtomicBool,
        unexpected_exit: AtomicBool,
        ready: Mutex<Result<ReadyInfo, String>>,
        spawn_error: Mutex<Option<String>>,
        graceful_exit: bool,
    }

    impl FakeDriver {
        fn healthy() -> Self {
            Self {
                spawns: AtomicUsize::new(0),
                stops: AtomicUsize::new(0),
                terminates: AtomicUsize::new(0),
                terminated: AtomicBool::new(false),
                unexpected_exit: AtomicBool::new(false),
                ready: Mutex::new(Ok(ReadyInfo {
                    pid: 42,
                    child_instance_id: "child".into(),
                    generation: 1,
                    ws_endpoint: WsEndpoint {
                        host: "127.0.0.1".into(),
                        port: 0,
                    },
                    health: BackendHealth {
                        durable_state: "READY".into(),
                        target_repository: "READY".into(),
                        target_json_count: 0,
                        ws_transport: "PENDING_S5".into(),
                        rule_kit_worker: "PENDING_S3".into(),
                    },
                })),
                spawn_error: Mutex::new(None),
                graceful_exit: true,
            }
        }
    }

    impl ProcessDriver for FakeDriver {
        type Child = FakeChild;
        fn spawn(&self, _: &LaunchSpecification) -> Result<Self::Child, String> {
            self.spawns.fetch_add(1, Ordering::SeqCst);
            if let Some(error) = self.spawn_error.lock().unwrap().clone() {
                return Err(error);
            }
            Ok(FakeChild)
        }
        fn await_ready(
            &self,
            _: &Self::Child,
            _: &LaunchSpecification,
        ) -> Result<ReadyInfo, String> {
            self.ready.lock().unwrap().clone()
        }
        fn request_graceful_stop(
            &self,
            _: &Self::Child,
            _: &LaunchSpecification,
        ) -> Result<(), String> {
            self.stops.fetch_add(1, Ordering::SeqCst);
            Ok(())
        }
        fn wait_for_exit(&self, _: &Self::Child, _: Duration) -> Result<bool, String> {
            Ok(self.graceful_exit || self.terminated.load(Ordering::SeqCst))
        }
        fn observe_exit(&self, _: &Self::Child, _: Duration) -> Result<bool, String> {
            if self.unexpected_exit.load(Ordering::SeqCst) {
                Ok(true)
            } else {
                std::thread::sleep(Duration::from_millis(1));
                Ok(false)
            }
        }
        fn terminate_owned_child(&self, _: &Self::Child) -> Result<(), String> {
            self.terminates.fetch_add(1, Ordering::SeqCst);
            self.terminated.store(true, Ordering::SeqCst);
            Ok(())
        }
    }

    fn specification() -> LaunchSpecification {
        LaunchSpecification {
            executable: "python".into(),
            args: vec![],
            working_directory: ".".into(),
            environment: BTreeMap::new(),
            owner_instance_id: "owner".into(),
            child_instance_id: "child".into(),
            generation: 1,
            readiness_timeout: Duration::from_millis(10),
            graceful_stop_timeout: Duration::from_millis(10),
            kill_timeout: Duration::from_millis(10),
        }
    }

    #[test]
    fn double_start_and_hide_keep_one_owned_child() {
        let driver = Arc::new(FakeDriver::healthy());
        let wrapper = BackendProcessWrapper::new(driver.clone(), specification());
        assert_eq!(wrapper.start().unwrap(), wrapper.start().unwrap());
        assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);
        assert_eq!(wrapper.presentation_hidden(), ProcessState::Ready);
        wrapper.stop().unwrap();
        wrapper.stop().unwrap();
        assert_eq!(driver.stops.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn concurrent_start_calls_spawn_exactly_one_child() {
        let driver = Arc::new(FakeDriver::healthy());
        let wrapper = Arc::new(BackendProcessWrapper::new(driver.clone(), specification()));
        let gate = Arc::new(std::sync::Barrier::new(9));
        let callers: Vec<_> = (0..8)
            .map(|_| {
                let wrapper = wrapper.clone();
                let gate = gate.clone();
                std::thread::spawn(move || {
                    gate.wait();
                    wrapper.start()
                })
            })
            .collect();
        gate.wait();
        for caller in callers {
            assert_eq!(caller.join().unwrap().unwrap().pid, 42);
        }
        assert_eq!(driver.spawns.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn spawn_failure_is_fail_closed_and_does_not_claim_ready() {
        let driver = Arc::new(FakeDriver::healthy());
        *driver.spawn_error.lock().unwrap() = Some("missing executable".into());
        let wrapper = BackendProcessWrapper::new(driver.clone(), specification());
        assert_eq!(wrapper.start().unwrap_err(), "missing executable");
        assert_eq!(wrapper.state(), ProcessState::Failed);
        assert_eq!(driver.stops.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn readiness_failure_cleans_up_child() {
        let driver = Arc::new(FakeDriver::healthy());
        *driver.ready.lock().unwrap() = Err("version mismatch".into());
        let wrapper = BackendProcessWrapper::new(driver.clone(), specification());
        assert_eq!(wrapper.start().unwrap_err(), "version mismatch");
        assert_eq!(wrapper.state(), ProcessState::Failed);
        assert_eq!(driver.stops.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn bounded_stop_terminates_only_owned_handle_after_timeout() {
        let driver = Arc::new(FakeDriver {
            graceful_exit: false,
            ..FakeDriver::healthy()
        });
        let wrapper = BackendProcessWrapper::new(driver.clone(), specification());
        wrapper.start().unwrap();
        wrapper.stop().unwrap();
        assert_eq!(driver.terminates.load(Ordering::SeqCst), 1);
        assert_eq!(wrapper.state(), ProcessState::Exited);
    }

    #[test]
    fn restart_requires_new_child_and_monotonic_generation() {
        let driver = Arc::new(FakeDriver::healthy());
        let wrapper = BackendProcessWrapper::new(driver.clone(), specification());
        wrapper.start().unwrap();
        assert!(wrapper.restart_with(specification()).is_err());

        let mut next = specification();
        next.child_instance_id = "child-2".into();
        next.generation = 2;
        *driver.ready.lock().unwrap() = Ok(ReadyInfo {
            pid: 43,
            child_instance_id: "child-2".into(),
            generation: 2,
            ws_endpoint: WsEndpoint {
                host: "127.0.0.1".into(),
                port: 0,
            },
            health: BackendHealth {
                durable_state: "READY".into(),
                target_repository: "READY".into(),
                target_json_count: 0,
                ws_transport: "PENDING_S5".into(),
                rule_kit_worker: "PENDING_S3".into(),
            },
        });
        assert_eq!(wrapper.restart_with(next).unwrap().generation, 2);
        assert_eq!(driver.spawns.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn unexpected_exit_invalidates_ready_and_restart_recovers_new_generation() {
        let driver = Arc::new(FakeDriver::healthy());
        let wrapper = BackendProcessWrapper::new(driver.clone(), specification());
        wrapper.start().unwrap();
        assert_eq!(wrapper.state(), ProcessState::Ready);

        driver.unexpected_exit.store(true, Ordering::SeqCst);
        for _ in 0..100 {
            if wrapper.state() == ProcessState::Failed {
                break;
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        assert_eq!(wrapper.state(), ProcessState::Failed);
        assert!(wrapper.ready_info().is_none());

        driver.unexpected_exit.store(false, Ordering::SeqCst);
        let mut next = specification();
        next.child_instance_id = "child-2".into();
        next.generation = 2;
        *driver.ready.lock().unwrap() = Ok(ReadyInfo {
            pid: 43,
            child_instance_id: "child-2".into(),
            generation: 2,
            ws_endpoint: WsEndpoint {
                host: "127.0.0.1".into(),
                port: 0,
            },
            health: BackendHealth {
                durable_state: "READY".into(),
                target_repository: "READY".into(),
                target_json_count: 0,
                ws_transport: "PENDING_S5".into(),
                rule_kit_worker: "PENDING_S3".into(),
            },
        });
        assert_eq!(wrapper.restart_with(next).unwrap().generation, 2);
        assert_eq!(wrapper.state(), ProcessState::Ready);
    }
}

#[cfg(test)]
#[path = "backend_process_review_tests.rs"]
mod review_tests;

use super::*;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

struct FaultDriver {
    spawns: AtomicUsize,
    ready_fails: AtomicBool,
    exited: AtomicBool,
    terminate_fails: AtomicBool,
    wait_fails: AtomicBool,
    observe_fails: AtomicBool,
    touched: Mutex<Vec<usize>>,
}
impl FaultDriver {
    fn new() -> Self {
        Self {
            spawns: AtomicUsize::new(0),
            ready_fails: AtomicBool::new(false),
            exited: AtomicBool::new(false),
            terminate_fails: AtomicBool::new(false),
            wait_fails: AtomicBool::new(false),
            observe_fails: AtomicBool::new(false),
            touched: Mutex::new(vec![]),
        }
    }
}
impl ProcessDriver for FaultDriver {
    type Child = usize;
    fn spawn(&self, _: &LaunchSpecification) -> Result<usize, String> {
        Ok(self.spawns.fetch_add(1, Ordering::SeqCst) + 1)
    }
    fn await_ready(&self, child: &usize, s: &LaunchSpecification) -> Result<ReadyInfo, String> {
        if self.ready_fails.load(Ordering::SeqCst) {
            return Err("READY timeout".into());
        }
        Ok(ReadyInfo {
            pid: *child as u32,
            child_instance_id: s.child_instance_id.clone(),
            generation: s.generation,
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
        })
    }
    fn request_graceful_stop(&self, c: &usize, _: &LaunchSpecification) -> Result<(), String> {
        self.touched.lock().unwrap().push(*c);
        Ok(())
    }
    fn wait_for_exit(&self, _: &usize, _: Duration) -> Result<bool, String> {
        if self.wait_fails.load(Ordering::SeqCst) {
            Err("injected wait failure".into())
        } else {
            Ok(self.exited.load(Ordering::SeqCst))
        }
    }
    fn observe_exit(&self, _: &usize, _: Duration) -> Result<bool, String> {
        thread::sleep(Duration::from_millis(2));
        if self.observe_fails.load(Ordering::SeqCst) {
            Err("injected observation failure".into())
        } else {
            Ok(false)
        }
    }
    fn terminate_owned_child(&self, c: &usize) -> Result<(), String> {
        self.touched.lock().unwrap().push(*c);
        if self.terminate_fails.load(Ordering::SeqCst) {
            Err("injected terminate failure".into())
        } else {
            Ok(())
        }
    }
}
fn spec() -> LaunchSpecification {
    LaunchSpecification {
        executable: "python3".into(),
        args: vec![],
        working_directory: ".".into(),
        environment: BTreeMap::new(),
        owner_instance_id: "owner".into(),
        child_instance_id: "child".into(),
        generation: 1,
        readiness_timeout: Duration::from_secs(5),
        graceful_stop_timeout: Duration::from_millis(100),
        kill_timeout: Duration::from_secs(2),
    }
}
#[test]
fn failed_cleanup_retains_ownership_and_blocks_spawn_until_confirmed_exit() {
    // Cover READY failure and running-child stop, termination failure, false wait,
    // and wait errors. Each independent scenario must target only child handle1.
    for startup_failure in [false, true] {
        for failure in ["terminate", "unconfirmed", "wait"] {
            let d = Arc::new(FaultDriver::new());
            d.ready_fails.store(startup_failure, Ordering::SeqCst);
            d.terminate_fails
                .store(failure == "terminate", Ordering::SeqCst);
            d.wait_fails.store(failure == "wait", Ordering::SeqCst);
            let w = BackendProcessWrapper::new(d.clone(), spec());
            if startup_failure {
                assert!(w.start().is_err());
            } else {
                w.start().unwrap();
                assert!(w.stop().is_err());
            }
            assert_eq!(w.state(), ProcessState::Failed);
            assert!(w.ready_info().is_none());
            assert_eq!(w.inner.lock().unwrap().child, Some(1));
            assert!(w.start().is_err());
            let mut next = spec();
            next.generation = 2;
            next.child_instance_id = "child-2".into();
            assert!(w.restart_with(next.clone()).is_err());
            assert_eq!(d.spawns.load(Ordering::SeqCst), 1);
            assert_eq!(w.specification.lock().unwrap().generation, 1);
            assert!(d.touched.lock().unwrap().iter().all(|c| *c == 1));
            d.wait_fails.store(false, Ordering::SeqCst);
            d.exited.store(true, Ordering::SeqCst);
            d.ready_fails.store(false, Ordering::SeqCst);
            // Exit confirmation wins over a terminate error/process-exit race.
            w.stop().unwrap();
            assert!(w.inner.lock().unwrap().child.is_none());
            assert_eq!(w.restart_with(next).unwrap().generation, 2);
            assert_eq!(d.spawns.load(Ordering::SeqCst), 2);
            w.stop().unwrap();
        }
    }
}
#[test]
fn watcher_error_invalidates_ready_but_does_not_prove_exit() {
    let d = Arc::new(FaultDriver::new());
    let w = BackendProcessWrapper::new(d.clone(), spec());
    w.start().unwrap();
    d.observe_fails.store(true, Ordering::SeqCst);
    for _ in 0..100 {
        if w.state() == ProcessState::Failed {
            break;
        }
        thread::sleep(Duration::from_millis(2));
    }
    assert_eq!(w.state(), ProcessState::Failed);
    assert!(w.ready_info().is_none());
    assert_eq!(w.inner.lock().unwrap().child, Some(1));
    assert!(w.start().is_err());
    assert_eq!(d.spawns.load(Ordering::SeqCst), 1);
    d.exited.store(true, Ordering::SeqCst);
    w.stop().unwrap();
}

struct Sandbox(PathBuf);
impl Sandbox {
    fn new() -> Self {
        static ID: AtomicUsize = AtomicUsize::new(0);
        let p = std::env::temp_dir().join(format!(
            "s2-ready-{}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            ID.fetch_add(1, Ordering::SeqCst)
        ));
        std::fs::create_dir(&p).unwrap();
        Self(p)
    }
    fn launch(&self, mutation: &str) -> LaunchSpecification {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .canonicalize()
            .unwrap();
        let descriptor = self.0.join("bootstrap.json");
        let payload = serde_json::json!({"protocol":"d4planner-managed/v1","contractVersion":"d4planner-r1-contract/1.0.0-candidate.6","ownerInstanceId":"owner","childInstanceId":"child","generation":1,"dataDir":self.0.join("data"),"targetFolder":self.0.join("targets"),"wsEndpoint":{"host":"127.0.0.1","port":0},"credential":"SYNTHETIC_TEST_CREDENTIAL_0000000000000000"});
        std::fs::write(&descriptor, payload.to_string()).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&descriptor, std::fs::Permissions::from_mode(0o600)).unwrap();
        }
        let mut s = spec();
        s.executable = std::env::var_os("S2_TEST_PYTHON")
            .unwrap_or_else(|| "python3".into())
            .into();
        s.working_directory = root.clone();
        s.environment.insert(
            "PYTHONPATH".into(),
            root.join("utility/d4planner/src").display().to_string(),
        );
        s.environment.insert(
            "D4PLANNER_BOOTSTRAP_FILE".into(),
            descriptor.display().to_string(),
        );
        // S2 tests exercise the real managed entrypoint with BaseRuntime only.
        // Production composition is the S5 default and has separate integration
        // tests; do not let that default change this stdlib-only handshake scope.
        s.environment
            .insert("D4PLANNER_RUNTIME_FACTORY".into(), String::new());
        for key in ["PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"] {
            if let Ok(v) = std::env::var(key) {
                s.environment.insert(key.into(), v);
            }
        }
        if mutation.is_empty() {
            s.args = vec!["-m".into(), "d4planner.managed_backend".into()];
        } else {
            // Alter actual Python-produced READY for negative wire/ownership tests.
            s.args=vec!["-c".into(),format!("import d4planner.managed_backend as m\noriginal=m._emit\ndef emit(row):\n if row.get('event')=='READY':\n  {mutation}\n original(row)\nm._emit=emit\nraise SystemExit(m.main())")];
        }
        s
    }
}
impl Drop for Sandbox {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
struct Reap(StdChild);
impl Drop for Reap {
    fn drop(&mut self) {
        if let Ok(mut c) = self.0.process.lock() {
            if c.try_wait().ok().flatten().is_none() {
                let _ = c.kill();
                let _ = c.wait_timeout(Duration::from_secs(2));
            }
        }
    }
}
#[test]
fn real_rust_driver_accepts_python_ready_and_stops_owned_child() {
    let sandbox = Sandbox::new();
    let s = sandbox.launch("");
    let driver = Arc::new(StdProcessDriver);
    let w = BackendProcessWrapper::new(driver, s);
    let started = std::time::Instant::now();
    let result = w.start();
    let child = w.inner.lock().unwrap().child.clone();
    let _reap = child.clone().map(Reap);
    let r = result.unwrap();
    assert_eq!(r.health.ws_transport, "PENDING_S5");
    assert_eq!(r.health.rule_kit_worker, "PENDING_S3");
    assert_eq!(r.health.target_json_count, 0);
    assert_eq!(r.pid, child.as_ref().unwrap().process.lock().unwrap().id());
    w.stop().unwrap();
    assert!(child
        .unwrap()
        .process
        .lock()
        .unwrap()
        .try_wait()
        .unwrap()
        .unwrap()
        .success());
    assert!(w.ready_info().is_none());
    println!(
        "REAL_PYTHON_READY pid={} generation={} cleanup=EXITED elapsed_ms={}",
        r.pid,
        r.generation,
        started.elapsed().as_millis()
    );
}
#[test]
fn actual_python_ready_rejects_missing_malformed_and_foreign_identity() {
    for (mutation, expected) in [
        (
            "row['health'].pop('wsTransport',None)",
            "invalid READY handshake",
        ),
        (
            "row['health']['targetJsonCount']='not-a-count'",
            "invalid READY handshake",
        ),
        ("row['event']='EXIT'", "ownership/protocol/version"),
        ("row['protocol']='unknown'", "ownership/protocol/version"),
        (
            "row['contractVersion']='unknown'",
            "ownership/protocol/version",
        ),
        (
            "row['ownerInstanceId']='foreign'",
            "ownership/protocol/version",
        ),
        (
            "row['childInstanceId']='foreign'",
            "ownership/protocol/version",
        ),
        ("row['generation']=2", "ownership/protocol/version"),
        ("row['pid']+=1", "PID does not match"),
    ] {
        let sandbox = Sandbox::new();
        let s = sandbox.launch(mutation);
        let d = StdProcessDriver;
        let c = d.spawn(&s).unwrap();
        let _reap = Reap(c.clone());
        let error = d.await_ready(&c, &s).unwrap_err();
        assert!(error.contains(expected), "{mutation}: {error}");
        d.request_graceful_stop(&c, &s).unwrap();
        assert!(d.wait_for_exit(&c, Duration::from_secs(2)).unwrap());
    }
}

#[test]
fn real_stop_start_rejects_used_generation() {
    assert_new_lifetime(false);
}

#[test]
fn real_crash_start_rejects_used_generation() {
    assert_new_lifetime(true);
}

fn assert_new_lifetime(crash: bool) {
    {
        let sandbox = Sandbox::new();
        let spec = sandbox.launch("");
        let wrapper = BackendProcessWrapper::new(Arc::new(StdProcessDriver), spec.clone());
        let first = wrapper.start().unwrap();
        let child = wrapper.inner.lock().unwrap().child.clone().unwrap();
        let _reap = Reap(child.clone());
        if crash {
            StdProcessDriver.terminate_owned_child(&child).unwrap();
            let deadline = std::time::Instant::now() + Duration::from_secs(3);
            while wrapper.state() == ProcessState::Ready && std::time::Instant::now() < deadline {
                thread::sleep(Duration::from_millis(10));
            }
            assert_eq!(wrapper.state(), ProcessState::Failed);
        } else {
            wrapper.stop().unwrap();
            assert_eq!(wrapper.state(), ProcessState::Exited);
        }
        assert!(child.process.lock().unwrap().try_wait().unwrap().is_some());
        assert!(wrapper.inner.lock().unwrap().child.is_none());
        let repeated = wrapper.start();
        // Reap a wrongly spawned child even when this fail-first assertion fails.
        let _unexpected = wrapper.inner.lock().unwrap().child.clone().map(Reap);
        assert!(
            repeated.is_err(),
            "reused lifetime after crash={crash}: {repeated:?}"
        );
        assert!(repeated.unwrap_err().contains("generation already used"));
        assert!(wrapper.ready_info().is_none());

        // Native composition must provision a matching new descriptor/spec.
        let descriptor = sandbox.0.join("bootstrap.json");
        let mut json: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&descriptor).unwrap()).unwrap();
        json["generation"] = 2.into();
        json["childInstanceId"] = "child-2".into();
        std::fs::write(&descriptor, serde_json::to_vec(&json).unwrap()).unwrap();
        let mut next = spec;
        next.generation = 2;
        next.child_instance_id = "child-2".into();
        let second = wrapper.restart_with(next).unwrap();
        let _second_reap = Reap(wrapper.inner.lock().unwrap().child.clone().unwrap());
        assert_eq!(second.generation, first.generation + 1);
        assert_ne!(second.child_instance_id, first.child_instance_id);
        assert_eq!(wrapper.start().unwrap(), second);
        wrapper.stop().unwrap();
        assert!(wrapper.inner.lock().unwrap().child.is_none());
        println!(
            "F03 real crash={crash}: old_pid={} new_pid={} generations=1->2 cleanup=EXITED",
            first.pid, second.pid
        );
    }
}

#[test]
fn failed_ready_consumes_generation_even_after_successful_cleanup() {
    let d = Arc::new(FaultDriver::new());
    d.ready_fails.store(true, Ordering::SeqCst);
    d.exited.store(true, Ordering::SeqCst);
    let w = BackendProcessWrapper::new(d.clone(), spec());
    assert!(w.start().is_err());
    assert!(w.inner.lock().unwrap().child.is_none());
    w.stop().unwrap(); // FAILED -> STOPPED must not erase lifetime history.
    d.ready_fails.store(false, Ordering::SeqCst);
    assert!(w.start().is_err());
    assert_eq!(d.spawns.load(Ordering::SeqCst), 1);
}

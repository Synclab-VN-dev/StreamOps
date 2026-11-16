use crate::model::{Actor, Error, Host, Operation};
use serde_json::Value;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tokio::sync::Semaphore;

/// Holds permits in the blocking task even after its caller times out. A disconnected
/// browser must not allow another mutation to race a still-running native operation.
#[derive(Clone)]
pub struct Dispatcher {
    host: Arc<dyn Host>,
    reads: Arc<Semaphore>,
    mutations: Arc<Semaphore>,
    timeout: Duration,
    closing: Arc<AtomicBool>,
}
impl Dispatcher {
    pub fn new(host: Arc<dyn Host>, timeout: Duration) -> Self {
        Self {
            host,
            reads: Arc::new(Semaphore::new(8)),
            mutations: Arc::new(Semaphore::new(1)),
            timeout,
            closing: Arc::new(AtomicBool::new(false)),
        }
    }
    pub fn close(&self) {
        self.closing.store(true, Ordering::SeqCst);
    }
    pub async fn drain(&self) -> Result<(), Error> {
        self.close();
        tokio::time::timeout(Duration::from_secs(70), async {
            let _reads = self.reads.acquire_many(8).await;
            let _mutation = self.mutations.acquire().await;
        })
        .await
        .map_err(|_| Error::new(503, "WEB_DRAIN_TIMEOUT"))
    }
    pub async fn call(
        &self,
        operation: Operation,
        params: Value,
        actor: Actor,
    ) -> Result<Value, Error> {
        if self.closing.load(Ordering::SeqCst) {
            return Err(Error::new(503, "WEB_STOPPING"));
        }
        let (scope, mutation) = policy(operation);
        if !actor.permissions.contains(scope) {
            return Err(Error::new(403, "PERMISSION_DENIED"));
        }
        let pool = if mutation {
            &self.mutations
        } else {
            &self.reads
        };
        let permit = pool
            .clone()
            .try_acquire_owned()
            .map_err(|_| Error::new(409, "OPERATION_BUSY"))?;
        let host = self.host.clone();
        let closing = self.closing.clone();
        let task = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            if closing.load(Ordering::SeqCst) {
                return Err(Error::new(503, "WEB_STOPPING"));
            }
            host.operation(operation, params, actor)
        });
        tokio::time::timeout(self.timeout, task)
            .await
            .map_err(|_| Error::new(504, "OPERATION_TIMEOUT"))?
            .map_err(|_| Error::new(500, "OPERATION_FAILED"))?
    }
}
pub(crate) fn policy(operation: Operation) -> (&'static str, bool) {
    match operation {
        Operation::Targets => ("hud.read", false),
        Operation::SelectTarget => ("target.select", true),
        Operation::RuntimeStart
        | Operation::RuntimeStop
        | Operation::RuntimeRestart
        | Operation::CaptureStart
        | Operation::CaptureStop
        | Operation::CaptureRestart => ("runtime.control", true),
        Operation::PlannerReady => ("planner.open", true),
        Operation::ReportPreview => ("report.preview", true),
        Operation::ReportSubmit => ("report.submit", true),
        Operation::ReportStatus => ("report.read", false),
        Operation::ReportCancel => ("report.preview", true),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Asset, Bootstrap};
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Condvar, Mutex,
    };
    struct Fake {
        calls: AtomicUsize,
        released: (Mutex<bool>, Condvar),
    }
    impl Host for Fake {
        fn read_hud(&self) -> Result<Option<Value>, Error> {
            Ok(None)
        }
        fn bootstrap(&self) -> Result<Bootstrap, Error> {
            Err(Error::unavailable())
        }
        fn runtime(&self) -> Result<Value, Error> {
            Ok(Value::Null)
        }
        fn asset(&self, _: &str) -> Option<Asset> {
            None
        }
        fn operation(&self, _: Operation, _: Value, _: Actor) -> Result<Value, Error> {
            self.calls.fetch_add(1, Ordering::SeqCst);
            let (lock, cv) = &self.released;
            let mut released = lock.lock().unwrap();
            while !*released {
                released = cv.wait(released).unwrap();
            }
            Ok(Value::Null)
        }
    }
    fn actor(scope: &str) -> Actor {
        Actor {
            subject: "test".into(),
            permissions: [scope.to_owned()].into(),
        }
    }
    #[tokio::test]
    async fn timeout_does_not_release_mutation_ownership() {
        let host = Arc::new(Fake {
            calls: AtomicUsize::new(0),
            released: (Mutex::new(false), Condvar::new()),
        });
        let dispatcher = Dispatcher::new(host.clone(), Duration::from_millis(30));
        let first = dispatcher
            .call(
                Operation::RuntimeStart,
                Value::Null,
                actor("runtime.control"),
            )
            .await;
        let second = dispatcher
            .call(
                Operation::RuntimeStop,
                Value::Null,
                actor("runtime.control"),
            )
            .await;
        // Always release before assertions so a failure cannot strand the test runtime.
        *host.released.0.lock().unwrap() = true;
        host.released.1.notify_all();
        assert_eq!(first.unwrap_err().code, "OPERATION_TIMEOUT");
        assert_eq!(second.unwrap_err().code, "OPERATION_BUSY");
        assert_eq!(host.calls.load(Ordering::SeqCst), 1);
    }
    #[tokio::test]
    async fn denied_control_never_reaches_native_callback() {
        let host = Arc::new(Fake {
            calls: AtomicUsize::new(0),
            released: (Mutex::new(true), Condvar::new()),
        });
        let dispatcher = Dispatcher::new(host.clone(), Duration::from_secs(1));
        assert_eq!(
            dispatcher
                .call(Operation::RuntimeStart, Value::Null, actor("hud.read"))
                .await
                .unwrap_err()
                .code,
            "PERMISSION_DENIED"
        );
        assert_eq!(host.calls.load(Ordering::SeqCst), 0);
    }
}

use crate::model::*;
use axum::http::HeaderMap;
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq;

struct Session {
    actor: Actor,
    expires: Instant,
    csrf: String,
}
pub struct Auth {
    sessions: HashMap<String, Session>,
    rates: HashMap<String, (Instant, u32)>,
    credentials: Vec<Credential>,
}
impl Auth {
    pub fn new(credentials: Vec<Credential>) -> Self {
        Self {
            sessions: HashMap::new(),
            rates: HashMap::new(),
            credentials,
        }
    }
    pub fn rate(&mut self, key: &str, limit: u32) -> Result<(), Error> {
        self.rates
            .retain(|_, (t, _)| t.elapsed() < Duration::from_secs(60));
        if self.rates.len() > 256 && !self.rates.contains_key(key) {
            return Err(Error::new(429, "RATE_LIMIT"));
        }
        let (_, n) = self.rates.entry(key.into()).or_insert((Instant::now(), 0));
        *n += 1;
        if *n > limit {
            Err(Error::new(429, "RATE_LIMIT"))
        } else {
            Ok(())
        }
    }
    fn bearer(&self, token: &str) -> Result<Actor, Error> {
        if token.len() < 32 || token.len() > 256 {
            return Err(Error::new(401, "AUTH_REQUIRED"));
        }
        let hash = format!("{:x}", Sha256::digest(token.as_bytes()));
        self.credentials
            .iter()
            .find(|c| bool::from(c.sha256.as_bytes().ct_eq(hash.as_bytes())))
            .map(|c| Actor {
                subject: c.subject.clone(),
                permissions: c.permissions.clone(),
            })
            .ok_or(Error::new(401, "AUTH_REQUIRED"))
    }
    pub fn login(&mut self, token: &str) -> Result<(String, String), Error> {
        self.rate("login", 20)?;
        let actor = self.bearer(token)?;
        self.sessions.retain(|_, s| s.expires > Instant::now());
        if self.sessions.len() >= 32 {
            return Err(Error::new(429, "SESSION_LIMIT"));
        }
        let id = format!(
            "{}{}",
            uuid::Uuid::new_v4().simple(),
            uuid::Uuid::new_v4().simple()
        );
        let csrf = uuid::Uuid::new_v4().simple().to_string();
        self.sessions.insert(
            id.clone(),
            Session {
                actor,
                expires: Instant::now() + Duration::from_secs(3600),
                csrf: csrf.clone(),
            },
        );
        Ok((id, csrf))
    }
    pub fn actor(
        &mut self,
        headers: &HeaderMap,
        permission: &str,
        mutation: bool,
    ) -> Result<Actor, Error> {
        let a = if let Some(header) = headers.get("authorization") {
            self.bearer(
                header
                    .to_str()
                    .ok()
                    .and_then(|s| s.strip_prefix("Bearer "))
                    .ok_or(Error::new(401, "AUTH_REQUIRED"))?,
            )?
        } else {
            let id = cookie(headers).ok_or(Error::new(401, "AUTH_REQUIRED"))?;
            let s = self
                .sessions
                .get(id)
                .filter(|s| s.expires > Instant::now())
                .ok_or(Error::new(401, "SESSION_EXPIRED"))?;
            if mutation
                && !headers
                    .get("x-hud-csrf")
                    .is_some_and(|h| bool::from(h.as_bytes().ct_eq(s.csrf.as_bytes())))
            {
                return Err(Error::new(403, "CSRF_REJECTED"));
            }
            s.actor.clone()
        };
        if !a.permissions.contains(permission) {
            return Err(Error::new(403, "PERMISSION_DENIED"));
        }
        self.rate(
            &format!("{}:{permission}", a.subject),
            if permission == "planner.open" {
                6000
            } else {
                240
            },
        )?;
        Ok(a)
    }
    pub fn session(&self, headers: &HeaderMap) -> Result<(Actor, String), Error> {
        let s = cookie(headers)
            .and_then(|id| self.sessions.get(id))
            .filter(|s| s.expires > Instant::now())
            .ok_or(Error::new(401, "AUTH_REQUIRED"))?;
        Ok((s.actor.clone(), s.csrf.clone()))
    }
    pub fn logout(&mut self, headers: &HeaderMap) {
        if let Some(id) = cookie(headers) {
            self.sessions.remove(id);
        }
    }
}
fn cookie(headers: &HeaderMap) -> Option<&str> {
    headers
        .get("cookie")?
        .to_str()
        .ok()?
        .split(';')
        .find_map(|s| s.trim().strip_prefix("d4hud_session="))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn auth() -> Auth {
        Auth::new(vec![Credential {
            subject: "owner".into(),
            sha256: format!("{:x}", Sha256::digest(b"01234567890123456789012345678901")),
            permissions: ["hud.read".into(), "runtime.control".into()].into(),
        }])
    }
    #[test]
    fn cookie_mutation_requires_csrf_and_permission() {
        let mut auth = auth();
        let (id, csrf) = auth.login("01234567890123456789012345678901").unwrap();
        let mut headers = HeaderMap::new();
        headers.insert("cookie", format!("d4hud_session={id}").parse().unwrap());
        assert!(auth.actor(&headers, "hud.read", false).is_ok());
        assert_eq!(
            auth.actor(&headers, "runtime.control", true)
                .err()
                .unwrap()
                .code,
            "CSRF_REJECTED"
        );
        headers.insert("x-hud-csrf", csrf.parse().unwrap());
        assert!(auth.actor(&headers, "runtime.control", true).is_ok());
        assert_eq!(
            auth.actor(&headers, "report.submit", true)
                .err()
                .unwrap()
                .code,
            "PERMISSION_DENIED"
        );
        auth.logout(&headers);
        assert_eq!(
            auth.actor(&headers, "hud.read", false).err().unwrap().code,
            "SESSION_EXPIRED"
        );
    }
    #[test]
    fn rejected_login_is_rate_limited() {
        let mut auth = auth();
        for _ in 0..20 {
            assert_eq!(auth.login("invalid").unwrap_err().code, "AUTH_REQUIRED");
        }
        assert_eq!(auth.login("invalid").unwrap_err().code, "RATE_LIMIT");
    }
}

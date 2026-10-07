"""D4Planner lifecycle supervisor."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Protocol

from .model import RuntimeState, RuntimeStatus, can_transition
from .pathing import UserPathManager
from .store import (
    EventStore,
    RuntimePaths,
    atomic_write_json,
    iso_now,
    write_capture_config,
)
from .windows import RuntimeBlocked


class RuntimeAdapter(Protocol):
    def require_windows(self) -> None: ...
    def ensure_controller_runtime(self) -> Path: ...
    def controller_ready(self) -> bool: ...
    def addon_installed(self) -> bool: ...
    def ensure_addon_runtime(self) -> bool: ...
    def nvda_version(self) -> str | None: ...
    def nvda_version_compatible(self, version: str | None = None) -> bool: ...
    def active_console_session_id(self) -> int | None: ...
    def ensure_nvda_running(self, *, timeout: float = 15.0): ...
    def restart_nvda(self, *, timeout: float = 15.0): ...
    def nvda_process(self): ...
    def steam_process(self): ...
    def game_process(self): ...
    def probe_tolk(self): ...
    def process_started_before(self, process, timestamp: str | None) -> bool: ...
    def launch_game(self) -> None: ...
    def wait_for_game(self, *, timeout: float = 90.0): ...


class Supervisor:
    def __init__(
        self,
        *,
        paths: RuntimePaths,
        runtime: RuntimeAdapter,
        path_manager: UserPathManager,
        silent: bool = True,
        isolated: bool = False,
        poll_interval: float = 0.10,
        health_poll_interval: float = 2.0,
        game_start_timeout: float = 90.0,
        tolk_ready_timeout: float = 15.0,
        tolk_retry_interval: float = 0.5,
    ):
        self.paths = paths
        self.runtime = runtime
        self.path_manager = path_manager
        self.silent = silent
        self.isolated = isolated
        self.poll_interval = poll_interval
        self.health_poll_interval = health_poll_interval
        self.game_start_timeout = game_start_timeout
        self.tolk_ready_timeout = max(0.0, float(tolk_ready_timeout))
        self.tolk_retry_interval = max(0.01, float(tolk_retry_interval))
        self.store: EventStore | None = None
        self.status = RuntimeStatus(
            state=RuntimeState.STOPPED,
            updated_at=iso_now(),
            supervisor_pid=os.getpid(),
            silent=silent,
        )
        self._raw_offset = 0
        self._next_lease_refresh = 0.0

    @staticmethod
    def _steam_priority_allows_launch(steam: object) -> bool:
        priority = str(getattr(steam, "priority_class", None) or "").casefold()
        return priority in {"normal", "abovenormal", "high", "realtime"}

    def _wait_for_tolk_nvda(self):
        """Wait for NVDA's controller endpoint instead of trusting process presence alone."""
        deadline = time.monotonic() + self.tolk_ready_timeout
        health = self.runtime.probe_tolk()
        self.status.tolk = health
        while not health.ready and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(self.tolk_retry_interval, remaining))
            health = self.runtime.probe_tolk()
            self.status.tolk = health
        return health

    def _persist_status(self) -> None:
        self.status.updated_at = iso_now()
        atomic_write_json(self.paths.runtime_state, self.status.as_dict())

    def _safe_emit(self, event_type: str, data: dict[str, Any] | None = None):
        if not self.store:
            return None
        try:
            return self.store.emit(event_type, data)
        except (OSError, TypeError, ValueError) as exc:
            self.status.last_error = f"event sink failure: {type(exc).__name__}: {exc}"
            try:
                self._persist_status()
            except OSError:
                pass
            return None

    def _refresh_processes(self) -> None:
        try:
            self.status.active_console_session_id = self.runtime.active_console_session_id()
        except Exception:
            self.status.active_console_session_id = None
        try:
            self.status.nvda = self.runtime.nvda_process()
        except Exception:
            self.status.nvda = None
        try:
            self.status.steam = self.runtime.steam_process()
        except Exception:
            self.status.steam = None
        try:
            self.status.game = self.runtime.game_process()
        except Exception:
            self.status.game = None

    def transition(
        self,
        target: RuntimeState,
        detail: str,
        *,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        current = self.status.state
        if not can_transition(current, target):
            raise RuntimeError(f"invalid D4Planner transition: {current.value} -> {target.value}")
        self.status.state = target
        self.status.detail = detail
        self.status.last_error = error
        self._refresh_processes()
        self._persist_status()
        if self.store:
            event_data = {"detail": detail, "from": current.value, "to": target.value}
            if error:
                event_data["error"] = error
            if data:
                event_data.update(data)
            self._safe_emit(f"runtime.{target.value.casefold()}", event_data)

    def _create_session(self) -> None:
        self.store = EventStore.create(
            self.paths,
            silent=self.silent,
            metadata={
                "nvdaVersion": self.runtime.nvda_version(),
                "isolated": self.isolated,
            },
        )
        self.status.session_id = self.store.session.session_id
        self.status.session_dir = str(self.store.session.directory)
        self._persist_status()
        self._safe_emit(
            "runtime.start",
            {
                "detail": "D4Planner supervisor started",
                "pid": os.getpid(),
                "silent": self.silent,
                "isolated": self.isolated,
            },
        )

    def _block(self, detail: str, exc: Exception | None = None) -> RuntimeState:
        error = f"{type(exc).__name__}: {exc}" if exc else detail
        try:
            self.transition(RuntimeState.BLOCKED, detail, error=error)
        except RuntimeError:
            self.status.state = RuntimeState.BLOCKED
            self.status.detail = detail
            self.status.last_error = error
            self._persist_status()
        write_capture_config(self.paths, enabled=False)
        return self.status.state

    def bootstrap(self) -> RuntimeState:
        self.paths.ensure()
        try:
            self.paths.stop_request.unlink()
        except FileNotFoundError:
            pass
        self.transition(RuntimeState.BOOTSTRAPPING, "checking runtime")

        try:
            self._create_session()
            self.runtime.require_windows()

            # Fail before persistent PATH/runtime mutation when the proven NVDA
            # baseline is not present.
            nvda_version = self.runtime.nvda_version()
            if not self.runtime.nvda_version_compatible(nvda_version):
                raise RuntimeBlocked(
                    f"NVDA 2026.2 is required; detected {nvda_version or 'not installed'}"
                )
            self.status.extras["nvdaVersion"] = nvda_version

            controller = self.runtime.ensure_controller_runtime()
            self.status.extras["controllerDll"] = str(controller)

            path_change = None
            if not self.isolated:
                path_change = self.path_manager.ensure(self.paths.controller)
                self.status.extras["userPathManaged"] = True
                self.status.extras["userPathChanged"] = path_change.changed
                self.status.extras["userPathUpdatedAt"] = path_change.updated_at
            else:
                self.status.extras["userPathManaged"] = False

            addon_changed = self.runtime.ensure_addon_runtime()
            if not self.runtime.addon_installed():
                raise RuntimeBlocked("D4Planner NVDA add-on 0.2.0 is not installed correctly")

            console = self.runtime.active_console_session_id()
            if console is None:
                raise RuntimeBlocked("no active interactive Windows console session")

            existing_nvda = self.runtime.nvda_process()
            if addon_changed and existing_nvda:
                nvda = self.runtime.restart_nvda()
                self.status.extras["nvdaRestartReason"] = "add-on updated"
            else:
                nvda = self.runtime.ensure_nvda_running()
            if nvda.session_id != console:
                raise RuntimeBlocked(
                    f"NVDA SessionId={nvda.session_id} does not match active console SessionId={console}"
                )
            self.status.active_console_session_id = console
            self.status.nvda = nvda
            self.transition(RuntimeState.NVDA_READY, f"NVDA ready in Session {console}")

            health = self._wait_for_tolk_nvda()
            if not health.ready:
                game = self.runtime.game_process()
                self.status.game = game
                detail = (
                    "Tolk cannot detect NVDA"
                    + (f": {health.error}" if health.error else f" (reader={health.reader})")
                )
                if game:
                    if game.session_id != console:
                        raise RuntimeBlocked(
                            f"Diablo IV SessionId={game.session_id} does not match active console SessionId={console}"
                        )
                    self.transition(
                        RuntimeState.RESTART_REQUIRED,
                        "Diablo IV is already running but the Tolk backend is not NVDA; "
                        "exit Diablo IV normally and run start again",
                        error=detail,
                        data={
                            "pid": game.pid,
                            "reader": health.reader,
                            "speech": health.speech,
                        },
                    )
                    write_capture_config(self.paths, enabled=False)
                    return self.status.state
                raise RuntimeBlocked(detail)
            self.transition(
                RuntimeState.TOLK_READY,
                "Tolk detects NVDA and speech is available",
                data={"reader": health.reader, "speech": health.speech},
            )

            steam = self.runtime.steam_process()
            if self.isolated and steam:
                self.status.steam = steam
                self.transition(
                    RuntimeState.RESTART_REQUIRED,
                    "isolated mode cannot retrofit PATH into an existing Steam process; "
                    "exit Steam normally and run start --isolated again",
                    data={"steamPid": steam.pid},
                )
                write_capture_config(self.paths, enabled=False)
                return self.status.state

            managed_updated = self.path_manager.managed_updated_at() if not self.isolated else None
            if (
                not self.isolated
                and steam
                and self.runtime.process_started_before(steam, managed_updated)
            ):
                self.status.steam = steam
                self.transition(
                    RuntimeState.RESTART_REQUIRED,
                    "Steam predates D4Planner User PATH update; exit Steam normally and run start again",
                    data={"steamPid": steam.pid},
                )
                write_capture_config(self.paths, enabled=False)
                return self.status.state

            game = self.runtime.game_process()
            if game:
                if game.session_id != console:
                    raise RuntimeBlocked(
                        f"Diablo IV SessionId={game.session_id} does not match active console SessionId={console}"
                    )
                self.status.game = game
                self.transition(
                    RuntimeState.GAME_ATTACHED,
                    "attached to existing Diablo IV process without restart",
                    data={"pid": game.pid},
                )
            else:
                if steam and not self._steam_priority_allows_launch(steam):
                    priority = getattr(steam, "priority_class", None) or "unknown"
                    self.status.steam = steam
                    self.transition(
                        RuntimeState.RESTART_REQUIRED,
                        "Steam priority is not safe for automated game launch; restart Steam "
                        "normally through StreamOps before retrying",
                        data={"steamPid": steam.pid, "priorityClass": priority},
                    )
                    write_capture_config(self.paths, enabled=False)
                    return self.status.state
                self.transition(RuntimeState.GAME_STARTING, "launching Diablo IV through interactive task")
                self.runtime.launch_game()
                game = self.runtime.wait_for_game(timeout=self.game_start_timeout)
                if not game:
                    self.transition(
                        RuntimeState.WAITING_FOR_GAME,
                        "Diablo IV has not appeared yet; supervisor remains active",
                    )
                    write_capture_config(
                        self.paths,
                        enabled=True,
                        session=self.store.session if self.store else None,
                        silent=self.silent,
                        game_pid=None,
                    )
                    self.status.capture_active = True
                    self._persist_status()
                    return self.status.state
                if game.session_id != console:
                    raise RuntimeBlocked(
                        f"Diablo IV SessionId={game.session_id} does not match active console SessionId={console}"
                    )
                self.status.game = game
                self.transition(
                    RuntimeState.GAME_ATTACHED,
                    "Diablo IV started in active console session",
                    data={"pid": game.pid},
                )

            if not self.store:
                raise RuntimeBlocked("capture session not initialized")
            write_capture_config(
                self.paths,
                enabled=True,
                session=self.store.session,
                silent=self.silent,
                game_pid=game.pid,
            )
            self.status.capture_active = True
            self.transition(RuntimeState.CAPTURE_READY, "NVDA add-on capture enabled")
            self.transition(RuntimeState.RUNNING, "D4Planner runtime ready")
            return self.status.state
        except RuntimeBlocked as exc:
            return self._block(str(exc), exc)
        except Exception as exc:
            return self._block("unexpected bootstrap failure", exc)

    def _renew_capture_lease(self, *, force: bool = False) -> None:
        if not self.status.capture_active or not self.store:
            return
        now = time.monotonic()
        if not force and now < self._next_lease_refresh:
            return
        try:
            write_capture_config(
                self.paths,
                enabled=True,
                session=self.store.session,
                silent=self.silent,
                game_pid=self.status.game.pid if self.status.game else None,
                lease_seconds=5.0,
            )
            self._next_lease_refresh = now + 2.0
        except OSError as exc:
            # Do not crash. If renewal keeps failing, the add-on lease expires
            # and speech automatically passes through instead of staying silent.
            # Back off instead of retrying every supervisor poll tick.
            self._next_lease_refresh = now + 0.5
            self.status.last_error = f"capture lease renewal failed: {exc}"
            try:
                self._persist_status()
            except OSError:
                pass

    def _read_new_capture(self) -> int:
        if not self.store:
            return 0
        path = self.store.session.raw_speech_path
        if not path.exists():
            return 0
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(self._raw_offset)
            while True:
                line = handle.readline()
                if not line:
                    break
                self._raw_offset = handle.tell()
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                try:
                    unified = self.store.ingest_capture(event)
                except (OSError, TypeError, ValueError) as exc:
                    self.status.last_error = (
                        f"capture event sink failure: {type(exc).__name__}: {exc}"
                    )
                    self._persist_status()
                    continue
                self.status.last_event_at = str(unified["timestamp"])
                count += 1
        if count:
            self._persist_status()
        return count

    def _recover_nvda(self) -> None:
        current = self.runtime.nvda_process()
        if current and self.status.state != RuntimeState.DEGRADED:
            return

        if current is None:
            self.transition(RuntimeState.DEGRADED, "NVDA process exited; attempting recovery")
            try:
                write_capture_config(self.paths, enabled=False)
            except OSError:
                pass
            self.status.capture_active = False

        try:
            nvda = current or self.runtime.ensure_nvda_running()
            console = self.runtime.active_console_session_id()
            if nvda.session_id != console:
                raise RuntimeBlocked("restarted NVDA is not in the active console session")
            self.status.nvda = nvda

            # A live NVDA process is not enough. Tolk can still be SAPI/null after
            # NVDA restart, so never restore RUNNING until the real backend is
            # proven healthy again.
            health = self._wait_for_tolk_nvda()
            if not health.ready:
                detail = (
                    "NVDA is running but Tolk cannot detect NVDA"
                    + (f": {health.error}" if health.error else f" (reader={health.reader})")
                )
                try:
                    write_capture_config(self.paths, enabled=False)
                except OSError:
                    pass
                self.status.capture_active = False
                game = self.runtime.game_process()
                self.status.game = game
                if game and game.session_id != console:
                    self.status.last_error = (
                        f"game={game.session_id}, console={console}; {detail}"
                    )
                    self._persist_status()
                    return

                # Recovery is allowed to be temporarily DEGRADED: Tolk may need
                # a moment to reconnect to a freshly restarted NVDA instance.
                # Keep capture fail-open and retry on the next health interval
                # instead of declaring RUNNING or forcing a game restart.
                self.status.detail = "NVDA recovered; waiting for Tolk/NVDA backend"
                self.status.last_error = detail
                self._persist_status()
                return

            game = self.runtime.game_process()
            if game and game.session_id != console:
                self.status.game = game
                self.status.last_error = (
                    f"Diablo IV SessionId={game.session_id} does not match "
                    f"active console SessionId={console}"
                )
                self._persist_status()
                return

            self.status.game = game
            if self.store:
                write_capture_config(
                    self.paths,
                    enabled=True,
                    session=self.store.session,
                    silent=self.silent,
                    game_pid=game.pid if game else None,
                )
                self.status.capture_active = True
            target = RuntimeState.RUNNING if game else RuntimeState.WAITING_FOR_GAME
            self.transition(target, "NVDA/Tolk recovered")
        except Exception as exc:
            self.status.last_error = f"{type(exc).__name__}: {exc}"
            self._persist_status()

    def _watch_game(self) -> None:
        game = self.runtime.game_process()
        if game is None:
            self.status.game = None
            if self.status.state in {
                RuntimeState.RUNNING,
                RuntimeState.CAPTURE_READY,
                RuntimeState.GAME_ATTACHED,
            }:
                self.transition(RuntimeState.WAITING_FOR_GAME, "Diablo IV exited")
                self._renew_capture_lease(force=True)
            return

        if self.status.state == RuntimeState.WAITING_FOR_GAME:
            console = self.runtime.active_console_session_id()
            if game.session_id != console:
                self.transition(
                    RuntimeState.DEGRADED,
                    "Diablo IV returned in a different Windows session",
                    error=f"game={game.session_id}, console={console}",
                )
                return
            steam = self.runtime.steam_process()
            managed_updated = self.path_manager.managed_updated_at() if not self.isolated else None
            if (
                not self.isolated
                and steam
                and self.runtime.process_started_before(steam, managed_updated)
            ):
                self.transition(
                    RuntimeState.RESTART_REQUIRED,
                    "Steam environment is stale; exit Steam normally before continuing",
                )
                return
            health = self._wait_for_tolk_nvda()
            if not health.ready:
                detail = (
                    "Diablo IV returned but Tolk cannot detect NVDA"
                    + (f": {health.error}" if health.error else f" (reader={health.reader})")
                )
                write_capture_config(self.paths, enabled=False)
                self.status.capture_active = False
                self.status.game = game
                self.transition(
                    RuntimeState.RESTART_REQUIRED,
                    "Diablo IV returned but the Tolk backend is not NVDA; "
                    "exit Diablo IV normally and retry",
                    error=detail,
                    data={
                        "pid": game.pid,
                        "reader": health.reader,
                        "speech": health.speech,
                    },
                )
                return

            self.status.game = game
            self.transition(RuntimeState.GAME_ATTACHED, "Diablo IV detected and attached")
            self._renew_capture_lease(force=True)
            self.transition(RuntimeState.CAPTURE_READY, "capture remains enabled")
            self.transition(RuntimeState.RUNNING, "D4Planner runtime ready")
            return

        current = self.status.game
        if current is None or current.pid != game.pid:
            console = self.runtime.active_console_session_id()
            if game.session_id != console:
                self.transition(
                    RuntimeState.DEGRADED,
                    "Diablo IV process changed into a different Windows session",
                    error=f"game={game.session_id}, console={console}",
                )
                return
            health = self.runtime.probe_tolk()
            self.status.tolk = health
            if not health.ready:
                detail = (
                    "Diablo IV process changed but Tolk cannot detect NVDA"
                    + (f": {health.error}" if health.error else f" (reader={health.reader})")
                )
                write_capture_config(self.paths, enabled=False)
                self.status.capture_active = False
                self.status.game = game
                self.transition(
                    RuntimeState.RESTART_REQUIRED,
                    "Diablo IV process changed but the Tolk backend is not NVDA; "
                    "exit Diablo IV normally and retry",
                    error=detail,
                    data={
                        "pid": game.pid,
                        "reader": health.reader,
                        "speech": health.speech,
                    },
                )
                return

            previous_pid = current.pid if current else None
            self.status.game = game
            self._renew_capture_lease(force=True)
            self._persist_status()
            self._safe_emit(
                "runtime.game_context_changed",
                {
                    "detail": "Diablo IV PID changed without an observable stopped interval",
                    "previousPid": previous_pid,
                    "pid": game.pid,
                },
            )

    def run(self) -> int:
        state = self.bootstrap()
        if state in {RuntimeState.BLOCKED, RuntimeState.RESTART_REQUIRED}:
            return 2 if state == RuntimeState.BLOCKED else 3

        try:
            next_health_check = 0.0
            while not self.paths.stop_request.exists():
                # Capture promotion is latency-sensitive. Process/session health
                # checks are deliberately slower because the Windows adapter may
                # use OS probes that are much more expensive than tailing JSONL.
                self._renew_capture_lease()
                self._read_new_capture()
                now = time.monotonic()
                if now >= next_health_check:
                    self._recover_nvda()
                    self._watch_game()
                    next_health_check = now + self.health_poll_interval
                if self.status.state in {RuntimeState.BLOCKED, RuntimeState.RESTART_REQUIRED}:
                    break
                time.sleep(self.poll_interval)
        finally:
            shutdown_error = self.status.last_error
            try:
                write_capture_config(self.paths, enabled=False)
            except OSError as exc:
                # Capture is already protected by a short lease. If this write
                # fails, the add-on will fail open as soon as the lease expires.
                shutdown_error = (
                    f"failed to disable capture during shutdown: {type(exc).__name__}: {exc}"
                )
                self.status.last_error = shutdown_error
            self.status.capture_active = False
            if self.store:
                self._safe_emit("runtime.stop", {"detail": "D4Planner supervisor stopped"})
            if can_transition(self.status.state, RuntimeState.STOPPED):
                self.transition(
                    RuntimeState.STOPPED,
                    "D4Planner stopped; game and Steam left untouched",
                    error=shutdown_error,
                )
            else:
                self.status.state = RuntimeState.STOPPED
                self.status.detail = "D4Planner stopped; game and Steam left untouched"
                self.status.last_error = shutdown_error
                self._persist_status()
            try:
                self.paths.stop_request.unlink()
            except FileNotFoundError:
                pass
        return 0

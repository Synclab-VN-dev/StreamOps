use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};

#[derive(Debug, PartialEq, Eq, Copy, Clone)]
pub enum ShortcutAction {
    Toggle,
    Exit,
}

pub fn toggle_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F10)
}

pub fn exit_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F11)
}

pub fn shortcut_action(
    pressed: &Shortcut,
    state: ShortcutState,
    toggle: &Shortcut,
    exit: &Shortcut,
) -> Option<ShortcutAction> {
    if state != ShortcutState::Pressed {
        return None;
    }
    if pressed == exit {
        Some(ShortcutAction::Exit)
    } else if pressed == toggle {
        Some(ShortcutAction::Toggle)
    } else {
        None
    }
}

/// Keep the cached state unchanged if the OS refuses the cursor hit-testing
/// transition. Calling the setter even for an unchanged value is intentional:
/// it reconciles the OS and the cached state after startup/recovery.
pub fn transition_mode<F>(current: &mut bool, interactive: bool, mut set_ignore: F) -> Result<(), String>
where
    F: FnMut(bool) -> Result<(), String>,
{
    set_ignore(!interactive)?;
    *current = interactive;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shortcuts_have_exact_modifiers_and_distinct_f_keys() {
        let toggle = toggle_shortcut();
        let exit = exit_shortcut();
        assert_ne!(toggle, exit);
        assert_eq!(toggle, Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F10));
        assert_eq!(exit, Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::F11));
    }

    #[test]
    fn key_down_dispatches_but_key_up_and_unrelated_shortcuts_are_ignored() {
        let toggle = toggle_shortcut();
        let exit = exit_shortcut();
        let foreign = Shortcut::new(Some(Modifiers::ALT), Code::F10);
        assert_eq!(shortcut_action(&toggle, ShortcutState::Pressed, &toggle, &exit), Some(ShortcutAction::Toggle));
        assert_eq!(shortcut_action(&exit, ShortcutState::Pressed, &toggle, &exit), Some(ShortcutAction::Exit));
        assert_eq!(shortcut_action(&toggle, ShortcutState::Released, &toggle, &exit), None);
        assert_eq!(shortcut_action(&exit, ShortcutState::Released, &toggle, &exit), None);
        assert_eq!(shortcut_action(&foreign, ShortcutState::Pressed, &toggle, &exit), None);
    }

    #[test]
    fn interactive_passive_interactive_roundtrip_updates_native_hit_testing() {
        let mut mode = true;
        let mut requests = Vec::new();
        for next in [false, true, false, true] {
            transition_mode(&mut mode, next, |ignore| { requests.push(ignore); Ok(()) }).unwrap();
            assert_eq!(mode, next);
        }
        assert_eq!(requests, vec![true, false, true, false]);
    }

    #[test]
    fn failure_to_apply_cursor_mode_does_not_corrupt_state() {
        let mut mode = true;
        let result = transition_mode(&mut mode, false, |_ignore| Err("OS error".into()));
        assert_eq!(result.unwrap_err(), "OS error");
        assert!(mode, "must remain interactive on Windows API failure");
        // A user can still recover after the failure.
        transition_mode(&mut mode, false, |ignore| { assert!(ignore); Ok(()) }).unwrap();
        assert!(!mode);
    }

    #[test]
    fn same_mode_reapplies_native_setting_for_recovery() {
        let mut mode = true;
        let mut calls = 0;
        transition_mode(&mut mode, true, |ignore| { assert!(!ignore); calls += 1; Ok(()) }).unwrap();
        assert_eq!(calls, 1);
        assert!(mode);
    }
}

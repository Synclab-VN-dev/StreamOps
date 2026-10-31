use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};

#[derive(Debug, PartialEq, Eq, Copy, Clone)]
pub enum ShortcutAction {
    Toggle,
    Exit,
}

pub const MIN_OVERLAY_WIDTH: u32 = 280;
pub const MAX_OVERLAY_WIDTH: u32 = 900;
pub const MIN_OVERLAY_HEIGHT: u32 = 220;
pub const MAX_OVERLAY_HEIGHT: u32 = 640;

pub fn validated_extent(width: u32, height: u32) -> Result<(u32, u32), String> {
    if !(MIN_OVERLAY_WIDTH..=MAX_OVERLAY_WIDTH).contains(&width)
        || !(MIN_OVERLAY_HEIGHT..=MAX_OVERLAY_HEIGHT).contains(&height)
    {
        return Err("overlay extent is outside the approved HUD bounds".into());
    }
    Ok((width, height))
}

pub fn clamp_origin(
    origin: (i32, i32),
    extent: (u32, u32),
    monitor_origin: (i32, i32),
    monitor_extent: (u32, u32),
) -> (i32, i32) {
    let maximum_x = monitor_origin.0 + monitor_extent.0.saturating_sub(extent.0) as i32;
    let maximum_y = monitor_origin.1 + monitor_extent.1.saturating_sub(extent.1) as i32;
    (
        origin.0.clamp(monitor_origin.0, maximum_x.max(monitor_origin.0)),
        origin.1.clamp(monitor_origin.1, maximum_y.max(monitor_origin.1)),
    )
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

    #[test]
    fn approved_extent_is_bounded_and_rejects_an_oversized_hit_test_surface() {
        assert_eq!(validated_extent(886, 620).unwrap(), (886, 620));
        assert!(validated_extent(901, 620).is_err());
        assert!(validated_extent(886, 641).is_err());
        assert!(validated_extent(100, 100).is_err());
    }

    #[test]
    fn multi_monitor_origin_is_clamped_in_physical_coordinates() {
        assert_eq!(clamp_origin((-1800, 40), (900, 640), (-1920, 0), (1920, 1080)), (-1800, 40));
        assert_eq!(clamp_origin((-2500, -100), (900, 640), (-1920, 0), (1920, 1080)), (-1920, 0));
        assert_eq!(clamp_origin((-500, 900), (900, 640), (-1920, 0), (1920, 1080)), (-900, 440));
    }
}

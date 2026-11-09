#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    if args.get(1).is_some_and(|a| a == "--planner-unpack") {
        let ok = args.len() == 5 && d4planner_report_issue::snapshot_unpack::unpack(
            std::path::Path::new(&args[2]), std::path::Path::new(&args[3]),
            std::path::Path::new(&args[4])).is_ok();
        std::process::exit(if ok { 0 } else { 2 });
    }
    d4planner_overlay_poc_lib::run();
}

//! Clipboard stays on the desktop host; Web uses the requesting browser clipboard.
pub fn write(text: &str, owner: usize) -> Result<(), String> {
    if text.len() > 1_000_000 || text.contains('\0') {return Err("CHARACTER_EXPORT_TOO_LARGE".into());}
    #[cfg(windows)]
    { windows::write(text, owner) }
    #[cfg(not(windows))]
    { let _=owner; Err("CLIPBOARD_UNAVAILABLE".into()) }
}

#[cfg(windows)]
mod windows {
    use std::ffi::c_void;
    #[link(name="user32")]
    extern "system" {
        fn OpenClipboard(owner:*mut c_void)->i32;
        fn CloseClipboard()->i32;
        fn EmptyClipboard()->i32;
        fn SetClipboardData(format:u32, data:*mut c_void)->*mut c_void;
    }
    #[link(name="kernel32")]
    extern "system" {
        fn GlobalAlloc(flags:u32, bytes:usize)->*mut c_void;
        fn GlobalLock(memory:*mut c_void)->*mut c_void;
        fn GlobalUnlock(memory:*mut c_void)->i32;
        fn GlobalFree(memory:*mut c_void)->*mut c_void;
    }
    pub fn write(text:&str, owner:usize)->Result<(),String>{unsafe{
        let utf16:Vec<u16>=text.encode_utf16().chain(Some(0)).collect();
        let memory=GlobalAlloc(0x0002,utf16.len()*2);
        if memory.is_null(){return Err("CLIPBOARD_UNAVAILABLE".into());}
        let ptr=GlobalLock(memory);
        if ptr.is_null(){GlobalFree(memory);return Err("CLIPBOARD_UNAVAILABLE".into());}
        std::ptr::copy_nonoverlapping(utf16.as_ptr(),ptr.cast::<u16>(),utf16.len());GlobalUnlock(memory);
        if OpenClipboard(owner as *mut c_void)==0 {GlobalFree(memory);return Err("CLIPBOARD_UNAVAILABLE".into());}
        let success=EmptyClipboard()!=0 && !SetClipboardData(13,memory).is_null();
        CloseClipboard();
        if success {Ok(())} else {GlobalFree(memory);Err("CLIPBOARD_UNAVAILABLE".into())}
    }}
}
